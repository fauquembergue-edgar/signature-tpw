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
from reportlab.lib.utils import ImageReader


load_dotenv()
from PyPDF2 import PdfReader, PdfWriter
import io
from PIL import Image

# Configuration du logger
import logging
LOG_FOLDER = os.getenv('LOG_FOLDER', 'logs')
os.makedirs(LOG_FOLDER, exist_ok=True)
handler = logging.FileHandler(os.path.join(LOG_FOLDER, 'app.log'))
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(handler)


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

    if field['type'] == 'signature':
        pdf_input_path = os.path.join(UPLOAD_FOLDER, session_data['pdf'])
        new_pdf_name = f"signed_{uuid.uuid4()}.pdf"
        new_pdf_path = os.path.join(UPLOAD_FOLDER, new_pdf_name)
        apply_signature(pdf_input_path, field['value'], new_pdf_path, field['x'], field['y'], scale=1.5)
        session_data['pdf'] = new_pdf_name
    else:
        apply_text(pdf_path, field['x'], field['y'], data['value'], scale=1.5)

    # 🔥 AJOUT ESSENTIEL : on enregistre les changements dans session_data
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
        # Ne pas envoyer l'email suivant car le signataire courant n’a pas fini
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

def apply_text(pdf_path, x, y, text, scale=1.5):
    # Convertir en coordonnées PDF sans décalage artificiel
    x_pdf = x / scale
    y_pdf = (letter[1] - y / scale)

    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=letter)
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




def apply_signature(pdf_path, sig_data, output_path, x, y, scale=1.5):
    """
    Applique la signature sur le PDF en utilisant les dimensions reelles de la page
    et en conservant la transparence de l image PNG.
    x, y sont exprimes en points dans le repere du PDF.
    """
    from reportlab.lib.utils import ImageReader

    # lecture du PDF pour connaitre sa taille
    reader = PdfReader(pdf_path)
    page = reader.pages[0]
    media = page.mediabox
    page_w = float(media.width)
    page_h = float(media.height)

    # decode de l image de signature
    if sig_data.startswith("data:image/png;base64,"):
        sig_data = sig_data.split(",",1)[1]
    image_bytes = base64.b64decode(sig_data)
    # chargement avec canal alpha
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    # creation du canevas avec la taille de la page
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(page_w, page_h))
    # dessin de l image en respectant transparence
    dpi_x, dpi_y = image.info.get("dpi", (72,72))
    w_pt = image.width * 72.0 / dpi_x
    h_pt = image.height * 72.0 / dpi_y
    can.drawImage(ImageReader(io.BytesIO(image_bytes)), x, y, width=w_pt, height=h_pt, mask='auto')
    can.save()

    packet.seek(0)
    overlay = PdfReader(packet)
    writer = PdfWriter()

    # fusion de l overlay sur chaque page
    for page in reader.pages:
        page.merge_page(overlay.pages[0])
        writer.add_page(page)

    # ecriture du PDF final
    with open(output_path, 'wb') as f_out:
        writer.write(f_out)



def save_signature_image(data_url, session_id, index):
    if data_url.startswith("data:image/png;base64,"):
        data_url = data_url.replace("data:image/png;base64,", "")
    sig_data = base64.b64decode(data_url)
    sig_path = os.path.join(UPLOAD_FOLDER, f"{session_id}_sig_{index}.png")
    with open(sig_path, 'wb') as f:
        f.write(sig_data)
    return sig_path

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
    msg.set_content(f"Bonjour, veuillez signer ici : {app_url}/sign/{session_id}/{step}")
    try:
        with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
            server.starttls()
            server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
            server.send_message(msg)
    except Exception as e:
        logger.error(f"Erreur SMTP pour {recipient} : {e}")
            log.write(f"[ERROR] email vers {recipient} : {e}\n")

def send_pdf_to_all(session_data):
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
            msg.set_content('Voici le PDF final signé.')
            msg.add_attachment(content, maintype='application', subtype='pdf', filename='document_final.pdf')
            try:
                with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
                    server.starttls()
                    server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
                    server.send_message(msg)
            except Exception as e:
                logger.error(f"Erreur SMTP pour {recipient} : {e}")
                    log.write(f"[ERROR] PDF à {recipient} : {e}\n")


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)