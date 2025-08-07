# On importe toutes les bibliothèques nécessaires pour notre application Flask
from flask import Flask, request, render_template, send_from_directory, jsonify
import os  # Pour gérer les fichiers et dossiers
import uuid  # Pour générer des identifiants uniques (ex: noms de fichiers)
import json  # Pour lire/écrire des fichiers JSON (sessions, templates...)
import smtplib  # Pour envoyer des mails
import base64  # Pour décoder les signatures au format base64
from email.message import EmailMessage  # Pour structurer les mails
from PyPDF2 import PdfReader, PdfWriter  # Pour lire et modifier les fichiers PDF
from reportlab.pdfgen import canvas as pdfcanvas  # Pour dessiner du texte ou des images dans un PDF
from dotenv import load_dotenv  # Pour charger les variables d'environnement depuis un fichier .env
import io  # Pour manipuler des fichiers en mémoire (sans écrire sur disque)
from PIL import Image  # Pour manipuler les images de signature
from reportlab.lib.utils import ImageReader  # Pour lire les images dans un PDF
from shutil import copyfile  # Pour copier un fichier (par exemple : PDF d’origine vers session)

# On charge les variables d’environnement depuis le fichier .env (comme les identifiants mail)
load_dotenv()

# Initialisation de l'application Flask
app = Flask(__name__)

# Définition des chemins pour stocker les différents types de fichiers
UPLOAD_FOLDER = 'uploads'
SESSION_FOLDER = 'sessions'
TEMPLATES_FOLDER = 'templates_data'
LOG_FOLDER = 'logs'
SIGNERS_FILE = 'signers.json'

# Création des dossiers si jamais ils n'existent pas encore
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SESSION_FOLDER, exist_ok=True)
os.makedirs(TEMPLATES_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

# --- Fonctions pour gérer les adresses email des signataires enregistrés ---

# On lit le fichier JSON qui contient les emails des signataires
def load_signers():
    if not os.path.exists(SIGNERS_FILE):
        return []
    with open(SIGNERS_FILE) as f:
        return json.load(f)

# On sauvegarde la liste des emails triée et sans doublons
def save_signers(signers):
    with open(SIGNERS_FILE, 'w') as f:
        json.dump(list(sorted(set(signers))), f)

# On ajoute un email (si pas vide) à la liste des signataires
def add_signer(email):
    email = email.lower().strip()
    if not email:
        return
    signers = set(load_signers())
    signers.add(email)
    save_signers(signers)

# On retire un email de la liste des signataires
def remove_signer(email):
    email = email.lower().strip()
    signers = set(load_signers())
    signers.discard(email)
    save_signers(signers)

# Cette fonction retourne la taille (largeur, hauteur) de la page d’un PDF
def get_pdf_page_size(pdf_path, page_num=0):
    reader = PdfReader(pdf_path)
    mediabox = reader.pages[page_num].mediabox
    width = float(mediabox.width)
    height = float(mediabox.height)
    return width, height

# Cette fonction ajoute une page superposée (overlay) sur un PDF existant
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

# Cette fonction écrit un texte à une position précise sur une page PDF
def apply_text(pdf_path, x, y, text, page_num=0, offset_x=0, offset_y=-20, font_size=14):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    y_pdf = pdf_height - y - font_size  # Conversion car l’origine est en bas dans reportlab
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))
    can.setFont("Helvetica", font_size)
    can.setFillColorRGB(0, 0, 0)  # Texte noir
    can.drawString(x + offset_x, y_pdf + offset_y, text)
    can.save()
    packet.seek(0)
    merge_overlay(pdf_path, packet, output_path=pdf_path, page_num=page_num)

# Cette fonction applique une signature (image) à une position sur le PDF
def apply_signature(pdf_path, sig_data, output_path, x, y, w, h, page_num=0, offset_x=0, offset_y=-100):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    
    # Si la signature est encodée en base64 (avec préfixe), on extrait les données
    if sig_data.startswith("data:image/png;base64,"):
        sig_data = sig_data.split(",", 1)[1]
    
    # On décode la signature et on la charge comme image
    image_bytes = base64.b64decode(sig_data)
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    # On crée un canvas temporaire pour dessiner l’image
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))
    img_io = io.BytesIO()
    image.save(img_io, format="PNG")
    img_io.seek(0)

    # Position de la signature (origine en bas à gauche)
    y_pdf = pdf_height - y - h
    can.drawImage(ImageReader(img_io), x + offset_x, y_pdf + offset_y, width=w, height=h, mask='auto')
    can.save()
    packet.seek(0)
    merge_overlay(pdf_path, packet, output_path=output_path, page_num=page_num)

