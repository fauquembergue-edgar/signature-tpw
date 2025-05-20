
from flask import Flask, request, render_template, send_from_directory, redirect, jsonify
import os
import uuid
import json
import smtplib
from email.message import EmailMessage
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from dotenv import load_dotenv
import io

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

app = Flask(__name__)

# Dossiers de travail
UPLOAD_FOLDER = 'uploads'
SESSION_FOLDER = 'sessions'
LOG_FOLDER = 'logs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SESSION_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

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

@app.route('/define-fields', methods=['POST'])
def define_fields():
    data = json.loads(request.form['fields_json'])
    session_id = str(uuid.uuid4())
    pdf_file = data['pdf']
    fields = data['fields']

    for field in fields:
        field['signed'] = False
        field['value'] = ''

    session_data = {
        'pdf': pdf_file,
        'fields': fields,
        'current': 0
    }

    with open(os.path.join(SESSION_FOLDER, f'{session_id}.json'), 'w') as f:
        json.dump(session_data, f)

    send_email(session_id, 0)
    return f"Processus lance. Le premier signataire a ete notifie."

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
            sig = request.files[f'signature_{step}']
            sig_path = os.path.join(UPLOAD_FOLDER, f'{session_id}_sig_{step}.png')
            sig.save(sig_path)
            new_pdf_path = os.path.join(UPLOAD_FOLDER, f"signed_{uuid.uuid4()}.pdf")
            apply_signature(pdf_path, sig_path, new_pdf_path, field['x'], field['y'])
            session_data['pdf'] = os.path.basename(new_pdf_path)

        field['signed'] = True
        session_data['current'] += 1

        with open(session_path, 'w') as f:
            json.dump(session_data, f)

        with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
            log.write(f"{field['email']} a complete le champ {step} dans la session {session_id}\n")

        if session_data['current'] < len(session_data['fields']):
            send_email(session_id, session_data['current'])
            return "Champ enregistre. Prochaine personne notifiee."
        else:
            return f"Toutes les entrees sont completes. <a href='/download/{session_data['pdf']}'>Telecharger le PDF</a>"

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
    can = canvas.Canvas(packet, pagesize=letter)
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
    can = canvas.Canvas(packet, pagesize=letter)
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
    msg = EmailMessage()
    msg['Subject'] = 'Champ a remplir dans un document'
    msg['From'] = os.getenv('SMTP_USER')
    msg['To'] = recipient
    msg.set_content(f"Bonjour, veuillez completer ce champ : https://votre-url-deploiement.onrender.com/sign/{session_id}/{step}")
    try:
        with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
            server.starttls()
            server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
            server.send_message(msg)
    except Exception as e:
        with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
            log.write(f"[ERROR] Email vers {recipient} echoue: {e}\n")

# Important pour que Render detecte le port a utiliser
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
