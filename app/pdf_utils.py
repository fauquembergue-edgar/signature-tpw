# app/pdf_utils.py
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PyPDF2 import PdfReader, PdfWriter
from PIL import Image

def create_overlay(sign_image_path: str, coords: tuple, page_size=letter):
    # creation d un overlay avec la signature
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=page_size)
    img = Image.open(sign_image_path)
    w, h = img.size
    # mise a l echelle pour 150 dpi
    scale = 150 / img.info.get("dpi", (150,150))[0]
    c.drawImage(sign_image_path, coords[0], coords[1], width=w*scale, height=h*scale, mask="auto")
    c.save()
    buffer.seek(0)
    return buffer

def merge_pdfs(base_pdf_stream, overlay_stream, output_stream):
    # fusion du pdf de base et de l overlay
    base = PdfReader(base_pdf_stream)
    overlay = PdfReader(overlay_stream)
    writer = PdfWriter()
    for page in base.pages:
        page.merge_page(overlay.pages[0])
        writer.add_page(page)
    writer.write(output_stream)
    output_stream.seek(0)
    return output_stream
