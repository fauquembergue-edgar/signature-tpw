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
from PIL import Image, ImageDraw

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
    pdf_file = data['pdf']
    fields = data['fields']

    scale = 1.5
    for field in fields:
        field['signed'] = False
        field['value'] = ''
        field['x'] = round(field['x'] / scale, 2)
        field['y'] = round(field['y'] / scale, 2)

    session_data = {
        'pdf': pdf_file,
        'fields': fields,
        'email_message': message,
        'nom_demande': nom_demande
    }
    with open(os.path.join(SESSION_FOLDER, f'{session_id}.json'), 'w') as f:
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

    if field['type'] == 'signature':
        if data['value'].startswith('data:image/png;base64,'):
            field['mode'] = 'draw'
        elif data['value'].startswith('data:image'):
            field['mode'] = 'image'
        else:
            field['mode'] = 'text'
    else:
        field['mode'] = 'text'

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
    session_id = data['session_id']
    signed_steps = set(f['step'] for f in all_fields if f['signed'])
    remaining = [f for f in all_fields if not f['signed']]

    if remaining:
        next_step = min(f['step'] for f in remaining)
        if next_step not in signed_steps:
            send_email(session_id, next_step)
    else:
        send_pdf_to_all(session_data)

    with open(session_path, 'w') as f:
        json.dump(session_data, f)

    return jsonify({'status': 'finalised'})


@app.route('/session/<session_id>/status')
def status(session_id):
    path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    with open(path) as f:
        session_data = json.load(f)
    done = all(f['signed'] for f in session_data['fields'])
    return f"<h2>Signature terminée : {'✅ OUI' if done else '❌ NON'}</h2>"

def send_email(session_id, step):
    with open(os.path.join(SESSION_FOLDER, f"{session_id}.json")) as f:
        data = json.load(f)
    recipient = next((f['email'] for f in data['fields'] if f.get('step', 0) == step), None)
    if not recipient:
        return
    app_url = os.getenv('APP_URL', 'http://localhost:5000')
    msg = EmailMessage()
    msg['Subject'] = 'Signature requise'
    msg['From'] = os.getenv('SMTP_USER')
    msg['To'] = recipient
    msg.set_content(f"Bonjour,\n\nVeuillez signer ce document : {app_url}/sign/{session_id}/{step}")
    try:
        with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
            server.starttls()
            server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
            server.send_message(msg)
    except Exception as e:
        with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
            log.write(f"[ERROR] email vers {recipient} : {e}\n")

def send_pdf_to_all(session_data):
    pdf_path = os.path.join(UPLOAD_FOLDER, session_data['pdf'])
    temp_output = os.path.join(UPLOAD_FOLDER, f"final_{uuid.uuid4()}.pdf")

    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)

    for field in session_data['fields']:
        x = field['x']
        y = field['y']
        value = field.get('value', '')

        if field['type'] == 'text':
            can.setFont("Helvetica", 12)
            can.drawString(x, y, value)

        elif field['type'] == 'signature':
            if field.get('mode') == 'draw' or field.get('mode') == 'image':
                sig_data = base64.b64decode(value.split(',')[1])
                sig_path = os.path.join(UPLOAD_FOLDER, f"sig_{uuid.uuid4()}.png")
                with open(sig_path, 'wb') as f:
                    f.write(sig_data)
                can.drawImage(sig_path, x, y, width=100, height=50)
                os.remove(sig_path)
            else:
                can.setFont("Helvetica-Bold", 12)
                can.drawString(x, y, value)

    can.save()
    packet.seek(0)
    overlay = PdfReader(packet)

    for i, page in enumerate(reader.pages):
        if i == 0:
            page.merge_page(overlay.pages[0])
        writer.add_page(page)

    with open(temp_output, 'wb') as f:
        writer.write(f)

    with open(temp_output, 'rb') as f:
        content = f.read()

    recipients = set(f['email'] for f in session_data['fields'] if f['email'])
    for recipient in recipients:
        msg = EmailMessage()
        msg['Subject'] = 'Document signé final'
        msg['From'] = os.getenv('SMTP_USER')
        msg['To'] = recipient
        msg.set_content('Voici le PDF final signé.')
        msg.add_attachment(content, maintype='application', subtype='pdf', filename=os.path.basename(temp_output))
        try:
            with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
                server.starttls()
                server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
                server.send_message(msg)
        except Exception as e:
            with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
                log.write(f"[ERROR] PDF à {recipient} : {e}\n")

    os.remove(temp_output)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
