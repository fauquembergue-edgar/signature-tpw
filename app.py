from flask import Flask, request, render_template, send_from_directory, jsonify
import os
import uuid
import json
import smtplib
import base64
from email.message import EmailMessage
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.pagesizes import letter
from dotenv import load_dotenv
import io
from PIL import Image
from reportlab.lib.utils import ImageReader

load_dotenv()

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
SESSION_FOLDER = 'sessions'
TEMPLATES_FOLDER = 'templates_data'
LOG_FOLDER = 'logs'

# create folders
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SESSION_FOLDER, exist_ok=True)
os.makedirs(TEMPLATES_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

@app.route('/')
def index():
    sessions = {}
    for filename in os.listdir(SESSION_FOLDER):
        if filename.endswith(".json"):
            sid = filename.replace(".json", "")
            with open(os.path.join(SESSION_FOLDER, filename)) as f:
                data = json.load(f)
            sessions[sid] = {
                "pdf": data["pdf"],
                "name": data.get("nom_demande", ""),
                "fields": data["fields"],
                "done": all(f.get("signed") for f in data["fields"])
            }
    templates = [f.replace('.json', '') for f in os.listdir(TEMPLATES_FOLDER) if f.endswith('.json')]
    return render_template("index.html", templates=templates, sessions=sessions)

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['pdf']
    filename = f"{uuid.uuid4()}.pdf"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    return jsonify({'filename': filename})

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/save-template', methods=['POST'])
def save_template():
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify({'error': 'Nom de template requis'}), 400
    path = os.path.join(TEMPLATES_FOLDER, f"{name}.json")
    with open(path, 'w') as f:
        json.dump({'pdf': data['pdf'], 'fields': data['fields']}, f)
    return jsonify({'status': 'saved'})

@app.route('/load-template/<name>')
def load_template(name):
    path = os.path.join(TEMPLATES_FOLDER, f"{name}.json")
    if not os.path.exists(path):
        return jsonify({'error': 'Template introuvable'}), 404
    with open(path) as f:
        return jsonify(json.load(f))

@app.route('/define-fields', methods=['POST'])
def define_fields():
    data = json.loads(request.form['fields_json'])
    message = request.form.get('email_message', '')
    nom_demande = request.form.get('nom_demande', '')
    session_id = str(uuid.uuid4())
    fields = data['fields']
    for i, field in enumerate(fields):
        field['signed'] = False
        field['value'] = ''
        field['step'] = i
    session_data = {
        'pdf': data['pdf'],
        'fields': fields,
        'email_message': message,
        'nom_demande': nom_demande
    }
    with open(os.path.join(SESSION_FOLDER, f"{session_id}.json"), 'w') as f:
        json.dump(session_data, f)
    send_email(session_id, step=0)
    return render_template("notified.html", session_id=session_id)

@app.route('/sign/<session_id>/<int:step>')
def sign(session_id, step):
    path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    with open(path) as f:
        session_data = json.load(f)
    fields = [f for f in session_data['fields'] if f.get('step', 0) == step]
    return render_template('sign.html',
                           fields_json=fields,
                           pdf=session_data['pdf'],
                           session_id=session_id,
                           step=step,
                           email=fields[0]['email'],
                           fields_all=session_data['fields'])

@app.route('/fill-field', methods=['POST'])
def fill_field():
    data = request.get_json()
    session_path = os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")
    with open(session_path) as f:
        session_data = json.load(f)
    field = session_data['fields'][data['field_index']]
    field['value'] = data['value']
    field['signed'] = True
    pdf_path = os.path.join(UPLOAD_FOLDER, session_data['pdf'])

    # Determine if clicked coords provided (new integration)
    if 'x_px' in data and 'y_px' in data and 'scale_x' in data and 'scale_y' in data and 'html_height_px' in data:
        x_px = data['x_px']
        y_px = data['y_px']
        html_height_px = data['html_height_px']
        scale_x = data['scale_x']
        scale_y = data['scale_y']

        if field['type'] == 'signature':
            new_pdf_name = f"signed_{uuid.uuid4()}.pdf"
            new_pdf_path = os.path.join(UPLOAD_FOLDER, new_pdf_name)
            apply_signature(pdf_path,
                            field['value'],
                            new_pdf_path,
                            x_px, y_px,
                            html_height_px,
                            scale_x, scale_y)
            session_data['pdf'] = new_pdf_name
        elif field['type'] == 'checkbox':
            apply_checkbox(pdf_path,
                           x_px, y_px,
                           data['value'] in ['true','on','1'],
                           html_height_px,
                           scale_x, scale_y)
        else:
            apply_text(pdf_path,
                       x_px, y_px,
                       data['value'],
                       html_height_px,
                       scale_x, scale_y)
    else:
        # Fallback to legacy coordinates
        x = field.get('x')
        y = field.get('y')
        if field['type'] == 'signature':
            new_pdf_name = f"signed_{uuid.uuid4()}.pdf"
            new_pdf_path = os.path.join(UPLOAD_FOLDER, new_pdf_name)
            apply_signature(pdf_path,
                            field['value'],
                            new_pdf_path,
                            x, y)
            session_data['pdf'] = new_pdf_name
        elif field['type'] == 'checkbox':
            apply_checkbox(pdf_path,
                           x, y,
                           data['value'] in ['true','on','1'])
        else:
            apply_text(pdf_path,
                       x, y,
                       data['value'])

    # Save updated session data
    with open(session_path, 'w') as f:
        json.dump(session_data, f)
    return jsonify({'status': 'ok'})

@app.route('/finalise-signature', methods=['POST'])
def finalise_signature():
    data = request.get_json()
    session_path = os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")
    with open(session_path) as f:
        session_data = json.load(f)
    all_fields = session_data['fields']
    current_step = max(f['step'] for f in all_fields if f['signed']) if any(f['signed'] for f in all_fields) else 0
    remaining_same = [f for f in all_fields if f['step']==current_step and not f['signed']]
    if remaining_same:
        return jsonify({'status': 'incomplete'})
    remaining = [f for f in all_fields if not f['signed']]
    if remaining:
        next_step = min(f['step'] for f in remaining)
        send_email(data['session_id'], next_step)
    else:
        send_pdf_to_all(session_data)
    with open(session_path, 'w') as f:
        json.dump(session_data, f)
    return jsonify({'status': 'finalised'})

@app.route('/session/<session_id>/status')
def status(session_id):
    path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    with open(path) as f:
        data = json.load(f)
    done = all(f['signed'] for f in data['fields'])
    return f"<h2>Signature terminée : {'✅ OUI' if done else '❌ NON'}</h2>"

# --- Rendering functions using client-side scales ---
def apply_text(pdf_path, x_px, y_px, text, html_height_px, scale_x, scale_y):
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)

    x_pdf = x_px * scale_x
    y_pdf = (html_height_px - y_px) * scale_y

    can.setFont("Helvetica", 12)
    can.drawString(x_pdf, y_pdf, text)
    can.save()

    packet.seek(0)
    overlay = PdfReader(packet)
    for i, page in enumerate(reader.pages):
        if i == 0:
            page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with open(pdf_path, 'wb') as f:
        writer.write(f)


