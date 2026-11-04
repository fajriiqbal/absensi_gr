from collections import defaultdict
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from django.utils import timezone


MONTH_NAMES = (
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)


def excel_text(value):
    text = str(value or "")
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def parse_report_period(params):
    try:
        month = int(params.get("bulan", ""))
        year = int(params.get("tahun", ""))
    except (TypeError, ValueError):
        raise ValueError("Bulan dan tahun laporan tidak valid.") from None
    if not 1 <= month <= 12 or not 2000 <= year <= 2200:
        raise ValueError("Bulan atau tahun laporan berada di luar rentang yang valid.")
    return year, month


def report_month_name(month):
    return MONTH_NAMES[month - 1]


def resolve_report_period(params):
    today = timezone.localdate()
    if not params.get("bulan") and not params.get("tahun"):
        return today.year, today.month, ""
    try:
        return (*parse_report_period(params), "")
    except ValueError as exc:
        return today.year, today.month, str(exc)


def build_attendance_summary(logs, teachers):
    totals = defaultdict(lambda: {"hadir": 0, "terlambat": 0, "pulang_cepat": 0, "total": 0})
    for teacher in teachers:
        totals[(teacher.pk, teacher.nip, teacher.nama_lengkap)]
    for log in logs:
        item = totals[(log.guru_id, log.guru.nip, log.guru.nama_lengkap)]
        if log.status == "pulang_cepat":
            item["pulang_cepat"] += 1
        elif log.status == "terlambat":
            item["terlambat"] += 1
        else:
            item["hadir"] += 1
        if log.status_pulang == "pulang_cepat" and log.status != "pulang_cepat":
            item["pulang_cepat"] += 1
        item["total"] += 1
    return [
        {"id": key[0], "nip": key[1], "nama": key[2], **counts}
        for key, counts in sorted(totals.items(), key=lambda pair: pair[0][2].casefold())
    ]


def _new_sheet(workbook, title, headers, widths):
    sheet = workbook.active if workbook.active.title == "Sheet" else workbook.create_sheet()
    sheet.title = title
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17634C")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 30
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    return sheet


def _finish_workbook(workbook):
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _excel_datetime(value):
    if value is None:
        return None
    return timezone.localtime(value).replace(tzinfo=None) if timezone.is_aware(value) else value


