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
    return width, height

def merge_overlay(pdf_path, overlay_pdf, output_path=None, page_num=0):
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    overlay_reader = PdfReader(overlay_pdf)
    for i, page in enumerate(reader.pages):
        if i == page_num:
            page.merge_page(overlay_reader.pages[0])
        writer.add_page(page)
    with open(output_path or pdf_path, 'wb') as f:
        writer.write(f)

# ----------- Placement ABSOLU pour tous les apply fonctions -----------

def apply_text(pdf_path, x, y, text, page_num=0, offset_x=0, offset_y=0, font_size=14):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))
    can.setFont("Helvetica", font_size)
    can.setFillColorRGB(0, 0, 0)
    can.drawString(x + offset_x, y + offset_y, text)
    can.save()
    packet.seek(0)
    merge_overlay(pdf_path, packet, output_path=pdf_path, page_num=page_num)

def apply_signature(pdf_path, sig_data, output_path, x, y, w, h, page_num=0, offset_x=0, offset_y=0):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    if sig_data.startswith("data:image/png;base64,"):
        sig_data = sig_data.split(",", 1)[1]
    image_bytes = base64.b64decode(sig_data)
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))
    img_io = io.BytesIO()
    image.save(img_io, format="PNG")
    img_io.seek(0)
    can.drawImage(ImageReader(img_io), x + offset_x, y + offset_y, width=w, height=h, mask='auto')
    can.save()
    packet.seek(0)
    merge_overlay(pdf_path, packet, output_path=output_path, page_num=page_num)

def apply_checkbox(pdf_path, x, y, checked, size=14, page_num=0, offset_x=0, offset_y=0):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))
    can.rect(x + offset_x, y + offset_y, size, size)
    if checked:
        can.setLineWidth(2)
        can.line(x + offset_x, y + offset_y, x + offset_x + size, y + offset_y + size)
        can.line(x + offset_x, y + offset_y + size, x + offset_x + size, y + offset_y)
    can.save()
    packet.seek(0)
    merge_overlay(pdf_path, packet, output_path=pdf_path, page_num=page_num)

def apply_static_text_fields(pdf_path, fields, output_path=None, page_num=0, offset_x=0, offset_y=0):
    static_fields = [f for f in fields if f.get("type") == "statictext"]
    if not static_fields:
        return
    reader = PdfReader(pdf_path)
    pdf_w, pdf_h = get_pdf_page_size(pdf_path, page_num)
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_w, pdf_h))
    for field in static_fields:
        x_field  = float(field.get("x", 0))
        y_field  = float(field.get("y", 0))
        value    = field.get("value", "")
        font_size= float(field.get("font_size", 14))
        can.setFont("Helvetica", font_size)
        can.drawString(x_field + offset_x, y_field + offset_y, value)
    can.save()
    packet.seek(0)
    overlay_pdf = PdfReader(packet)
    writer = PdfWriter()
    for i, p in enumerate(reader.pages):
        if i == page_num:
            p.merge_page(overlay_pdf.pages[0])
        writer.add_page(p)
    with open(output_path or pdf_path, "wb") as f:
        writer.write(f)

# ------------- Reste du code identique, mais /fill-field doit passer x/y/w/h -----------

@app.route('/')
def index():
    sessions = {}
    for filename in os.listdir(SESSION_FOLDER):
        if filename.endswith(".json"):
            sid = filename.replace(".json", "")
            try:
                with open(os.path.join(SESSION_FOLDER, filename)) as f:
                    data = json.load(f)
                sessions[sid] = {
                    "pdf": data.get("pdf", ""),
                    "name": data.get("nom_demande", ""),
                    "fields": data.get("fields", []),
                    "done": all(f.get("signed") for f in data.get("fields", []) if f.get("type") != "statictext")
                }
            except Exception as e:
                print(f"[ERROR] Session {filename} illisible: {e}")
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
    return jsonify({'status': 'saved', 'pdf': data['pdf'], 'fields': data['fields']})

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
    if 'pdf' not in data or not data['pdf']:
        return jsonify({'error': "Aucun fichier PDF spécifié."}), 400
    message = request.form.get('email_message', '')
    nom_demande = request.form.get('nom_demande', '')
    session_id = str(uuid.uuid4())
    fields = data['fields']
    signataires = {}
    for f in fields:
        if f.get("type") != "statictext" and "signer_id" in f and "email" in f:
            signataires[f["signer_id"]] = f["email"]
    for field in fields:
        if field.get("type") != "statictext" and "signer_id" in field and "email" not in field:
            sid = field["signer_id"]
            if sid in signataires:
                field["email"] = signataires[sid]
    # Supposé: les champs sont déjà en px PDF natifs (x, y, w, h), pas de conversion ici
    for i, field in enumerate(fields):
        field['signed'] = False
        field['step'] = i
        field['page'] = field.get('page', 0)
        # S'assurer que w/h sont toujours présents
        if 'h' not in field:
            if field['type'] == 'signature':
                field['h'] = 40
            elif field['type'] == 'checkbox':
                field['h'] = 15
            else:
                field['h'] = 40
        if 'w' not in field:
            if field['type'] == 'signature':
                field['w'] = 120
            elif field['type'] == 'checkbox':
                field['w'] = 15
            else:
                field['w'] = 120
    pdf_path = os.path.join(UPLOAD_FOLDER, data['pdf'])
    apply_static_text_fields(pdf_path, fields, output_path=None)
    session_data = {
        'pdf': data['pdf'],
        'fields': fields,
        'email_message': message,
        'nom_demande': nom_demande,
        'message_final': ''  # initialisation
    }
    session_file_path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    with open(session_file_path, 'w') as f:
        json.dump(session_data, f)
    signable_fields = [f for f in fields if f.get('type') not in ('statictext',)]
    if signable_fields:
        send_email(session_id, step=0, message_final=None)
        return render_template("notified.html", session_id=session_id)
    else:
        return render_template(
            "index.html",
            templates=[f.replace('.json', '') for f in os.listdir(TEMPLATES_FOLDER) if f.endswith('.json')],
            sessions={}
        )

