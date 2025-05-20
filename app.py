
from flask import Flask, request, render_template, send_from_directory, jsonify
import os
import uuid
import json
import smtplib
import base64
from email.message import EmailMessage
from email.mime.base import MIMEBase
from email import encoders
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.pagesizes import letter
from dotenv import load_dotenv
import io
from PIL import Image, ImageDraw, ImageFont

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

@app.route('/')
def index():
    templates = [f.replace('.json', '') for f in os.listdir(TEMPLATES_FOLDER) if f.endswith('.json')]
    return render_template('index.html', templates=templates)

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
    name = data['name']
    template_data = {
        'pdf': data['pdf'],
        'fields': data['fields']
    }
    with open(os.path.join(TEMPLATES_FOLDER, f"{name}.json"), 'w') as f:
        json.dump(template_data, f)
    return jsonify({'status': 'saved'})

@app.route('/load-template/<name>')
def load_template(name):
    with open(os.path.join(TEMPLATES_FOLDER, f"{name}.json")) as f:
        return jsonify(json.load(f))

@app.route('/define-fields', methods=['POST'])
def define_fields():
    data = json.loads(request.form['fields_json'])
    message = request.form.get('email_message', '')
    session_id = str(uuid.uuid4())
    pdf_file = data['pdf']
    fields = data['fields']

    for field in fields:
        field['signed'] = False
        field['value'] = ''

    session_data = {
        'pdf': pdf_file,
        'fields': fields,
        'current': 0,
        'email_message': message
    }

    with open(os.path.join(SESSION_FOLDER, f'{session_id}.json'), 'w') as f:
        json.dump(session_data, f)

    send_email(session_id, 0)
    return f"Processus lancé. Le premier signataire a été notifié."

@app.route('/sign/<session_id>/<int:step>', methods=['GET', 'POST'])
def sign(session_id, step):
    session_path = os.path.join(SESSION_FOLDER, f'{session_id}.json')
    with open(session_path) as f:
        session_data = json.load(f)

    field = session_data['fields'][step]
    pdf_filename = session_data['pdf']
    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)

    if request.method == 'POST':
        if field['type'] == 'text':
            value = request.form.get(f'text_{step}', '')
            field['value'] = value
            apply_text(pdf_path, field['x'], field['y'], value)
        elif field['type'] == 'signature':
            sig_mode = request.form.get('sig_mode')
            sig_path = os.path.join(UPLOAD_FOLDER, f'{session_id}_sig_{step}.png')
            if sig_mode == 'draw':
                sig_data = request.form['signature_drawn'].split(',')[1]
                with open(sig_path, 'wb') as f:
                    f.write(base64.b64decode(sig_data))
            elif sig_mode == 'text':
                img = Image.new('RGBA', (400, 100), (255, 255, 255, 0))
                draw = ImageDraw.Draw(img)
                draw.text((10, 30), request.form['signature_text'], fill='black')
                img.save(sig_path)

            new_pdf_path = os.path.join(UPLOAD_FOLDER, f"signed_{uuid.uuid4()}.pdf")
            apply_signature(pdf_path, sig_path, new_pdf_path, field['x'], field['y'])
            session_data['pdf'] = os.path.basename(new_pdf_path)

        field['signed'] = True
        session_data['current'] += 1

        with open(session_path, 'w') as f:
            json.dump(session_data, f)

        if session_data['current'] < len(session_data['fields']):
            send_email(session_id, session_data['current'])
            return "Champ enregistré. Prochaine personne notifiée."
        else:
            send_pdf_to_all(session_data)
            return f"Toutes les entrées sont complétées. <a href='/download/{session_data['pdf']}'>Télécharger le PDF</a>"

    return render_template('sign.html', email=field['email'], fields=[field], pdf=pdf_filename)

@app.route('/session/<session_id>/status')
def status(session_id):
    session_path = os.path.join(SESSION_FOLDER, f'{session_id}.json')
    with open(session_path) as f:
        session_data = json.load(f)
    return render_template('status.html', fields=session_data['fields'])

@app.route('/download/<path:filename>')
def download(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

def apply_signature(pdf_path, sig_path, output_path, x, y):
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)
    can.drawImage(sig_path, x, y, width=100, height=50)
    can.save()
    packet.seek(0)
    sig_pdf = PdfReader(packet)
    for i, page in enumerate(reader.pages):
        if i == 0:
            page.merge_page(sig_pdf.pages[0])
        writer.add_page(page)
    with open(output_path, 'wb') as f:
        writer.write(f)

def apply_text(pdf_path, x, y, text):
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)
    can.setFont("Helvetica", 12)
    can.drawString(x, y, text)
    can.save()
    packet.seek(0)
    overlay = PdfReader(packet)
    for i, page in enumerate(reader.pages):
        if i == 0:
            page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with open(pdf_path, 'wb') as f:
        writer.write(f)

def send_email(session_id, step):
    with open(os.path.join(SESSION_FOLDER, f'{session_id}.json')) as f:
        data = json.load(f)
    recipient = data['fields'][step]['email']
    custom_message = data.get('email_message', '')
    app_url = os.getenv('APP_URL', 'http://localhost:5000')

    msg = EmailMessage()
    msg['Subject'] = 'Champ à remplir - Signature PDF'
    msg['From'] = os.getenv('SMTP_USER')
    msg['To'] = recipient
    msg.set_content(f"{custom_message}\n\nLien de signature : {app_url}/sign/{session_id}/{step}")
    try:
        with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
            server.starttls()
            server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
            server.send_message(msg)
    except Exception as e:
        with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
            log.write(f"[ERROR] Email vers {recipient} echoue: {e}\n")

def send_pdf_to_all(session_data):
    with open(os.path.join(UPLOAD_FOLDER, session_data['pdf']), 'rb') as f:
        file_data = f.read()
    for f in session_data['fields']:
        recipient = f['email']
        if recipient:
            msg = EmailMessage()
            msg['Subject'] = 'Document signé complet'
            msg['From'] = os.getenv('SMTP_USER')
            msg['To'] = recipient
            msg.set_content('Voici le PDF signé.')
            msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=session_data['pdf'])
            try:
                with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
                    server.starttls()
                    server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
                    server.send_message(msg)
            except Exception as e:
                with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
                    log.write(f"[ERROR] Envoi final PDF vers {recipient} echoue: {e}\n")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
