# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import settings
from .routes.upload import upload_bp
from .routes.sign import sign_bp

# initialisation de la base de donnees
db = SQLAlchemy()

def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()

def create_app():
    app = Flask(__name__)
    # chargement de la configuration
    app.config.from_object(settings)
    # init db
    init_db(app)
    # enregistrement des blueprints
    app.register_blueprint(upload_bp, url_prefix="/upload")
    app.register_blueprint(sign_bp, url_prefix="/sign")
    return app
