# Configuration de l application
import os
from pydantic import BaseSettings, EmailStr, HttpUrl

class Settings(BaseSettings):
    FLASK_ENV: str = "production"
    SECRET_KEY: str
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USER: EmailStr
    SMTP_PASS: str
    BASE_URL: HttpUrl  # URL de l application
    MAX_PDF_SIZE_MB: int = 10
    # URI de la base de donnees: utilise Postgres en prod sur Render ou sqlite en local
    SQLALCHEMY_DATABASE_URI: str = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:////tmp/signature.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