# Cette fonction dessine une case à cocher à une position donnée, et la coche si demandé
def apply_checkbox(pdf_path, x, y, checked, size=5, page_num=0, offset_x=0, offset_y=-20):
    pdf_width, pdf_height = get_pdf_page_size(pdf_path, page_num)
    y_pdf = pdf_height - y - size
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_width, pdf_height))
    
    # On dessine le carré de la checkbox
    can.rect(x + offset_x, y_pdf + offset_y, size, size)
    
    # Si la case est cochée, on dessine une croix dedans
    if checked:
        can.setLineWidth(2)
        can.line(x + offset_x, y_pdf + offset_y, x + offset_x + size, y_pdf + offset_y + size)
        can.line(x + offset_x, y_pdf + offset_y + size, x + offset_x + size, y_pdf + offset_y)
    
    can.save()
    packet.seek(0)
    merge_overlay(pdf_path, packet, output_path=pdf_path, page_num=page_num)

# Cette fonction applique tous les champs "texte statique" à une page PDF
def apply_static_text_fields(pdf_path, fields, output_path=None, page_num=0, offset_x=0, offset_y=3):
    static_fields = [f for f in fields if f.get("type") == "statictext"]
    if not static_fields:
        return

    reader = PdfReader(pdf_path)
    pdf_w, pdf_h = get_pdf_page_size(pdf_path, page_num)
    packet = io.BytesIO()
    can = pdfcanvas.Canvas(packet, pagesize=(pdf_w, pdf_h))

    # On parcourt tous les champs statiques et on les dessine
    for field in static_fields:
        x_field  = float(field.get("x", 0))
        y_field  = float(field.get("y", 0))
        value    = field.get("value", "")
        font_size = float(field.get("font_size", 14))
        y_pdf = pdf_h - y_field - font_size
        can.setFont("Helvetica", font_size)
        can.drawString(x_field + offset_x, y_pdf + offset_y, value)

    can.save()
    packet.seek(0)

    # On fusionne le PDF d’origine avec les textes ajoutés
    overlay_pdf = PdfReader(packet)
    writer = PdfWriter()
    for i, p in enumerate(reader.pages):
        if i == page_num:
            p.merge_page(overlay_pdf.pages[0])
        writer.add_page(p)
    with open(output_path or pdf_path, "wb") as f:
        writer.write(f)

# Page d’accueil de l’application : on affiche les sessions en cours, les modèles (templates) enregistrés, et les signataires connus
@app.route('/')
def index():
    sessions = {}
    
    # On parcourt tous les fichiers de session (fichiers JSON dans le dossier sessions)
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
    
    # On récupère la liste des templates disponibles
    templates = [f.replace('.json', '') for f in os.listdir(TEMPLATES_FOLDER) if f.endswith('.json')]
    
    # On charge les adresses email des signataires connus
    signers = load_signers()
    
    # On affiche la page HTML avec tous ces éléments
    return render_template("index.html", templates=templates, sessions=sessions, signers=signers)

# Route pour téléverser un fichier PDF
@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['pdf']
    filename = f"{uuid.uuid4()}.pdf"  # On donne un nom unique au fichier
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    return jsonify({'filename': filename})

# Route pour servir un fichier PDF depuis le dossier des uploads
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# Route pour enregistrer un modèle (template) avec les champs définis
@app.route('/save-template', methods=['POST'])
def save_template():
    data = request.get_json()
    name = data.get('name')

    if not name:
        return jsonify({'error': 'Nom de template requis'}), 400

    # On supprime certaines infos sensibles ou inutiles
    cleaned_fields = []
    for field in data['fields']:
        field_clean = {k: v for k, v in field.items() if k not in ['email', 'value', 'signed']}
        if field.get('type') == 'statictext' and 'value' in field:
            field_clean['value'] = field['value']
        cleaned_fields.append(field_clean)

    path = os.path.join(TEMPLATES_FOLDER, f"{name}.json")
    with open(path, 'w') as f:
        json.dump({'pdf': data['pdf'], 'fields': cleaned_fields}, f)

    return jsonify({'status': 'saved', 'pdf': data['pdf'], 'fields': cleaned_fields})

