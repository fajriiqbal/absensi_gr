import calendar
from collections import defaultdict
from copy import copy
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl import load_workbook
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


def build_attendance_summary(logs, teachers, year, month, sick_leaves=()):
    working_days = sum(
        date(year, month, day).weekday() != 6
        for day in range(1, calendar.monthrange(year, month)[1] + 1)
    )
    totals = defaultdict(lambda: {"hadir": 0, "terlambat": 0, "izin_sakit": 0})
    for teacher in teachers:
        totals[(teacher.pk, teacher.nip, teacher.nama_lengkap)]
    for log in logs:
        item = totals[(log.guru_id, log.guru.nip, log.guru.nama_lengkap)]
        if log.status == "terlambat":
            item["terlambat"] += 1
        elif log.status == "hadir":
            item["hadir"] += 1
    for leave in sick_leaves:
        if leave.jenis_izin == "sakit" and leave.status_approval == "disetujui":
            totals[(leave.guru_id, leave.guru.nip, leave.guru.nama_lengkap)]["izin_sakit"] += 1
    return [
        {
            "id": key[0],
            "nip": key[1],
            "nama": key[2],
            **counts,
            "persentase": (
                (counts["hadir"] + counts["terlambat"]) * 100 / working_days
                if working_days
                else 0
            ),
        }
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


def _teacher_sheet_title(workbook, teacher_name, current_sheet):
    invalid_characters = set("[]:*?/\\")
    title = "".join(
        " " if character in invalid_characters else character
        for character in str(teacher_name or "")
    ).strip().strip("'")
    title = title or "Guru"
    reserved_titles = {
        sheet.title.casefold() for sheet in workbook.worksheets if sheet is not current_sheet
    } | {"rekap per guru", "detail absensi"}
    candidate = title[:31]
    suffix_number = 2
    while candidate.casefold() in reserved_titles:
        suffix = f" ({suffix_number})"
        candidate = f"{title[:31 - len(suffix)].rstrip()}{suffix}"
        suffix_number += 1
    return candidate


def build_attendance_workbook(
    logs,
    year,
    month,
    teachers=(),
    teacher_sheet_names=False,
    sick_leaves=(),
):
    logs = list(logs)
    teachers = list(teachers)
    template_path = Path(__file__).resolve().parent.parent / "Absen_Januari_26.xlsx"
    workbook = load_workbook(template_path)
    workbook.properties.title = f"Rekap Absensi {report_month_name(month)} {year}"

    template_sheet = workbook.active
    sunday_fills = [copy(template_sheet.cell(13, column).fill) for column in range(1, template_sheet.max_column + 1)]
    friday_fills = [copy(template_sheet.cell(11, column).fill) for column in range(1, template_sheet.max_column + 1)]
    shift_schedules = {}
    for row in range(8, 38):
        shift_name = template_sheet[f"C{row}"].value
        if shift_name in {"Senin-Kamis", "Jum'at", "Sabtu"} and shift_name not in shift_schedules:
            shift_schedules[shift_name] = (template_sheet[f"E{row}"].value, template_sheet[f"H{row}"].value)
    days_in_month = calendar.monthrange(year, month)[1]
    if days_in_month > 30:
        template_sheet.unmerge_cells("C38:D38")
        template_sheet.insert_rows(38)
        template_sheet.merge_cells("C39:D39")
        for column in range(1, template_sheet.max_column + 1):
            template_sheet.cell(38, column)._style = copy(template_sheet.cell(37, column)._style)
        template_sheet.row_dimensions[38].height = template_sheet.row_dimensions[37].height

    day_names = ("Senin", "Selasa", "Rabu", "Kamis", "Jum'at", "Sabtu", "Minggu")
    logs_by_teacher = defaultdict(dict)
    for log in logs:
        logs_by_teacher[log.guru_id][log.tanggal] = log
    sick_dates_by_teacher = defaultdict(set)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)
    for leave in sick_leaves:
        if leave.jenis_izin != "sakit" or leave.status_approval != "disetujui":
            continue
        leave_start = max(leave.tgl_mulai, first_day)
        leave_end = min(leave.tgl_selesai, last_day)
        for day_number in range((leave_end - leave_start).days + 1):
            sick_date = leave_start + timedelta(days=day_number)
            if sick_date.weekday() != 6:
                sick_dates_by_teacher[leave.guru_id].add(sick_date)

    report_teachers = list(teachers)
    teacher_ids = {teacher.pk for teacher in report_teachers}
    for log in logs:
        if log.guru_id not in teacher_ids:
            report_teachers.append(log.guru)
            teacher_ids.add(log.guru_id)

    if not report_teachers:
        report_teachers = [None]

    for index, teacher in enumerate(report_teachers):
        sheet = template_sheet if index == 0 else workbook.copy_worksheet(template_sheet)
        if teacher:
            sheet.title = (
                _teacher_sheet_title(workbook, teacher.nama_lengkap, sheet)
                if teacher_sheet_names
                else report_month_name(month)
            )
        else:
            sheet.title = "Laporan Absensi"

        for row in range(8, 38 + (days_in_month > 30)):
            for column in range(1, sheet.max_column + 1):
                cell = sheet.cell(row, column)
                if not (isinstance(cell.value, str) and cell.value.startswith("=")):
                    cell.value = None

        if teacher:
            sheet["B4"] = f"PIN : {excel_text(teacher.pk)}"
            sheet["B5"] = f"NIK : {excel_text(teacher.nip)}"
            sheet["I4"] = f": {excel_text(teacher.nama_lengkap)}"
            sheet["R4"] = f": {excel_text(teacher.get_role_display())}"
        else:
            sheet["B4"] = "PIN :"
            sheet["B5"] = "NIK :"
            sheet["I4"] = ":"
            sheet["R4"] = ":"

        sheet["Q3"] = f"Tgl. Periode : {first_day:%d/%m/%Y}  s/d  {last_day:%d/%m/%Y}"

        total_attendance = 0
        total_duration_seconds = 0
        for day_number in range(1, days_in_month + 1):
            current_date = date(year, month, day_number)
            row = 7 + day_number
            weekday = current_date.weekday()
            is_routine_holiday = weekday == 6
            log = logs_by_teacher[teacher.pk].get(current_date) if teacher else None

            row_fills = sunday_fills if is_routine_holiday else friday_fills if weekday == 4 else None
            if row_fills:
                for column, fill in enumerate(row_fills, start=1):
                    sheet.cell(row, column).fill = copy(fill)

            sheet[f"A{row}"] = f"{day_names[weekday]},"
            sheet[f"B{row}"] = current_date
            if is_routine_holiday:
                sheet[f"C{row}"] = "Libur"
                sheet[f"T{row}"] = "Libur Rutin"
                sheet[f"E{row}"] = None
                sheet[f"H{row}"] = None
                sheet[f"F{row}"] = None
                sheet[f"I{row}"] = None
                sheet[f"G{row}"] = None
                sheet[f"J{row}"] = None
                sheet[f"K{row}"] = None
                continue

            if weekday <= 3:
                shift_name = "Senin-Kamis"
            elif weekday == 4:
                shift_name = "Jum'at"
            else:
                shift_name = "Sabtu"

            planned_checkin, planned_checkout = shift_schedules[shift_name]
            sheet[f"C{row}"] = shift_name
            sheet[f"E{row}"] = planned_checkin
            sheet[f"H{row}"] = planned_checkout
            sheet[f"K{row}"] = f"=I{row}-F{row}"

            checkin = _excel_datetime(log.waktu_masuk) if log and log.waktu_masuk else None
            checkout = _excel_datetime(log.waktu_pulang) if log and log.waktu_pulang else None
            checkin_time = checkin.time() if isinstance(checkin, datetime) else None
            checkout_time = checkout.time() if isinstance(checkout, datetime) else None
            is_sick_leave = teacher and current_date in sick_dates_by_teacher[teacher.pk]
            if is_sick_leave and not log:
                checkin_time = planned_checkin
                checkout_time = planned_checkout
            sheet[f"F{row}"] = checkin_time
            sheet[f"I{row}"] = checkout_time

            if checkin_time:
                late_seconds = max(
                    0,
                    (datetime.combine(current_date, checkin_time) - datetime.combine(current_date, planned_checkin)).total_seconds(),
                )
                sheet[f"G{row}"] = str(int(late_seconds // 60))
            if checkout_time:
                early_seconds = max(
                    0,
                    (datetime.combine(current_date, planned_checkout) - datetime.combine(current_date, checkout_time)).total_seconds(),
                )
                sheet[f"J{row}"] = str(int(early_seconds // 60))
            if log:
                total_attendance += 1
                if checkin_time and checkout_time:
                    total_duration_seconds += max(
                        0,
                        int((datetime.combine(current_date, checkout_time) - datetime.combine(current_date, checkin_time)).total_seconds()),
                    )

        summary_row = 38 + (days_in_month > 30)
        total_hours, total_seconds = divmod(total_duration_seconds, 3600)
        total_minutes = total_seconds // 60
        sheet[f"C{summary_row}"] = total_attendance
        sheet[f"K{summary_row}"] = f"{total_hours}.{total_minutes:02d}"
        sheet[f"P{39 + (days_in_month > 30)}"] = f"Klaten, {last_day.day} {report_month_name(month)} {year}"

    summary = _new_sheet(
        workbook,
        "Rekap Per Guru",
        ("NIP", "Nama Guru", "Hadir", "Terlambat", "Izin Sakit", "Kehadiran (%)"),
        (20, 32, 14, 16, 16, 20),
    )
    teacher_summary = build_attendance_summary(logs, teachers, year, month, sick_leaves)
    for item in teacher_summary:
        summary.append((
            excel_text(item["nip"]),
            excel_text(item["nama"]),
            item["hadir"],
            item["terlambat"],
            item["izin_sakit"],
            item["persentase"] / 100,
        ))
        summary.cell(summary.max_row, 6).number_format = "0.0%"
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