# app/routes/upload.py
from flask import Blueprint, request, current_app, jsonify
from io import BytesIO
from ..pdf_utils import create_overlay, merge_pdfs
from ..email_utils import send_signed_pdf
from ..models import Session
from .. import db
import os

upload_bp = Blueprint("upload", __name__)

@upload_bp.route("/", methods=["POST"])
def upload_pdf():
    # route pour l upload du pdf
    f = request.files.get("pdf")
    if not f or not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "PDF requis"}), 400
    content = f.read()
    if len(content) > current_app.config["MAX_PDF_SIZE_MB"] * 1024**2:
        return jsonify({"error": "PDF trop volumineux"}), 413
    f.stream.seek(0)

    # sauvegarde du pdf upload
    os.makedirs("uploads", exist_ok=True)
    pdf_path = os.path.join("uploads", f.filename)
    f.save(pdf_path)

    # creation de la session en base
    session = Session(name=f.filename, pdf_path=pdf_path)
    db.session.add(session)
    db.session.commit()

    # creation et fusion de l overlay (coords fixes)
    sig_path = os.path.join(current_app.static_folder, 'sig.png')
    overlay = create_overlay(sig_path, (100,100))
    out_stream = BytesIO()
    merge_pdfs(open(pdf_path,"rb"), overlay, out_stream)

    # envoi du pdf signe
    send_signed_pdf("user@example.com", out_stream.getvalue(), "signed.pdf")
    return jsonify({"status": "envoye", "session_id": session.id})