# Route pour charger un modèle (template) existant
@app.route('/load-template/<name>')
def load_template(name):
    path = os.path.join(TEMPLATES_FOLDER, f"{name}.json")
    if not os.path.exists(path):
        return jsonify({'error': 'Template introuvable'}), 404
    with open(path) as f:
        return jsonify(json.load(f))

# Route qui enregistre les champs de signature/textes définis sur le PDF
@app.route('/define-fields', methods=['POST'])
def define_fields():
    data = json.loads(request.form['fields_json'])

    # On vérifie qu’un fichier PDF a bien été spécifié
    if 'pdf' not in data or not data['pdf']:
        return jsonify({'error': "Aucun fichier PDF spécifié."}), 400

    message = request.form.get('email_message', '')
    nom_demande = request.form.get('nom_demande', '')
    session_id = str(uuid.uuid4())
    fields = data['fields']

    # On ajoute automatiquement les adresses email saisies dans la base
    for field in fields:
        if field.get('type') != 'statictext' and field.get('email'):
            add_signer(field['email'])

    # Si le fichier PDF existe, on le copie pour l’associer à la session
    original_pdf_path = os.path.join(UPLOAD_FOLDER, data['pdf'])
    if os.path.isfile(original_pdf_path):
        session_pdf_name = f"{uuid.uuid4()}_session.pdf"
        session_pdf_path = os.path.join(UPLOAD_FOLDER, session_pdf_name)
        copyfile(original_pdf_path, session_pdf_path)
        pdf_filename_for_session = session_pdf_name
    else:
        pdf_filename_for_session = data['pdf']

    # Vérification que tous les champs signables ont un email
    for field in fields:
        if field.get('type') != 'statictext' and not field.get('email'):
            return jsonify({'error': 'Email manquant pour un signataire.'}), 400

    # On enrichit chaque champ avec des infos supplémentaires
    for i, field in enumerate(fields):
        field['signed'] = False
        field['step'] = i  # L’ordre dans lequel les signataires doivent intervenir
        field['page'] = field.get('page', 0)

        # Si largeur/hauteur absentes, on applique une valeur par défaut selon le type
        if 'h' not in field:
            field['h'] = 40 if field['type'] == 'signature' else 15 if field['type'] == 'checkbox' else 40
        if 'w' not in field:
            field['w'] = 120 if field['type'] == 'signature' else 15 if field['type'] == 'checkbox' else 120

    # On enregistre la session dans un fichier JSON
    session_data = {
        'pdf': pdf_filename_for_session,
        'fields': fields,
        'email_message': message,
        'nom_demande': nom_demande,
        'message_final': ''
    }
    session_file_path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    with open(session_file_path, 'w') as f:
        json.dump(session_data, f)

    # On vérifie s’il y a des champs à signer, sinon on revient à la page d’accueil
    signable_fields = [f for f in fields if f.get('type') != 'statictext']
    if signable_fields:
        send_email(session_id, step=0, message_final=None)
        return render_template("notified.html", session_id=session_id)
    else:
        return render_template(
            "index.html",
            templates=[f.replace('.json', '') for f in os.listdir(TEMPLATES_FOLDER) if f.endswith('.json')],
            sessions={}
        )

# Route pour supprimer un modèle (template)
@app.route('/delete-template', methods=['POST'])
def delete_template():
    data = request.get_json()
    name = data.get('name')
    path = os.path.join(TEMPLATES_FOLDER, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)
        return jsonify({'status': 'deleted'})
    else:
        return jsonify({'status': 'not_found'}), 404

# Route pour supprimer une session (et le PDF associé)
@app.route('/delete-session', methods=['POST'])
def delete_session():
    data = request.get_json()
    session_id = data.get('session_id')
    path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                session_data = json.load(f)
            pdf_file = session_data.get('pdf', '')
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf_file)
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except Exception:
            pass
        os.remove(path)
        return jsonify({'status': 'deleted'})
    else:
        return jsonify({'status': 'not_found'}), 404

