# app/models.py
from . import db

# modele pour une session de signature
class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    pdf_path = db.Column(db.String(256), nullable=False)

# modele pour un signataire
class Signataire(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    email = db.Column(db.String(128), nullable=False)
    signed = db.Column(db.Boolean, default=False)

# modele pour audit des actions
class Audit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(256), nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
