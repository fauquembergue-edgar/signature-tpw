from flask import Flask, request, render_template, send_from_directory, jsonify
import os
import uuid
import json
import smtplib
import base64
from email.message import EmailMessage
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas as pdfcanvas
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

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SESSION_FOLDER, exist_ok=True)
os.makedirs(TEMPLATES_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

def get_pdf_page_size(pdf_path, page_num=0):
    reader = PdfReader(pdf_path)
    mediabox = reader.pages[page_num].mediabox
    width = float(mediabox.width)
    height = float(mediabox.height)
    print("PDF Page Size (points):", width, height)
    return width, height

def html_to_pdf_coords(x_html, y_html, h_zone, html_w, html_h, pdf_w, pdf_h):
    scale_x = pdf_w / html_w
    scale_y = pdf_h / html_h
    x_pdf = x_html * scale_x
    y_pdf = (html_h - y_html - h_zone) * scale_y
    print(f"[COORD] HTML({x_html},{y_html}) h={h_zone} -> PDF({x_pdf:.2f},{y_pdf:.2f})")
    return x_pdf, y_pdf

def merge_overlay(pdf_path, overlay_pdf, output_path=None, page_num=0):
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    overlay_reader = PdfReader(overlay_pdf)
    for i, page in enumerate(reader.pages):
        if i == page_num:
            page.merge_page(overlay_reader.pages[0])
        writer.add_page(page)
    if output_path:
        with open(output_path, 'wb') as f:
            writer.write(f)
    else:
        with open(pdf_path, 'wb') as f:
            writer.write(f)

def apply_text(pdf_path, x_px, y_px, text, html_width_px, html_height_px, field_height=40, page_num=0):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    font_size = 14
    x_pdf, y_pdf = html_to_pdf_coords(x_px, y_px, field_height, html_width_px, html_height_px, pdf_width, pdf_height)
    y_pdf += field_height - font_size  # Remonter baseline du texte
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))
    can.setFont("Helvetica", font_size)
    can.setFillColorRGB(0, 0, 0)
    can.drawString(x_pdf, y_pdf, text)
    can.save()
    packet.seek(0)
    merge_overlay(pdf_path, packet, output_path=pdf_path, page_num=page_num)

def apply_signature(pdf_path, sig_data, output_path, x_px, y_px, html_width_px, html_height_px, field_height=40, page_num=0):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    width, height = 100, field_height
    x_pdf, y_pdf = html_to_pdf_coords(x_px, y_px, height, html_width_px, html_height_px, pdf_width, pdf_height)
    if sig_data.startswith("data:image/png;base64,"):
        sig_data = sig_data.split(",", 1)[1]
    image_bytes = base64.b64decode(sig_data)
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))
    img_io = io.BytesIO()
    image.save(img_io, format="PNG")
    img_io.seek(0)
    can.drawImage(ImageReader(img_io), x_pdf, y_pdf, width=width, height=height, mask='auto')
    can.save()
    packet.seek(0)
    merge_overlay(pdf_path, packet, output_path=output_path, page_num=page_num)

def apply_static_text_fields(
    pdf_path,
    fields,
    output_path=None,
    page_num=0,
    offset_x=60,  # Décalage horizontal par défaut : 60 points à droite
    offset_y=-30  # Décalage vertical par défaut : 30 points vers le bas (négatif pour descendre)
):
    from reportlab.pdfgen import canvas as pdfcanvas
    from PyPDF2 import PdfReader, PdfWriter
    import io

    # Ratios calculés selon tes exemples (à adapter si besoin)
    ratio_x = 0.6667
    ratio_y = 0.6667

    font_size = 14  # à adapter si besoin

    pdf_reader = PdfReader(pdf_path)
    page = pdf_reader.pages[page_num]
    pdf_width = float(page.mediabox.width)
    pdf_height = float(page.mediabox.height)

    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))

    for field in fields:
        if field.get("type") == "statictext":
            x_front = field.get("x", 0)
            y_front = field.get("y", 0)
            value = field.get("value", "")

            x_pdf = x_front * ratio_x + offset_x  # Décalage à droite
            # Inversion de l'axe Y + décalage vers le bas
            y_pdf = pdf_height - (y_front * ratio_y) + offset_y

            can.setFont("Helvetica", font_size)
            can.setFillColorRGB(0, 0, 0)
            can.drawString(x_pdf, y_pdf, value)

    can.save()
    packet.seek(0)

    overlay_pdf = PdfReader(packet)
    writer = PdfWriter()
    for i, p in enumerate(pdf_reader.pages):
        page = p
        if i == page_num:
            page.merge_page(overlay_pdf.pages[0])
        writer.add_page(page)

    with open(output_path or pdf_path, "wb") as f:
        writer.write(f)
        
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
                "done": all(f.get("signed") for f in data["fields"] if f["type"] != "statictext")
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
        field['step'] = i
        field['page'] = field.get('page', 0)
        if 'h' not in field:
            if field['type'] == 'signature':
                field['h'] = 40
            elif field['type'] == 'checkbox':
                field['h'] = 15
            else:
                field['h'] = 40
    pdf_path = os.path.join(UPLOAD_FOLDER, data['pdf'])
    # Valeurs fixes du canvas HTML utilisé pour placer les zones (doivent matcher le front)
    html_width_px = 931.5
    html_height_px = 1250
    apply_static_text_fields(pdf_path, fields, output_path=None)
    session_data = {
        'pdf': data['pdf'],
        'fields': fields,
        'email_message': message,
        'nom_demande': nom_demande
    }
    session_file_path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    with open(session_file_path, 'w') as f:
        json.dump(session_data, f)
    send_email(session_id, step=0)
    return render_template("notified.html", session_id=session_id)