# Route pour supprimer un signataire (email) de la liste
@app.route('/delete-signer', methods=['POST'])
def delete_signer():
    data = request.get_json()
    email = data.get('email')
    remove_signer(email)
    return jsonify({'status': 'deleted'})

# Route pour récupérer la liste des signataires connus (emails)
@app.route('/get-signers')
def get_signers():
    return jsonify(load_signers())

# Route qui affiche la page de signature pour un signataire donné (à une étape précise)
@app.route('/sign/<session_id>/<int:step>')
def sign(session_id, step):
    session_path = os.path.join(SESSION_FOLDER, f"{session_id}.json")
    
    # On vérifie que la session existe
    if not os.path.exists(session_path):
        return "Session introuvable", 404

    with open(session_path) as f:
        session_data = json.load(f)

    signers = []

    # On construit la liste des signataires associés à cette session
    for f in session_data['fields']:
        if f.get('type') != 'statictext' and 'signer_id' in f and 'email' in f:
            s = {'id': f['signer_id'], 'email': f['email']}
            if s not in signers:
                signers.append(s)

    # On affiche uniquement les champs de cette étape (step) + les textes statiques
    fields = [f for f in session_data['fields'] if (f.get('step', 0) == step or f.get('type') == 'statictext')]

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

# Route appelée quand un champ est rempli (texte, signature ou case cochée)
@app.route('/fill-field', methods=['POST'])
def fill_field():
    data = request.get_json()
    session_path = os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")

    # On récupère les données de session
    with open(session_path) as f:
        session_data = json.load(f)

    field = session_data['fields'][data['field_index']]
    field['value'] = data['value']
    field['signed'] = True

    pdf_path = os.path.join(UPLOAD_FOLDER, session_data['pdf'])
    page_num = field.get('page', 0)
    x = float(field.get('x', 0))
    y = float(field.get('y', 0))
    w = float(field.get('w', 120))
    h = float(field.get('h', 40))

    # Selon le type du champ, on applique la modification correspondante au PDF
    if field['type'] == 'signature':
        new_pdf_name = f"signed_{uuid.uuid4()}.pdf"
        new_pdf_path = os.path.join(UPLOAD_FOLDER, new_pdf_name)
        apply_signature(pdf_path, field['value'], new_pdf_path, x, y, w, h, page_num, offset_x=0, offset_y=10)
        session_data['pdf'] = new_pdf_name

    elif field['type'] == 'checkbox':
        is_checked = data['value'] in ['true', 'on', '1', True]
        apply_checkbox(pdf_path, x, y, is_checked, size=max(w, h), page_num=page_num, offset_x=0, offset_y=2)

    elif field['type'] == 'statictext':
        # Champ statique, on enregistre juste la valeur
        field['value'] = data['value']

    else:
        # Champ de type texte
        apply_text(pdf_path, x, y, data['value'], page_num=page_num, offset_x=0, offset_y=3)

    # On enregistre la session mise à jour
    with open(session_path, 'w') as f:
        json.dump(session_data, f)

    return jsonify({'status': 'ok'})

