from flask import Flask, request, render_template, send_from_directory, jsonify
import os
import uuid
import json
import smtplib
import base64
from email.message import EmailMessage
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.colors import black
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
    x_pdf = x_html * pdf_w / html_w
    y_pdf = y_html * pdf_h / html_h
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

def apply_text(pdf_path, x_px, y_px, text, html_width_px, html_height_px, field_height=40, page_num=0, offset_x=0, offset_y=2):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    font_size = 14
    x_pdf, y_pdf = html_to_pdf_coords(x_px, y_px, field_height, html_width_px, html_height_px, pdf_width, pdf_height)
    x_pdf += offset_x
    y_pdf += offset_y + (field_height - font_size)
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))
    can.setFont("Helvetica", font_size)
    can.setFillColorRGB(0, 0, 0)
    can.drawString(x_pdf, y_pdf, text)
    can.save()
    packet.seek(0)
    merge_overlay(pdf_path, packet, output_path=pdf_path, page_num=page_num)

def apply_signature(pdf_path, sig_data, output_path, x_px, y_px, html_width_px, html_height_px, field_height=40, page_num=0, offset_x=0, offset_y=15):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    width, height = 100, field_height
    x_pdf, y_pdf = html_to_pdf_coords(x_px, y_px, height, html_width_px, html_height_px, pdf_width, pdf_height)
    x_pdf += offset_x
    y_pdf += offset_y
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

def apply_checkbox(pdf_path, x_px, y_px, checked, html_width_px, html_height_px, field_height=15, page_num=0, size=10, offset_x=0, offset_y=0):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    x_pdf, y_pdf = html_to_pdf_coords(x_px, y_px, size, html_width_px, html_height_px, pdf_width, pdf_height)
    x_pdf += offset_x
    y_pdf += offset_y
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))
    can.rect(x_pdf, y_pdf, size, size)
    if checked:
        can.setLineWidth(2)
        can.line(x_pdf, y_pdf, x_pdf + size, y_pdf + size)
        can.line(x_pdf, y_pdf + size, x_pdf + size, y_pdf)
    can.save()
    packet.seek(0)
    merge_overlay(pdf_path, packet, output_path=pdf_path, page_num=page_num)

def apply_static_text_fields(pdf_path, fields, output_path=None, page_num=0, offset_x=3, offset_y=23):
    static_fields = [f for f in fields if f.get("type") == "statictext"]
    if not static_fields:
        return
    reader = PdfReader(pdf_path)
    pdf_w, pdf_h = 596.6, 846.6
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_w, pdf_h))
    for field in static_fields:
        x_field = float(field.get("x", 0))
        y_field = float(field.get("y", 0))
        h_field = float(field.get("h", 0))
        value = field.get("value", "")
        font_size = float(field.get("font_size", 14))
        x_pdf = x_field + offset_x
        y_pdf = pdf_h - (y_field + h_field) + offset_y
        can.setFont("Helvetica", font_size)
        can.drawString(x_pdf, y_pdf, value)
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

@app.route('/define-fields', methods=['POST'])
def define_fields():
    data = json.loads(request.form['fields_json'])
    message = request.form.get('email_message', '')
    nom_demande = request.form.get('nom_demande', '')
    session_id = str(uuid.uuid4())
    fields = data.get('fields', [])
    for i, field in enumerate(fields):
        field['signed'] = False
        field['step'] = i
        field['page'] = field.get('page', 0)
        if 'h' not in field:
            if field.get('type') == 'signature':
                field['h'] = 40
            elif field.get('type') == 'checkbox':
                field['h'] = 15
            else:
                field['h'] = 40
    if not data.get('pdf'):
        print("[ERROR] Aucune clé 'pdf' dans les données reçues.")
        return render_template(
            "index.html",
            templates=[f.replace('.json', '') for f in os.listdir(TEMPLATES_FOLDER) if f.endswith('.json')],
            sessions={},
            error='Aucun fichier PDF spécifié.'
        )
    pdf_path = os.path.join(UPLOAD_FOLDER, data['pdf'])
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
    signable_fields = [f for f in fields if f.get('type') not in ('statictext',)]
    if signable_fields:
        send_email(session_id, step=0)
        return render_template("notified.html", session_id=session_id)
    else:
        return render_template(
            "index.html",
            templates=[f.replace('.json', '') for f in os.listdir(TEMPLATES_FOLDER) if f.endswith('.json')],
            sessions={}
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
    pdf_name = session_data.get('pdf')
    if not pdf_name:
        return jsonify({'error': "Clé 'pdf' absente dans la session."}), 400
    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name)
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
        apply_checkbox(pdf_path, x_px, y_px, data['value'] in ['true', 'on', '1', True], html_width_px, html_height_px, field_height=field_height, page_num=page_num)
    else:
        apply_text(pdf_path, x_px, y_px, data['value'], html_width_px, html_height_px, field_height=field_height, page_num=page_num)

    with open(session_path, 'w') as f:
        json.dump(session_data, f)
    return jsonify({'status': 'ok'})