def build_attendance_workbook(logs, year, month, teachers=()):
    workbook = Workbook()
    workbook.properties.title = f"Rekap Absensi {report_month_name(month)} {year}"
    summary = _new_sheet(
        workbook,
        "Rekap Per Guru",
        ("NIP", "Nama Guru", "Hadir", "Terlambat", "Pulang Cepat", "Total Presensi"),
        (20, 32, 14, 16, 18, 18),
    )
    teacher_summary = build_attendance_summary(logs, teachers)
    for item in teacher_summary:
        summary.append((excel_text(item["nip"]), excel_text(item["nama"]), item["hadir"], item["terlambat"], item["pulang_cepat"], item["total"]))
    summary.auto_filter.ref = f"A1:F{max(1, summary.max_row)}"

    details = workbook.create_sheet("Detail Absensi")
    headers = ("Tanggal", "NIP", "Nama Guru", "Waktu Masuk", "Waktu Pulang", "Metode", "Status Masuk", "Status Pulang", "Catatan")
    for value in headers:
        details.cell(row=1, column=headers.index(value) + 1, value=value)
    for cell in details[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17634C")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    details.row_dimensions[1].height = 30
    details.freeze_panes = "A2"
    details.auto_filter.ref = f"A1:I{max(1, len(logs) + 1)}"
    for index, width in enumerate((14, 20, 32, 18, 18, 32, 20, 22, 40), start=1):
        details.column_dimensions[get_column_letter(index)].width = width
    for log in logs:
        details.append((
            log.tanggal,
            excel_text(log.guru.nip),
            excel_text(log.guru.nama_lengkap),
            _excel_datetime(log.waktu_masuk),
            _excel_datetime(log.waktu_pulang),
            excel_text(log.get_metode_scan_display()),
            excel_text(log.get_status_display()),
            excel_text(log.get_status_pulang_display() if log.status_pulang else ""),
            excel_text(log.catatan),
        ))
    return _finish_workbook(workbook)


def build_leave_workbook(requests, year, month):
    workbook = Workbook()
    workbook.properties.title = f"Rekap Perizinan {report_month_name(month)} {year}"
    summary = _new_sheet(
        workbook,
        "Ringkasan",
        ("Status", "Jumlah Pengajuan"),
        (28, 20),
    )
    status_counts = {"pending": 0, "disetujui": 0, "ditolak": 0}
    for leave in requests:
        status_counts[leave.status_approval] = status_counts.get(leave.status_approval, 0) + 1
    labels = {"pending": "Menunggu Persetujuan", "disetujui": "Disetujui", "ditolak": "Ditolak"}
    for status, label in labels.items():
        summary.append((label, status_counts[status]))
    summary.append(("Total", len(requests)))
    summary.auto_filter.ref = f"A1:B{summary.max_row}"

    details = workbook.create_sheet("Histori Perizinan")
    headers = ("Tanggal Pengajuan", "NIP", "Nama Guru", "Jenis Izin", "Tanggal Mulai", "Tanggal Selesai", "Status", "Diproses Oleh", "Waktu Approval", "Alasan", "Catatan Kamad")
    details.append(headers)
    for cell in details[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17634C")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    details.row_dimensions[1].height = 34
    details.freeze_panes = "A2"
    details.auto_filter.ref = f"A1:K{max(1, len(requests) + 1)}"
    for index, width in enumerate((20, 20, 30, 20, 16, 16, 24, 30, 22, 48, 48), start=1):
        details.column_dimensions[get_column_letter(index)].width = width
    for leave in requests:
        details.append((
            _excel_datetime(leave.created_at),
            excel_text(leave.guru.nip),
            excel_text(leave.guru.nama_lengkap),
            excel_text(leave.get_jenis_izin_display()),
            leave.tgl_mulai,
            leave.tgl_selesai,
            excel_text(leave.get_status_approval_display()),
            excel_text(leave.approved_by.nama_lengkap if leave.approved_by else ""),
            _excel_datetime(leave.approved_at),
            excel_text(leave.alasan),
            excel_text(leave.catatan_kamad),
        ))

    schedule_details = workbook.create_sheet("Rincian Jam Lukiran")
    schedule_headers = (
        "ID Pengajuan", "NIP", "Nama Guru", "Hari", "Tanggal",
        "Mapel Diampu", "Jam Pelajaran", "Mapel Lukiran", "Jam Lukiran",
        "Keterangan Kelas", "Guru Rekan",
    )
    schedule_details.append(schedule_headers)
    for cell in schedule_details[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17634C")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    schedule_details.row_dimensions[1].height = 34
    schedule_details.freeze_panes = "A2"
    for index, width in enumerate((16, 18, 30, 14, 16, 24, 24, 24, 20, 22, 30), start=1):
        schedule_details.column_dimensions[get_column_letter(index)].width = width
    for leave in requests:
        for schedule in leave.jadwal_pelajaran.all():
            schedule_details.append((
                leave.pk,
                excel_text(leave.guru.nip),
                excel_text(leave.guru.nama_lengkap),
                excel_text(schedule.get_hari_display()),
                schedule.tanggal,
                excel_text(schedule.mapel_diampu),
                excel_text(schedule.jam_pelajaran_diampu),
                excel_text(schedule.mapel_lukiran),
                excel_text(schedule.jam_lukiran),
                excel_text(schedule.keterangan_kelas),
                excel_text(schedule.guru_lukiran.nama_lengkap),
            ))
    schedule_details.auto_filter.ref = f"A1:K{max(1, schedule_details.max_row)}"
    return _finish_workbook(workbook)