def apply_signature(pdf_path, sig_data, output_path, x_px, y_px, html_height_px, scale_x, scale_y):
    width, height = 100, 40
    x_pdf = x_px * scale_x - width/2
    y_pdf = (html_height_px - y_px) * scale_y - height/2

    if sig_data.startswith("data:image/png;base64,"):
        sig_data = sig_data.split(",",1)[1]
    image_bytes = base64.b64decode(sig_data)
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)
    img_io = io.BytesIO()
    image.save(img_io, format="PNG")
    img_io.seek(0)
    can.drawImage(ImageReader(img_io), x_pdf, y_pdf, width=width, height=height, mask='auto')
    can.save()

    packet.seek(0)
    overlay = PdfReader(packet)
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i == 0:
            page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with open(output_path, 'wb') as f:
        writer.write(f)


def apply_checkbox(pdf_path, x_px, y_px, checked, html_height_px, scale_x, scale_y, size=15):
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)

    x_pdf = x_px * scale_x - size/2
    y_pdf = (html_height_px - y_px) * scale_y - size/2

    can.rect(x_pdf, y_pdf, size, size)
    if checked:
        can.setLineWidth(2)
        can.line(x_pdf, y_pdf, x_pdf+size, y_pdf+size)
        can.line(x_pdf, y_pdf+size, x_pdf+size, y_pdf)
    can.save()

    packet.seek(0)
    overlay = PdfReader(packet)
    for i, page in enumerate(reader.pages):
        if i == 0:
            page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with open(pdf_path, 'wb') as f:
        writer.write(f)


def save_signature_image(data_url, session_id, index):
    if data_url.startswith("data:image/png;base64,"):
        data_url = data_url.split(",",1)[1]
    sig_data = base64.b64decode(data_url)
    sig_path = os.path.join(UPLOAD_FOLDER, f"{session_id}_sig_{index}.png")
    with open(sig_path, 'wb') as f:
        f.write(sig_data)
    return sig_path

# --- Email and PDF Sending Functions ---

def send_email(session_id, step):
    """
    Envoie un email au signataire de l'étape `step` pour lui demander de signer.
    """
    session_file = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    with open(session_file) as f:
        data = json.load(f)
    recipient = next((fld['email'] for fld in data['fields'] if fld.get('step', 0) == step), None)
    if not recipient:
        return
    app_url = os.getenv('APP_URL', 'http://localhost:5000')
    link = f"{app_url}/sign/{session_id}/{step}"
    msg = EmailMessage()
    msg['Subject'] = 'Signature requise'
    msg['From'] = os.getenv('SMTP_USER')
    msg['To'] = recipient
    body = data.get('email_message') or f"Bonjour, veuillez signer ici : {link}"
    # Ajouter le lien si pas présent
    if link not in body:
        body = body + " " + link
    msg.set_content(body)
    try:
        smtp_server = os.getenv('SMTP_SERVER')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_user = os.getenv('SMTP_USER')
        smtp_pass = os.getenv('SMTP_PASS')
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    except Exception as e:
        with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
            log.write(f"[ERROR] envoi email vers {recipient} étape {step} : {e}
")


def send_pdf_to_all(session_data):
    """
    Envoie le PDF final signé à tous les destinataires uniques.
    """
    pdf_name = session_data.get('pdf')
    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name)
    if not os.path.isfile(pdf_path):
        return
    with open(pdf_path, 'rb') as f:
        content = f.read()
    sent = set()
    for fld in session_data['fields']:
        recipient = fld.get('email')
        if not recipient or recipient in sent:
            continue
        sent.add(recipient)
        msg = EmailMessage()
        msg['Subject'] = 'Document signé final'
        msg['From'] = os.getenv('SMTP_USER')
        msg['To'] = recipient
        msg.set_content('Voici le PDF final signé.')
        msg.add_attachment(content,
                           maintype='application',
                           subtype='pdf',
                           filename='document_final.pdf')
        try:
            smtp_server = os.getenv('SMTP_SERVER')
            smtp_port = int(os.getenv('SMTP_PORT', 587))
            smtp_user = os.getenv('SMTP_USER')
            smtp_pass = os.getenv('SMTP_PASS')
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        except Exception as e:
            with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
                log.write(f"[ERROR] envoi PDF final à {recipient} : {e}
")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