@app.route('/finalise', methods=['POST'])
def finalise():
    data = request.get_json()
    session_path = os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")
    with open(session_path) as f:
        session_data = json.load(f)
    send_pdf_to_all(session_data)
    with open(session_path, 'w') as f:
        json.dump(session_data, f)
    return jsonify({'status': 'finalised'})

@app.route('/save-template', methods=['POST'])
def save_template():
    data = request.get_json()
    name = data.get('name')
    pdf = data.get('pdf')
    fields = data.get('fields', [])
    if not name or not pdf:
        return jsonify({'error': 'Nom ou PDF manquant.'}), 400
    template_data = {
        'pdf': pdf,
        'fields': fields
    }
    template_path = os.path.join(TEMPLATES_FOLDER, f"{name}.json")
    with open(template_path, 'w') as f:
        json.dump(template_data, f)
    return jsonify({'pdf': pdf, 'fields': fields})

@app.route('/load-template/<name>', methods=['GET'])
def load_template(name):
    template_path = os.path.join(TEMPLATES_FOLDER, f"{name}.json")
    if not os.path.exists(template_path):
        return jsonify({'error': 'Template non trouvé.'}), 404
    with open(template_path) as f:
        template_data = json.load(f)
    return jsonify(template_data)

def send_email(session_id, step=0):
    session_file = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    if not os.path.isfile(session_file) or os.path.getsize(session_file) == 0:
        print("Le fichier de session est vide ou absent.")
        return
    with open(session_file) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("Erreur : fichier JSON vide ou corrompu")
            return
    recipient = next((fld.get('email') for fld in data.get('fields', []) if fld.get('step', 0) == step and fld.get("type") != "statictext"), None)
    if not recipient:
        print("Aucun destinataire trouvé pour l'étape", step)
        return
    app_url = os.getenv('APP_URL', 'http://localhost:5000')
    link = f"{app_url}/sign/{session_id}/{step}"
    msg = EmailMessage()
    msg['Subject'] = 'Signature requise'
    msg['From'] = os.getenv('SMTP_USER')
    msg['To'] = recipient
    body = data.get('email_message', '') or ''
    body += f"\n\nVeuillez cliquer sur le lien suivant pour signer le document : {link}"
    msg.set_content(body)
    try:
        smtp_server = os.getenv('SMTP_SERVER')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_user = os.getenv('SMTP_USER')
        smtp_pass = os.getenv('SMTP_PASS')
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print(f"Email envoyé à {recipient}")
    except Exception as e:
        print(f"Erreur lors de l'envoi de l'email : {e}")

def send_pdf_to_all(session_data):
    pdf_name = session_data.get('pdf')
    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name) if pdf_name else None
    if not pdf_path or not os.path.isfile(pdf_path):
        print("Le PDF final n'existe pas.")
        return
    with open(pdf_path, 'rb') as f:
        content = f.read()
    sent = set()
    message_final = session_data.get('message_final', '')
    for fld in session_data.get('fields', []):
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
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            server.quit()
            print(f"Email final envoyé à {recipient}")
        except Exception as e:
            print(f"Erreur lors de l'envoi de l'email final : {e}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
