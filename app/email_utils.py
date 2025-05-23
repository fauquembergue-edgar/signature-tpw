# app/email_utils.py
import smtplib
from email.message import EmailMessage
import logging
from config import settings

logger = logging.getLogger(__name__)

def send_signed_pdf(to_addr: str, pdf_bytes: bytes, filename: str):
    # envoi du pdf signe par email
    msg = EmailMessage()
    msg["Subject"] = "Document signe"
    msg["From"] = settings.SMTP_USER
    msg["To"] = to_addr
    msg.set_content("Veuillez trouver ci-joint le document signe.")
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
            smtp.send_message(msg)
        logger.info(f"Email envoye a {to_addr}")
    except Exception as e:
        logger.error(f"Echec envoi email a {to_addr}: {e}")
        raise
