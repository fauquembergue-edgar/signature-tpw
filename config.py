# config.py
# Configuration centralisee et validation des variables d environnement
from pydantic import BaseSettings, EmailStr, AnyHttpUrl

class Settings(BaseSettings):
    SECRET_KEY: str
    SMTP_SERVER: str
    SMTP_PORT: int
    SMTP_USER: EmailStr
    SMTP_PASS: str
    BASE_URL: AnyHttpUrl

    MAX_PDF_SIZE_MB: int = 10
    SQLALCHEMY_DATABASE_URI: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
