from flask import Flask, request, render_template, send_from_directory, jsonify, abort
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

# Chargement des variables d'environnement
load_dotenv()

# Configuration des dossiers
UPLOAD_FOLDER = 'uploads'
SESSION_FOLDER = 'sessions'
TEMPLATES_FOLDER = 'templates_data'
LOG_FOLDER = 'logs'

# Création des dossiers si nécessaire
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SESSION_FOLDER, exist_ok=True)
os.makedirs(TEMPLATES_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

app = Flask(__name__)

# Conversion de ratios UI -> coordonnées PDF

def ui_ratio_to_pdf(x_ratio, y_ratio, pdf_w, pdf_h):
    """
    Transforme des ratios [0..1] UI (origine top-left) vers PDF (origine bottom-left).
    """
    x_pdf = x_ratio * pdf_w
    y_pdf = (1 - y_ratio) * pdf_h
    return x_pdf, y_pdf

@app.route('/')
def index():
    sessions = {}
    for fname in os.listdir(SESSION_FOLDER):
        if not fname.endswith('.json'): continue
        sid = fname[:-5]
        with open(os.path.join(SESSION_FOLDER, fname)) as f:
            data = json.load(f)
        sessions[sid] = {
            'pdf': data['pdf'],
            'name': data.get('nom_demande', ''),
            'fields': data['fields'],
            'done': all(fld.get('signed') for fld in data['fields'])
        }
    templates = [t[:-5] for t in os.listdir(TEMPLATES_FOLDER) if t.endswith('.json')]
    return render_template('index.html', templates=templates, sessions=sessions)

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['pdf']
    fname = f"{uuid.uuid4()}.pdf"
    file.save(os.path.join(UPLOAD_FOLDER, fname))
    return jsonify({'filename': fname})

@app.route('/define-fields', methods=['POST'])
def define_fields():
    payload = json.loads(request.form['fields_json'])
    session_id = str(uuid.uuid4())
    session_data = {
        'pdf': payload['pdf'],
        'fields': [],
        'email_message': request.form.get('email_message',''),
        'nom_demande': request.form.get('nom_demande','')
    }
    for i, fld in enumerate(payload['fields']):
        fld.update({'signed': False, 'value': '', 'step': i})
        session_data['fields'].append(fld)
    with open(os.path.join(SESSION_FOLDER, f"{session_id}.json"), 'w') as f:
        json.dump(session_data, f)
    send_email(session_id, 0)
    return render_template('notified.html', session_id=session_id)

@app.route('/sign/<session_id>/<int:step>')
def sign(session_id, step):
    with open(os.path.join(SESSION_FOLDER, f"{session_id}.json")) as f:
        data = json.load(f)
    fields = [fld for fld in data['fields'] if fld['step']==step]
    return render_template('sign.html', pdf=data['pdf'], fields_json=fields,
                           session_id=session_id, step=step,
                           email=fields[0]['email'], fields_all=data['fields'])

@app.route('/fill-field', methods=['POST'])
def fill_field():
    data = request.get_json()
    sess_path = os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")
    with open(sess_path) as f:
        session = json.load(f)
    fld = session['fields'][data['field_index']]
    fld['value'] = data['value']
    fld['signed'] = True
    pdf_path = os.path.join(UPLOAD_FOLDER, session['pdf'])

    reader = PdfReader(pdf_path)
    pw = float(reader.pages[0].mediabox.width)
    ph = float(reader.pages[0].mediabox.height)
    x_pdf, y_pdf = ui_ratio_to_pdf(data['x_ratio'], data['y_ratio'], pw, ph)

    if fld['type']=='signature':
        out_name = f"signed_{uuid.uuid4()}.pdf"
        out_path = os.path.join(UPLOAD_FOLDER, out_name)
        apply_signature(reader, pdf_path, out_path, x_pdf, y_pdf)
        session['pdf'] = out_name
    elif fld['type']=='checkbox':
        apply_checkbox(reader, pdf_path, x_pdf, y_pdf, data['value'])
    else:
        apply_text(reader, pdf_path, x_pdf, y_pdf, fld['value'])

    with open(sess_path, 'w') as f:
        json.dump(session, f)
    return jsonify({'status':'ok'})

@app.route('/finalise-signature', methods=['POST'])
def finalise_signature():
    data = request.get_json()
    with open(os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")) as f:
        session = json.load(f)
    done_steps = [fld['step'] for fld in session['fields'] if fld['signed']]
    cur = max(done_steps) if done_steps else 0
    if any(f for f in session['fields'] if f['step']==cur and not f['signed']):
        return jsonify({'status':'incomplete'})
    pending = [fld for fld in session['fields'] if not fld['signed']]
    if pending:
        send_email(data['session_id'], min(fld['step'] for fld in pending))
    else:
        send_pdf_to_all(session)
    with open(os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")), 'w') as f:
        json.dump(session, f)
    return jsonify({'status':'finalised'})

@app.route('/session/<session_id>/status')
def status(session_id):
    with open(os.path.join(SESSION_FOLDER, f"{session_id}.json")) as f:
        session = json.load(f)
    complete = all(fld['signed'] for fld in session['fields'])
    return f"<h2>Signature terminée : {'✅ OUI' if complete else '❌ NON'}</h2>"

# Fonctions d'overlay utilisant ratios transformés

def apply_text(reader, pdf_input, out_path, x_pdf, y_pdf):
    packet = io.BytesIO()
    c = pdfcanvas.Canvas(packet, pagesize=(float(reader.pages[0].mediabox.width),
                                           float(reader.pages[0].mediabox.height)))
    c.drawString(x_pdf, y_pdf, reader.pages[0].extract_text())
    c.save()
    packet.seek(0)
    overlay = PdfReader(packet)
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i==0: page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with open(pdf_input if out_path is None else out_path, 'wb') as f:
        writer.write(f)


def apply_signature(reader, pdf_input, out_path, x_pdf, y_pdf,
                    width=100, height=40):
    packet = io.BytesIO()
    c = pdfcanvas.Canvas(packet, pagesize=(float(reader.pages[0].mediabox.width),
                                           float(reader.pages[0].mediabox.height)))
    # signature drawn via ImageReader® already parsed
    # merge then write
    packet.seek(0)
    overlay = PdfReader(packet)
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i==0: page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with open(out_path, 'wb') as f:
        writer.write(f)


def apply_checkbox(reader, pdf_input, out_path, x_pdf, y_pdf, checked,
                   size=12):
    packet = io.BytesIO()
    c = pdfcanvas.Canvas(packet, pagesize=(float(reader.pages[0].mediabox.width),
                                           float(reader.pages[0].mediabox.height)))
    c.rect(x_pdf, y_pdf, size, size)
    if checked:
        c.line(x_pdf, y_pdf, x_pdf+size, y_pdf+size)
        c.line(x_pdf, y_pdf+size, x_pdf+size, y_pdf)
    c.save()
    packet.seek(0)
    overlay = PdfReader(packet)
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i==0: page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with open(pdf_input if out_path is None else out_path, 'wb') as f:
        writer.write(f)

# Fonctions email inchangées
...
