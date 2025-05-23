# config.py
import os
from pydantic_settings import BaseSettings
from pydantic import EmailStr, HttpUrl

class Settings(BaseSettings):
    FLASK_ENV: str = "production"
    SECRET_KEY: str
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USER: EmailStr
    SMTP_PASS: str
    BASE_URL: HttpUrl
    MAX_PDF_SIZE_MB: int = 10
    SQLALCHEMY_DATABASE_URI: str = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:////tmp/signature.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