@app.route('/sign/<session_id>/<int:step>')
def sign(session_id, step):
    session_path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    if not os.path.exists(session_path):
        return "Session introuvable", 404
    with open(session_path) as f:
        session_data = json.load(f)
    signers = []
    for f in session_data['fields']:
        if f.get('type') != 'statictext' and 'signer_id' in f and 'email' in f:
            s = {'id': f['signer_id'], 'email': f['email']}
            if s not in signers:
                signers.append(s)
    fields = [f for f in session_data['fields'] if f.get('step', 0) == step]
    currentSignerId = fields[0]['signer_id'] if fields and 'signer_id' in fields[0] else None
    return render_template(
        'sign.html',
        pdf=session_data['pdf'],
        session_id=session_id,
        step=step,
        fields_json=fields,
        fields_all=session_data['fields'],
        signers=signers,
        signer_id=currentSignerId,
        previous_message=session_data.get("message_final", "")
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
    # Récupération placement absolu
    x = float(field.get('x', 0))
    y = float(field.get('y', 0))
    w = float(field.get('w', 120))
    h = float(field.get('h', 40))
    offset_x = float(field.get('offset_x', 0))
    offset_y = float(field.get('offset_y', 0))
    if field['type'] == 'signature':
        new_pdf_name = f"signed_{uuid.uuid4()}.pdf"
        new_pdf_path = os.path.join(UPLOAD_FOLDER, new_pdf_name)
        apply_signature(pdf_path, field['value'], new_pdf_path, x, y, w, h, page_num, offset_x, offset_y)
        session_data['pdf'] = new_pdf_name
    elif field['type'] == 'checkbox':
        apply_checkbox(pdf_path, x, y, data['value'] in ['true','on','1', True], size=max(w, h), page_num=page_num, offset_x=offset_x, offset_y=offset_y)
    else:
        apply_text(pdf_path, x, y, data['value'], page_num=page_num, offset_x=offset_x, offset_y=offset_y)
    with open(session_path, 'w') as f:
        json.dump(session_data, f)
    return jsonify({'status': 'ok'})

@app.route('/finalise-signature', methods=['POST'])
def finalise_signature():
    data = request.get_json()
    session_path = os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")
    with open(session_path) as f:
        session_data = json.load(f)
    if data.get('message_final') is not None:
        session_data['message_final'] = data['message_final']
    all_fields = session_data['fields']
    current_step = max(f['step'] for f in all_fields if f['signed']) if any(f['signed'] for f in all_fields) else 0
    remaining_same = [f for f in all_fields if f['step']==current_step and not f['signed'] and f["type"] != "statictext"]
    if remaining_same:
        with open(session_path, 'w') as f:
            json.dump(session_data, f)
        return jsonify({'status': 'incomplete'})
    remaining = [f for f in all_fields if not f['signed'] and f["type"] != "statictext"]
    if remaining:
        next_step = min(f['step'] for f in remaining)
        send_email(data['session_id'], next_step, message_final=session_data.get('message_final'))
        session_data['message_final'] = ""
    else:
        send_pdf_to_all(session_data)
    with open(session_path, 'w') as f:
        json.dump(session_data, f)
    return jsonify({'status': 'finalised'})

def send_email(session_id, step, message_final=None):
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
    recipient = next((fld.get('email') for fld in data['fields'] if fld.get('step', 0) == step and fld["type"] != "statictext" and fld.get('email')), None)
    if not recipient:
        print(f"Aucun destinataire trouvé pour l'étape {step}")
        return
    app_url = os.getenv('APP_URL', 'http://localhost:5000')
    link = f"{app_url}/sign/{session_id}/{step}"
    msg = EmailMessage()
    msg['Subject'] = 'Signature requise'
    msg['From'] = os.getenv('SMTP_USER')
    msg['To'] = recipient
    body = data.get('email_message') or f"Bonjour, veuillez signer ici : {link}"
    if message_final is None:
        message_final = data.get('message_final', '')
    if message_final:
        body += f"\n\nMessage du signataire précédent :\n{message_final}"
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
        print(f"[MAIL] Envoyé à {recipient} pour l'étape {step}")
    except Exception as e:
        with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
            log.write(f"[ERROR] send_email to {recipient} at step {step}: {e}\n")
        print(f"[MAIL][ERROR] {e}")

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
            print(f"[MAIL] PDF final envoyé à {recipient}")
        except Exception as e:
            with open(os.path.join(LOG_FOLDER, 'audit.log'), 'a') as log:
                log.write(f"[ERROR] send_pdf_to_all to {recipient}: {e}\n")
            print(f"[MAIL][ERROR] {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
