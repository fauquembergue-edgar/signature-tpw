# app/routes/sign.py
from flask import Blueprint, request, render_template, jsonify
from ..models import Session, Signataire
from .. import db

sign_bp = Blueprint("sign", __name__)

@sign_bp.route("/<int:session_id>", methods=["GET"])
def sign_page(session_id):
    # page de signature pour un signataire
    session = Session.query.get_or_404(session_id)
    return render_template("sign.html", session=session)

@sign_bp.route("/<int:session_id>/submit", methods=["POST"])
def submit_sign(session_id):
    # reception de la signature d un signataire
    data = request.form
    email = data.get("email")
    # ici traitement de la signature (image ou coords)
    signataire = Signataire(session_id=session_id, email=email, signed=True)
    db.session.add(signataire)
    db.session.commit()
    return jsonify({"status": "signature enregistree"})
