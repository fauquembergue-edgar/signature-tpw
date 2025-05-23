# config.py
import os
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

class Settings:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret")
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT   = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER   = os.getenv("SMTP_USER", "")
    SMTP_PASS   = os.getenv("SMTP_PASS", "")
    LOG_FOLDER  = os.getenv("LOG_FOLDER", "logs")

settings = Settings()
