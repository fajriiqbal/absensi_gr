from io import BytesIO

import qrcode
from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .qr_engine import PRINTABLE_PREFIX


def generate_printable_qr_image(kode_lokasi_uuid):
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(f"{PRINTABLE_PREFIX}{kode_lokasi_uuid}")
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_printable_qr_pdf(titik_qr):
    image_bytes = generate_printable_qr_image(titik_qr.kode_lokasi)
    buffer = BytesIO()
    page_width, page_height = A4
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"QR Absensi - {titik_qr.label_titik}")
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawCentredString(page_width / 2, page_height - 80, "PRESENSI GURU")
    pdf.setFont("Helvetica", 14)
    pdf.drawCentredString(page_width / 2, page_height - 112, getattr(settings, "SCHOOL_NAME", "Madrasah"))
    pdf.drawImage(ImageReader(BytesIO(image_bytes)), page_width / 2 - 155, page_height / 2 - 100, 310, 310, preserveAspectRatio=True, mask="auto")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(page_width / 2, page_height / 2 - 145, titik_qr.label_titik[:80])
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(page_width / 2, 70, "Wajib berada di area sekolah dan mengambil foto selfie saat presensi.")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()