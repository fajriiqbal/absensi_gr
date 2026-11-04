from io import BytesIO
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException

from accounts.models import UserGuru

from .management_forms import UserGuruManagementForm


MAX_UPLOAD_SIZE = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 500
REQUIRED_HEADERS = ("nip", "nama_lengkap", "email", "password")


class GuruImportError(Exception):
    pass


def build_guru_template():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data Guru"
    sheet.append(REQUIRED_HEADERS)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = "A1:D1"
    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["B"].width = 32
    sheet.column_dimensions["C"].width = 36
    sheet.column_dimensions["D"].width = 28
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17634C")
        cell.alignment = Alignment(horizontal="center")
    for row_number in range(2, MAX_IMPORT_ROWS + 2):
        sheet.cell(row=row_number, column=1).number_format = "@"

    instructions = workbook.create_sheet("Petunjuk")
    instructions.append(("Kolom", "Cara mengisi"))
    instructions.append(("nip", "NIP guru, wajib dan harus unik. Isi sebagai teks agar angka nol di depan tidak hilang."))
    instructions.append(("nama_lengkap", "Nama lengkap guru, wajib."))
    instructions.append(("email", "Alamat email yang valid, wajib."))
    instructions.append(("password", "Kata sandi awal, wajib dan harus memenuhi kebijakan kata sandi aplikasi."))
    instructions.append(("username", "Dibuat otomatis dari NIP."))
    instructions.append(("role", "Semua akun yang diimpor akan dibuat dengan role Guru."))
    instructions.append(("Penting", "Simpan file dengan aman. Kata sandi di file ini berupa teks biasa; hapus file setelah impor dan bagikan kata sandi melalui jalur aman."))
    instructions.column_dimensions["A"].width = 22
    instructions.column_dimensions["B"].width = 105
    for cell in instructions[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17634C")
    for row in instructions.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _cell_text(value):
    if not isinstance(value, str):
        return ""
    return value.strip()


def _row_has_values(values):
    return any(value is not None and value != "" for value in values)


def parse_guru_workbook(upload):
    if upload.size > MAX_UPLOAD_SIZE:
        raise GuruImportError("Ukuran file maksimal 5 MB.")
    if not upload.name.lower().endswith(".xlsx"):
        raise GuruImportError("File harus berformat .xlsx.")

    try:
        upload.seek(0)
        workbook = load_workbook(upload, read_only=True, data_only=False)
    except (BadZipFile, InvalidFileException, OSError, ValueError, KeyError) as exc:
        raise GuruImportError("File Excel tidak dapat dibaca. Unduh template resmi lalu isi kembali.") from exc

    try:
        if "Data Guru" not in workbook.sheetnames:
            raise GuruImportError("Sheet bernama 'Data Guru' tidak ditemukan.")
        sheet = workbook["Data Guru"]
        if sheet.max_row > MAX_IMPORT_ROWS + 1:
            raise GuruImportError(f"Jumlah baris data maksimal {MAX_IMPORT_ROWS}.")
        rows = sheet.iter_rows(values_only=False)
        header_cells = next(rows, None)
        if not header_cells:
            raise GuruImportError("Baris header template tidak ditemukan.")
        headers = []
        for cell in header_cells:
            if cell.data_type == "f":
                raise GuruImportError("Header tidak boleh berisi formula.")
            headers.append(_cell_text(cell.value).lower())
        if len(headers) != len(REQUIRED_HEADERS) or set(headers) != set(REQUIRED_HEADERS):
            raise GuruImportError(
                "Kolom template harus tepat: nip, nama_lengkap, email, password."
            )
        indexes = {header: index for index, header in enumerate(headers)}

        pending_users = []
        seen_nips = set()
        errors = []
        row_count = 0
        for row_number, cells in enumerate(rows, start=2):
            values = [cell.value for cell in cells]
            if not _row_has_values(values):
                continue
            row_count += 1
            if row_count > MAX_IMPORT_ROWS:
                raise GuruImportError(f"Jumlah baris data maksimal {MAX_IMPORT_ROWS}.")
            if any(cell.data_type == "f" for cell in cells):
                errors.append(f"Baris {row_number}: formula tidak diperbolehkan.")
                continue

            data = {
                header: _cell_text(values[indexes[header]])
                for header in REQUIRED_HEADERS
            }
            missing = [
                header for header, value in data.items()
                if not value
            ]
            if missing:
                errors.append(
                    f"Baris {row_number}: kolom wajib belum diisi ({', '.join(missing)})."
                )
                continue
            if data["nip"] in seen_nips:
                errors.append(f"Baris {row_number}: NIP duplikat di dalam file.")
                continue
            seen_nips.add(data["nip"])

            form = UserGuruManagementForm(data={
                "username": data["nip"],
                "nip": data["nip"],
                "nama_lengkap": data["nama_lengkap"],
                "email": data["email"],
                "role": "guru",
                "password1": data["password"],
                "password2": data["password"],
                "is_active": "on",
            })
            if not form.is_valid():
                field_errors = "; ".join(
                    f"{form.fields[field].label}: {', '.join(messages)}"
                    for field, messages in form.errors.items()
                )
                errors.append(f"Baris {row_number}: {field_errors}")
                continue
            pending_users.append(form.save(commit=False))

        if not row_count:
            raise GuruImportError("Tidak ada baris data guru untuk diimpor.")
        if errors:
            preview = "\n".join(errors[:20])
            if len(errors) > 20:
                preview += f"\nDan {len(errors) - 20} kesalahan lainnya."
            raise GuruImportError(f"Impor dibatalkan. Perbaiki data berikut:\n{preview}")
        return pending_users
    finally:
        workbook.close()
