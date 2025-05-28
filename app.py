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
    for i, field in enumerate(fields):
        field['signed'] = False
        field['value'] = ''
        field['step'] = i
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

    # Update field
    field = session_data['fields'][data['field_index']]
    field['value'] = data['value']
    field['signed'] = True
    pdf_path = os.path.join(UPLOAD_FOLDER, session_data['pdf'])

    # Coordinates and scales from client
    x_px = data['x_px']
    y_px = data['y_px']
    html_h = data['html_height_px']
    scale_x = data['scale_x']
    scale_y = data['scale_y']

    # Dispatch by type
    if field['type'] == 'signature':
        new_pdf = f"signed_{uuid.uuid4()}.pdf"
        new_path = os.path.join(UPLOAD_FOLDER, new_pdf)
        apply_signature(pdf_path, data['value'], new_path,
                        x_px, y_px, html_h, scale_x, scale_y)
        session_data['pdf'] = new_pdf
    elif field['type'] == 'checkbox':
        apply_checkbox(pdf_path,
                       x_px, y_px,
                       data['value'] in ['true','on','1'],
                       html_h, scale_x, scale_y)
    else:
        apply_text(pdf_path,
                   x_px, y_px,
                   data['value'],
                   html_h, scale_x, scale_y)

    # Save session
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
    remaining_fields_same_step = [f for f in all_fields if f['step'] == current_step and not f['signed']]

    if remaining_fields_same_step:
        return jsonify({'status': 'incomplete'})
    else:
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
        session_data = json.load(f)
    done = all(f['signed'] for f in session_data['fields'])
    return f"<h2>Signature terminée : {'✅ OUI' if done else '❌ NON'}</h2>"

# --- Rendering functions ---

def apply_text(pdf_path, x_px, y_px, text, html_h, scale_x, scale_y):
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)

    # Linear conversion
    x_pdf = x_px * scale_x
    y_pdf = (html_h - y_px) * scale_y

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


def apply_signature(pdf_path, sig_data, output_path, x_px, y_px, html_h, scale_x, scale_y):
    width, height = 100, 40

    x_pdf = x_px * scale_x - width/2
    y_pdf = (html_h - y_px) * scale_y - height/2

    if sig_data.startswith("data:image/png;base64,"):
        sig_data = sig_data.split(",", 1)[1]
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


def apply_checkbox(pdf_path, x_px, y_px, checked, html_h, scale_x, scale_y, size=15):
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)

    x_pdf = x_px * scale_x - size/2
    y_pdf = (html_h - y_px) * scale_y - size/2

    can.rect(x_pdf, y_pdf, size, size)
    if checked:
        can.setLineWidth(2)
        can.line(x_pdf, y_pdf, x_pdf+size, y_pdf+size)
        can.line(x_pdf, y_px+size, x_px+size, y_pdf)
    can.save()

    packet.seek(0)
    overlay = PdfReader(packet)
    for i, page in enumerate(reader.pages):
        if i == 0:
            page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with open(pdf_path, 'wb') as f:
        writer.write(f)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