@app.route('/sign/<session_id>/<int:step>')
def sign(session_id, step):
    path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    with open(path) as f:
        session_data = json.load(f)
    fields = [f for f in session_data['fields'] if f.get('step', 0) == step]
    return render_template(
        'sign.html',
        fields_json=fields,
        pdf=session_data['pdf'],
        session_id=session_id,
        step=step,
        email=fields[0]['email'],
        fields_all=session_data['fields']
    )

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
    page_num = field.get('page', 0)
    field_height = data.get('field_height', field.get('h', 40))
    x_px = data['x_px']
    y_px = data['y_px']
    html_width_px = data['html_width_px']
    html_height_px = data['html_height_px']

    if field['type'] == 'signature':
        new_pdf_name = f"signed_{uuid.uuid4()}.pdf"
        new_pdf_path = os.path.join(UPLOAD_FOLDER, new_pdf_name)
        apply_signature(pdf_path, field['value'], new_pdf_path, x_px, y_px, html_width_px, html_height_px, field_height=field_height, page_num=page_num)
        session_data['pdf'] = new_pdf_name
    elif field['type'] == 'checkbox':
        apply_checkbox(pdf_path, x_px, y_px, data['value'] in ['true','on','1', True], html_width_px, html_height_px, field_height=field_height, page_num=page_num)
    else:
        apply_text(pdf_path, x_px, y_px, data['value'], html_width_px, html_height_px, field_height=field_height, page_num=page_num)

    with open(session_path, 'w') as f:
        json.dump(session_data, f)
    return jsonify({'status': 'ok'})

@app.route('/finalise-signature', methods=['POST'])
def finalise_signature():
    data = request.get_json()
    session_path = os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")
    with open(session_path) as f:
        session_data = json.load(f)
    if 'message_final' in data:
        session_data['message_final'] = data['message_final']
    all_fields = session_data['fields']
    current_step = max(f['step'] for f in all_fields if f['signed']) if any(f['signed'] for f in all_fields) else 0
    remaining_same = [f for f in all_fields if f['step']==current_step and not f['signed'] and f["type"] != "statictext"]
    if remaining_same:
        return jsonify({'status': 'incomplete'})
    remaining = [f for f in all_fields if not f['signed'] and f["type"] != "statictext"]
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
    done = all(f['signed'] for f in data['fields'] if f["type"] != "statictext")
    return f"<h2>Signature terminée : {'✅ OUI' if done else '❌ NON'}</h2>"

def send_email(session_id, step):
    session_file = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    if not os.path.isfile(session_file) or os.path.getsize(session_file) == 0:
        print("Le fichier de session est vide ou absent.")
        return
    with open(session_file) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("Erreur : fichier JSON vide ou corrompu")
            return
    recipient = next((fld['email'] for fld in data['fields'] if fld.get('step', 0) == step and fld["type"] != "statictext"), None)
    if not recipient:
        return
    app_url = os.getenv('APP_URL', 'http://localhost:5000')
    link = f"{app_url}/sign/{session_id}/{step}"
    msg = EmailMessage()
    msg['Subject'] = 'Signature requise'
    msg['From'] = os.getenv('SMTP_USER')
    msg['To'] = recipient
    body = data.get('email_message') or f"Bonjour, veuillez signer ici : {link}"
    if link not in body:
        body = f"{body}\n{link}"
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
            log.write(f"[ERROR] send_email to {recipient} at step {step}: {e}\n")

def send_pdf_to_all(session_data):
    pdf_name = session_data.get('pdf')
    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name)
    if not os.path.isfile(pdf_path):
        return
    with open(pdf_path, 'rb') as f:
        content = f.read()
    sent = set()
    message_final = session_data.get('message_final', '')
    for fld in session_data['fields']:
        recipient = fld.get('email')
        if not recipient or recipient in sent:
            continue
        sent.add(recipient)
        msg = EmailMessage()
        msg['Subject'] = 'Document signé final'
        msg['From'] = os.getenv('SMTP_USER')
        msg['To'] = recipient
        body = 'Voici le PDF final signé.'
        if message_final:
            body += f"\n\nMessage du signataire :\n{message_final}"
        msg.set_content(body)
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
                log.write(f"[ERROR] send_pdf_to_all to {recipient}: {e}\n")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