# Route appelée à la fin de l’étape de signature (par exemple quand tout est signé par l’utilisateur)
@app.route('/finalise-signature', methods=['POST'])
def finalise_signature():
    data = request.get_json()
    session_path = os.path.join(SESSION_FOLDER, f"{data['session_id']}.json")

    with open(session_path) as f:
        session_data = json.load(f)

    # On évite de renvoyer plusieurs fois le même PDF signé
    if session_data.get('final_pdf_sent'):
        return jsonify({'status': 'finalised_already_sent'})

    # On met à jour le message final si fourni
    if data.get('message_final') is not None:
        session_data['message_final'] = data['message_final']

    all_fields = session_data['fields']
    current_step = max(f['step'] for f in all_fields if f['signed']) if any(f['signed'] for f in all_fields) else 0

    # On vérifie que tous les champs de l’étape actuelle ont bien été remplis
    remaining_same = [f for f in all_fields if f['step'] == current_step and not f['signed'] and f["type"] != "statictext"]
    if remaining_same:
        with open(session_path, 'w') as f:
            json.dump(session_data, f)
        return jsonify({'status': 'incomplete'})

    # On vérifie s’il reste d’autres étapes à envoyer
    remaining = [f for f in all_fields if not f['signed'] and f["type"] != "statictext"]
    if remaining:
        next_step = min(f['step'] for f in remaining)
        send_email(data['session_id'], next_step, message_final=session_data.get('message_final'))
        session_data['message_final'] = ""
    else:
        # Tous les champs sont signés, on applique les champs statiques au PDF et on l’envoie à tout le monde
        pdf_path = os.path.join(UPLOAD_FOLDER, session_data['pdf'])
        apply_static_text_fields(pdf_path, all_fields, output_path=pdf_path)
        send_pdf_to_all(session_data)
        session_data['final_pdf_sent'] = True

    # On enregistre la session mise à jour
    with open(session_path, 'w') as f:
        json.dump(session_data, f)

    return jsonify({'status': 'finalised'})

# Fonction qui envoie un email au prochain signataire avec le lien de signature
def send_email(session_id, step, message_final=None):
    session_file = os.path.join(SESSION_FOLDER, f"{session_id}.json")

    # On vérifie que le fichier de session est bien présent et non vide
    if not os.path.isfile(session_file) or os.path.getsize(session_file) == 0:
        print("Le fichier de session est vide ou absent.")
        return

    # On lit les données de session
    with open(session_file) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("Erreur : fichier JSON vide ou corrompu")
            return

    # On cherche l’adresse email du signataire à cette étape
    recipient = next(
        (fld.get('email') for fld in data['fields'] 
         if fld.get('step', 0) == step and fld["type"] != "statictext" and fld.get('email')), 
        None
    )

    if not recipient:
        print(f"Aucun destinataire trouvé pour l'étape {step}")
        return

    # On construit le lien vers la page de signature
    app_url = os.getenv('APP_URL', 'http://localhost:5000')
    link = f"{app_url}/sign/{session_id}/{step}"

    # Création du message email
    msg = EmailMessage()
    msg['Subject'] = 'Signature requise'
    msg['From'] = os.getenv('SMTP_USER')
    msg['To'] = recipient

    # On construit le corps du message
    body = data.get('email_message') or f"Bonjour, veuillez signer ici : {link}"
    if message_final is None:
        message_final = data.get('message_final', '')
    if message_final:
        body += f"\n\nMessage du signataire précédent :\n{message_final}"
    if link not in body:
        body += f"\n{link}"
    msg.set_content(body)

    # Envoi de l’email via le serveur SMTP
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

# Fonction qui envoie le PDF final signé à tous les signataires + à l’émetteur
def send_pdf_to_all(session_data):
    pdf_name = session_data.get('pdf')
    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name)

    # On vérifie que le fichier existe
    if not os.path.isfile(pdf_path):
        return

    with open(pdf_path, 'rb') as f:
        content = f.read()

    message_final = session_data.get('message_final', '')
    sender_email = os.getenv('SMTP_USER')
    recipients = set()

    # On ajoute tous les signataires de la session
    for fld in session_data['fields']:
        recipient = fld.get('email')
        if recipient:
            recipients.add(recipient.lower().strip())

    # On ajoute aussi l'expéditeur si ce n'est pas déjà fait
    if sender_email and sender_email.lower().strip() not in recipients:
        recipients.add(sender_email.lower().strip())

    print("[DEBUG] Destinataires PDF final:", recipients)

    # On envoie le PDF à tous les destinataires
    for recipient in recipients:
        msg = EmailMessage()
        msg['Subject'] = 'Document signé final'
        msg['From'] = sender_email
        msg['To'] = recipient

        # Corps du mail avec éventuel message final
        body = 'Voici le PDF final signé.'
        if message_final:
            body += f"\n\nMessage du signataire :\n{message_final}"
        msg.set_content(body)

        # On attache le PDF au mail
        msg.add_attachment(content,
                           maintype='application',
                           subtype='pdf',
                           filename='document_final.pdf')

        # Envoi du mail
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

# Point d’entrée de l’application Flask quand on exécute le script
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

