# config.py
# Configuration de l application
import os
from pydantic import BaseSettings, EmailStr

class Settings(BaseSettings):
    FLASK_ENV: str = "production"
    SECRET_KEY: str = "your_secret_key"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: EmailStr = "fauquember@cy-tech.fr"
    SMTP_PASS: str = "icvj rchk xsyt mgos"
    BASE_URL: str = "http://localhost:5000"  # type as str to avoid HttpUrl validation

    MAX_PDF_SIZE_MB: int = 10
    SQLALCHEMY_DATABASE_URI: str = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:////tmp/signature.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
