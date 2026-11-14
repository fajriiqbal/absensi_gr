
from io import BytesIO
from xml.sax.saxutils import escape
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    Image,
)


def generate_leave_letter_pdf(leave):
    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=12 * mm,
        bottomMargin=22 * mm,
        title=f"Surat Persetujuan Izin {leave.guru.nip}",
    )

    styles = getSampleStyleSheet()

    # Warna kop surat
    green = colors.HexColor("#00A651")
    dark_green = colors.HexColor("#173f35")
    light_green = colors.HexColor("#D9E8B5")
    line_green = colors.HexColor("#548044")

    # Style teks
    header_small_style = ParagraphStyle(
        "HeaderSmall",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=green,
    )

    header_name_style = ParagraphStyle(
        "HeaderName",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=green,
    )

    header_detail_style = ParagraphStyle(
        "HeaderDetail",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=green,
    )

    address_style = ParagraphStyle(
        "HeaderAddress",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=10,
        textColor=colors.black,
    )

    title_style = ParagraphStyle(
        "LetterTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=21,
        textColor=dark_green,
    )

    body_style = ParagraphStyle(
        "LetterBody",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontSize=11,
        leading=17,
    )

    label_style = ParagraphStyle(
        "LetterLabel",
        parent=body_style,
        fontName="Helvetica-Bold",
    )

    escape_text = lambda value: escape(
        str(value or "")
    ).replace("\n", "<br/>")

    # ==================================================
    # KOP SURAT MADRASAH
    # ==================================================

    # Lokasi logo:
    # PROJECT_ROOT/static/images/logo-madrasah.png
    logo_path = (
        Path(settings.BASE_DIR)
        / "static"
        / "app"
        / "images"
        / "logo-madrasah.png"
    )

    logo_width = 27 * mm
    logo_height = 27 * mm

    if logo_path.exists():
        logo = Image(
            str(logo_path),
            width=logo_width,
            height=logo_height,
        )
        logo.hAlign = "CENTER"
    else:
        # Tetap dapat membuat PDF jika logo belum tersedia.
        logo = Paragraph("", header_small_style)

    header_content = [
        Paragraph(
            "LEMBAGA PENDIDIKAN MA'ARIF N.U.",
            header_small_style,
        ),
        Paragraph(
            'MADRASAH TSANAWIYAH "SUNAN KALIJAGA"',
            header_name_style,
        ),
        Paragraph(
            "TULUNG KAB. KLATEN",
            header_small_style,
        ),
        Paragraph(
            'TERAKREDITASI : PERINGKAT "B"',
            header_detail_style,
        ),
        Paragraph(
            "NSM : 1212 331 00015"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
            "NISN : 20363773",
            header_detail_style,
        ),
    ]

    header_table = Table(
        [[logo, header_content]],
        colWidths=[32 * mm, 148 * mm],
        hAlign="LEFT",
    )

    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, 0), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ])
    )

    address_table = Table(
        [[
            Paragraph(
                "Alamat: Jl. Raya Tulung – Ngangkruk "
                "KM. 0,1 Kec. Tulung Kab. Klaten "
                "Kode Pos: 57482 "
                "Phone: +6281548697948",
                address_style,
            )
        ]],
        colWidths=[180 * mm],
    )

    address_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), light_green),
            ("BOX", (0, 0), (-1, -1), 0.8, dark_green),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )

    # Garis bawah kop surat
    line_table = Table(
        [[""]],
        colWidths=[180 * mm],
        rowHeights=[1.2 * mm],
    )

    line_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), green),
        ])
    )

    # ==================================================
    # DATA SURAT (LOGIKA ASLI DIPERTAHANKAN)
    # ==================================================

    period = (
        f"{leave.tgl_mulai:%d-%m-%Y} "
        f"s.d. {leave.tgl_selesai:%d-%m-%Y}"
    )

    reference = (
        f"{leave.pk:05d}/MTs.I/T/{leave.tgl_mulai.month}/{leave.tgl_mulai.year}"
    )

    story = [
        # Kop surat
        header_table,
        Spacer(1, 2 * mm),
        address_table,
        Spacer(1, 1 * mm),
        line_table,
        Spacer(1, 8 * mm),

        # Isi surat
        Paragraph("SURAT PERSETUJUAN IZIN", title_style),

        Paragraph(
            f"Nomor: {reference}",
            ParagraphStyle(
                "Ref",
                parent=body_style,
                alignment=TA_CENTER,
            ),
        ),

        Spacer(1, 10 * mm),

        Paragraph(
            "Dengan ini menerangkan bahwa permohonan "
            "izin berikut telah disetujui:",
            body_style,
        ),

        Spacer(1, 4 * mm),
    ]

    details = [
        [
            Paragraph("Nama", label_style),
            Paragraph(
                escape_text(leave.guru.nama_lengkap),
                body_style,
            ),
        ],
        [
            Paragraph("NIP", label_style),
            Paragraph(
                escape_text(leave.guru.nip),
                body_style,
            ),
        ],
        [
            Paragraph("Jenis izin", label_style),
            Paragraph(
                escape_text(leave.get_jenis_izin_display()),
                body_style,
            ),
        ],
        [
            Paragraph("Periode", label_style),
            Paragraph(period, body_style),
        ],
        [
            Paragraph("Alasan", label_style),
            Paragraph(
                escape_text(leave.alasan),
                body_style,
            ),
        ],
    ]
    if leave.jenis_izin == "sakit" and leave.tugas_kelas:
        details.append([
            Paragraph("Tugas kelas", label_style),
            Paragraph(escape_text(leave.tugas_kelas), body_style),
        ])

    table = Table(
        details,
        colWidths=(35 * mm, 120 * mm),
        hAlign="LEFT",
    )

    table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            (
                "LINEBELOW",
                (0, 0),
                (-1, -1),
                0.35,
                colors.HexColor("#dbe1dc"),
            ),
        ])
    )

    story.extend([
        table,
        Spacer(1, 8 * mm),
    ])

    story.append(
        Paragraph(
            "Surat ini diterbitkan sebagai bukti persetujuan "
            "pengajuan izin pada sistem presensi sekolah.",
            body_style,
        )
    )

    story.extend([
        Spacer(1, 14 * mm),
        Paragraph(
            "Disetujui oleh: "
            + escape_text(
                leave.approved_by.nama_lengkap
                if leave.approved_by
                else "Kepala Madrasah"
            ),
            body_style,
        ),
    ])

    approved_at = leave.approved_at or leave.created_at

    story.append(
        Paragraph(
            "Tanggal persetujuan: "
            f"{timezone.localtime(approved_at):%d-%m-%Y}",
            body_style,
        )
    )

    document.build(story)

    return buffer.getvalue()
