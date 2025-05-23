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

for folder in [UPLOAD_FOLDER, SESSION_FOLDER, LOG_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

@app.route('/')
def index():
    sessions = {}
    for fname in os.listdir(SESSION_FOLDER):
        if fname.endswith('.json'):
            sid = fname.replace('.json', '')
            with open(os.path.join(SESSION_FOLDER, fname)) as f:
                data = json.load(f)
                sessions[sid] = {
                    "pdf": data["pdf"],
                    "name": data.get("nom_demande", ""),
                    "fields": data["fields"],
                    "done": all(f.get("signed") for f in data["fields"]),
                    "email_message": data.get("email_message", "")
                }
    templates = [f.replace('.json', '') for f in os.listdir(TEMPLATES_FOLDER) if f.endswith('.json')]
    return render_template("index.html", templates=templates, sessions=sessions)

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['pdf']
    filename = str(uuid.uuid4()) + '.pdf'
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
    with open(os.path.join(TEMPLATES_FOLDER, f"{name}.json"), 'w') as f:
        json.dump({'pdf': data['pdf'], 'fields': data['fields']}, f)
    return jsonify({'status': 'saved'})

@app.route('/define-fields', methods=['POST'])
def define_fields():
    data = request.get_json()
    sid = data['session_id']
    with open(os.path.join(TEMPLATES_FOLDER, f"{data['template']}.json")) as f:
        tmpl = json.load(f)
    sessions_data = {
        'pdf': tmpl['pdf'],
        'fields': tmpl['fields'],
        'nom_demande': data.get('nom_demande', ''),
        'email_message': data.get('message', ''),
        'done': False
    }
    with open(os.path.join(SESSION_FOLDER, f"{sid}.json"), 'w') as f:
        json.dump(sessions_data, f)
    send_email(sid, 1)
    return jsonify({'status': 'started'})

@app.route('/sign/<session_id>/<int:step>')
def sign_page(session_id, step):
    with open(os.path.join(SESSION_FOLDER, f"{session_id}.json")) as f:
        session_data = json.load(f)
    fields = [f for f in session_data['fields'] if f['step'] == step]
    if not fields:
        return "Aucune signature à ce pas", 404
    return render_template('sign.html',
                           pdf=session_data['pdf'],
                           session_id=session_id,
                           step=step,
                           fields=fields,
                           email=fields[0]['email'])

@app.route('/fill-field', methods=['POST'])
def fill_field():
    data = request.get_json()
    scale = data.get('scale', 1.5)
    session_path = os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")
    with open(session_path) as f:
        session_data = json.load(f)

    field = session_data['fields'][data['field_index']]
    field['value'] = data['value']
    field['signed'] = True

    pdf_input_path = os.path.join(UPLOAD_FOLDER, session_data['pdf'])
    new_pdf_path = pdf_input_path

    if field['type'] == 'signature':
        apply_signature(pdf_input_path,
                        field['value'],
                        new_pdf_path,
                        field['x'],
                        field['y'],
                        scale=scale)
    else:
        apply_text(pdf_input_path,
                   field['x'],
                   field['y'],
                   data['value'],
                   scale)

    with open(session_path, 'w') as f:
        json.dump(session_data, f)

    remaining = [f for f in session_data['fields'] if not f.get('signed')]
    if remaining:
        next_step = min(f['step'] for f in remaining)
        send_email(data['session_id'], next_step)
        return jsonify({'status': 'next'})
    else:
        send_pdf_to_all(session_data)
        return jsonify({'status': 'completed'})

@app.route('/session/<session_id>/status')
def status(session_id):
    path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    with open(path) as f:
        session_data = json.load(f)
    done = all(f['signed'] for f in session_data['fields'])
    return f"<h2>Signature terminée : {'✅ OUI' if done else '❌ NON'}" 


def apply_text(pdf_path, x, y, text, scale=1.5):
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)
    x_pdf = x / scale
    y_pdf = letter[1] - y / scale
    can.setFont("Helvetica", 12)
    can.drawString(x_pdf, y_pdf, text)
    can.save()
    packet.seek(0)
    overlay = PdfReader(packet)
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i == 0:
            page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with open(pdf_path, 'wb') as f:
        writer.write(f)


def apply_signature(pdf_path, sig_data, output_path, x, y, scale=1.5):
    # Décodage de l'image
    if sig_data.startswith("data:image/png;base64,"):
        sig_data = sig_data.split(",")[1]
    image_bytes = base64.b64decode(sig_data)
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    width, height = image.size

    x_pdf = x / scale
    y_pdf = letter[1] - y / scale - (height / scale)

    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)
    img_io = io.BytesIO()
    image.save(img_io, format="PNG")
    img_io.seek(0)
    can.drawImage(ImageReader(img_io),
                  x_pdf,
                  y_pdf,
                  width=width/scale,
                  height=height/scale,
                  mask='auto')
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


def send_email(session_id, step):
    session_file = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    with open(session_file) as f:
        data = json.load(f)
        email_message = data.get('email_message', '').strip()
    recipient = next((fd['email'] for fd in data['fields'] if fd['step'] == step), None)
    if not recipient:
        return
    app_url = os.getenv('APP_URL', 'http://localhost:5000')
    msg = EmailMessage()
    msg['Subject'] = 'Signature requise'
    msg['From'] = os.getenv('SMTP_USER')
    msg['To'] = recipient
    msg.set_content(
        "Bonjour,\n\n"
        f"{email_message}\n\n"
        f"Pour signer, cliquez ici : {app_url}/sign/{session_id}/{step}" Franco )


def send_pdf_to_all(session_data):
    email_message = session_data.get('email_message', '').strip()
    pdf_path = os.path.join(UPLOAD_FOLDER, session_data['pdf'])

    if not os.path.isfile(pdf_path):
        return

    with open(pdf_path, 'rb') as f:
        content = f.read()

    sent = set()
    for f in session_data['fields']:
        recipient = f['email']
        if recipient and recipient not in sent:
            sent.add(recipient)
            msg = EmailMessage()
            msg['Subject'] = 'Document signé final'
            msg['From'] = os.getenv('SMTP_USER')
            msg['To'] = recipient
            msg.set_content(
            "Bonjour,\n\n"
            f"{email_message}\n\n"
            "Le document final signé est en pièce jointe."
        )
            msg.add_attachment(content, maintype='application', subtype='pdf', filename='document_final.pdf')
            try:
                with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
                    server.starttls()
                    server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
                    server.send_message(msg)
            except Exception as e:
                with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
                    log.write(f"[ERROR] PDF à {recipient} : {e}\n")


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
