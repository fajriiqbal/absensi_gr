import uuid
import mimetypes

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from PIL import Image, UnidentifiedImageError

from accounts.models import UserGuru
from core.geo import calculate_haversine, parse_coordinates
from core.models import LokasiSekolah, TitikQRCetak
from core.qr_engine import GURU_PREFIX, PRINTABLE_PREFIX, TV_PREFIX, generate_teacher_qr_token, verify_dynamic_qr_token, verify_teacher_qr_token

from .forms import JadwalPelajaranIzinFormSetFactory, PengajuanIzinForm
from .letters import generate_leave_letter_pdf
from .models import AbsensiLog, PengajuanIzin
from .reporting import MONTH_NAMES, build_attendance_summary, build_attendance_workbook, report_month_name, resolve_report_period
from .schedule import AttendanceScheduleError, record_attendance_event


MAX_SELFIE_SIZE = 5 * 1024 * 1024
REPORT_MONTH_OPTIONS = tuple(enumerate(MONTH_NAMES, start=1))


def api_error(message, status=400):
    return JsonResponse({"status": "error", "message": message}, status=status)


@login_required
def attendance_report(request):
    if request.user.role != "admin" and not request.user.is_superuser:
        raise Http404
    year, month, error = resolve_report_period(request.GET)
    teachers = list(UserGuru.objects.filter(role="guru", is_active=True).order_by("nama_lengkap"))
    selected_teacher_id = request.GET.get("guru", "")
    selected_teacher = None
    if selected_teacher_id:
        try:
            selected_teacher = next(teacher for teacher in teachers if teacher.pk == int(selected_teacher_id))
        except (ValueError, StopIteration):
            error = "Guru yang dipilih tidak ditemukan."
            selected_teacher_id = ""

    logs_query = AbsensiLog.objects.filter(tanggal__year=year, tanggal__month=month).select_related("guru").order_by("tanggal", "guru__nama_lengkap")
    report_teachers = teachers
    if selected_teacher:
        logs_query = logs_query.filter(guru=selected_teacher)
        report_teachers = [selected_teacher]
    logs = list(logs_query)
    summary = build_attendance_summary(logs, report_teachers)

    if request.GET.get("aksi") == "xlsx" and not error:
        workbook = build_attendance_workbook(logs, year, month, report_teachers)
        response = HttpResponse(workbook, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="rekap-absensi-{year}-{month:02d}.xlsx"'
        return response

    return render(request, "attendance/attendance_report.html", {
        "year": year,
        "month": month,
        "month_name": report_month_name(month),
        "month_options": REPORT_MONTH_OPTIONS,
        "teachers": teachers,
        "selected_teacher_id": selected_teacher_id,
        "summary": summary,
        "logs": logs,
        "error": error,
    })


def validate_selfie(upload):
    if not upload:
        raise ValueError("Foto selfie diperlukan untuk scan QR Cetak.")
    if upload.size > MAX_SELFIE_SIZE:
        raise ValueError("Ukuran foto maksimal 5 MB.")
    try:
        image = Image.open(upload)
        image.verify()
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Format foto harus JPEG, PNG, atau WEBP.")
        upload.seek(0)
    except (UnidentifiedImageError, OSError):
        raise ValueError("File selfie bukan gambar yang valid.") from None


def scan_page(request):
    if request.user.role != "guru":
        return render(request, "403.html", status=403)
    return render(request, "attendance/scan.html")


@login_required
def leave_requests(request):
    if request.user.role != "guru":
        return render(request, "403.html", status=403)
    leave_instance = PengajuanIzin(guru=request.user)
    submission_error = False
    if request.method == "POST":
        form = PengajuanIzinForm(request.POST, request.FILES)
        schedule_formset = JadwalPelajaranIzinFormSetFactory(request.POST, instance=leave_instance)
        form_is_valid = form.is_valid()
        if form_is_valid:
            leave_instance.tgl_mulai = form.cleaned_data["tgl_mulai"]
            leave_instance.tgl_selesai = form.cleaned_data["tgl_selesai"]
        schedules_are_valid = schedule_formset.is_valid()
        if form_is_valid and schedules_are_valid:
            with transaction.atomic():
                leave = form.save(commit=False)
                leave.guru = request.user
                leave.save()
                schedule_formset.instance = leave
                schedule_formset.save()
            messages.success(request, "Pengajuan izin berhasil dikirim untuk persetujuan.")
            return redirect("leave-requests")
        submission_error = True
    else:
        form = PengajuanIzinForm()
        schedule_formset = JadwalPelajaranIzinFormSetFactory(instance=leave_instance)
    return render(request, "attendance/leave_requests.html", {
        "form": form,
        "schedule_formset": schedule_formset,
        "submission_error": submission_error,
        "requests": PengajuanIzin.objects.filter(guru=request.user)
        .select_related("approved_by")
        .prefetch_related("jadwal_pelajaran__guru_lukiran"),
    })


@login_required
def teacher_history(request):
    if request.user.role != "guru":
        return render(request, "403.html", status=403)
    return render(request, "attendance/teacher_history.html", {
        "attendance_logs": AbsensiLog.objects.filter(guru=request.user).order_by("-tanggal", "-waktu_masuk"),
        "leave_requests": PengajuanIzin.objects.filter(guru=request.user)
        .select_related("approved_by")
        .order_by("-created_at"),
    })


@login_required
def download_leave_letter(request, pk):
    if request.user.role != "guru":
        raise Http404
    leave = get_object_or_404(
        PengajuanIzin.objects.select_related("guru", "approved_by"),
        pk=pk,
        guru=request.user,
        status_approval="disetujui",
    )
    response = HttpResponse(generate_leave_letter_pdf(leave), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="surat-izin-{leave.tgl_mulai:%Y%m%d}-{leave.pk}.pdf"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def my_qr(request):
    if request.user.role != "guru":
        return render(request, "403.html", status=403)
    return render(request, "attendance/my_qr.html")


@login_required
@require_POST
def teacher_qr_api(request):
    if request.user.role != "guru":
        return api_error("Akun ini tidak memiliki QR guru.", 403)
    response = JsonResponse({"payload": generate_teacher_qr_token(request.user), "ttl": 45})
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    return response


@require_POST
@login_required
def scan_api(request):
    if request.user.role != "guru":
        return api_error("Akun ini tidak memiliki akses presensi guru.", 403)

    qr_payload = request.POST.get("qr_payload", "").strip()
    lat_value = request.POST.get("latitude", "")
    lng_value = request.POST.get("longitude", "")
    method = None
    user_lat = user_lng = None

    if qr_payload.startswith(PRINTABLE_PREFIX):
        try:
            point_id = uuid.UUID(qr_payload.removeprefix(PRINTABLE_PREFIX))
        except ValueError:
            return api_error("QR poster tidak valid.")
        point = TitikQRCetak.objects.filter(kode_lokasi=point_id, is_active=True).first()
        if point is None:
            return api_error("Titik QR tidak dikenal atau sudah dinonaktifkan.")
        if not lat_value or not lng_value:
            return api_error("Lokasi GPS wajib diaktifkan untuk scan QR Cetak.")
        try:
            user_lat, user_lng = parse_coordinates(lat_value, lng_value)
        except ValueError as exc:
            return api_error(str(exc))
        school = LokasiSekolah.objects.order_by("pk").first()
        if school is None:
            return api_error("Lokasi sekolah belum dikonfigurasi oleh administrator.", 503)
        distance = calculate_haversine(user_lat, user_lng, school.latitude, school.longitude)
        if distance > school.radius_toleransi_meter:
            return api_error(f"Absen ditolak. Anda berada {int(distance)} m di luar lokasi sekolah.")
        photo = request.FILES.get("foto_selfie")
        if photo:
            try:
                validate_selfie(photo)
            except ValueError as exc:
                return api_error(str(exc))
        method = "qr_cetak"
    elif qr_payload.startswith(TV_PREFIX):
        claims, valid = verify_dynamic_qr_token(qr_payload.removeprefix(TV_PREFIX))
        if not valid:
            return api_error(claims["error"])
        method = "qr_tv"
        try:
            if lat_value and lng_value:
                user_lat, user_lng = parse_coordinates(lat_value, lng_value)
            else:
                user_lat = user_lng = None
        except ValueError as exc:
            return api_error(str(exc))
    else:
        return api_error("Format QR tidak didukung.")

    try:
        _, event = record_attendance_event(
            request.user,
            method=method,
            latitude=user_lat if method == "qr_cetak" or lat_value else None,
            longitude=user_lng if method == "qr_cetak" or lng_value else None,
            photo=request.FILES.get("foto_selfie") if method == "qr_cetak" else None,
        )
    except AttendanceScheduleError as exc:
        return api_error(str(exc), exc.status)
    except IntegrityError:
        return api_error("Presensi hari ini sudah tercatat dari perangkat lain.", 409)

    return JsonResponse({"status": "ok", "event": event, "message": f"Presensi {event} berhasil dicatat."})


def kiosk_allowed(request):
    return request.user.is_authenticated and (
        request.user.is_staff or request.user.role == "admin" or request.user.is_superuser
    )


@login_required
def kiosk_scan_page(request):
    if not kiosk_allowed(request):
        return render(request, "403.html", status=403)
    return render(request, "attendance/kiosk_scan.html")


@require_POST
@login_required
def kiosk_scan_api(request):
    if not kiosk_allowed(request):
        return api_error("Akses kiosk tidak diizinkan.", 403)
    payload = request.POST.get("qr_payload", "").strip()
    if not payload.startswith(GURU_PREFIX):
        return api_error("QR guru tidak valid.")
    claims, valid = verify_teacher_qr_token(payload.removeprefix(GURU_PREFIX))
    if not valid:
        return api_error(claims["error"])
    guru = UserGuru.objects.filter(pk=claims.get("sub"), role="guru", is_active=True).first()
    if guru is None:
        return api_error("Akun guru tidak ditemukan atau tidak aktif.")
    try:
        _, event = record_attendance_event(guru, method="qr_guru")
    except AttendanceScheduleError as exc:
        return api_error(str(exc), exc.status)
    except IntegrityError:
        return api_error("Presensi hari ini sudah tercatat.", 409)
    return JsonResponse({"status": "ok", "event": event, "message": f"Presensi {event} {guru.nama_lengkap} berhasil dicatat."})


@require_POST
@login_required
def kiosk_manual_api(request):
    if not kiosk_allowed(request):
        return api_error("Akses kiosk tidak diizinkan.", 403)
    nip = request.POST.get("nip", "").strip()
    guru = UserGuru.objects.filter(nip=nip, role="guru", is_active=True).first()
    if guru is None:
        return api_error("NIP guru tidak ditemukan atau tidak aktif.")
    photo = request.FILES.get("foto_selfie")
    today = timezone.localdate()
    existing_log = AbsensiLog.objects.filter(guru=guru, tanggal=today).first()
    if existing_log is None or photo:
        try:
            validate_selfie(photo)
        except ValueError as exc:
            return api_error(str(exc))
    try:
        _, event = record_attendance_event(
            guru,
            method="manual_kiosk",
            photo=photo if existing_log is None else None,
        )
    except AttendanceScheduleError as exc:
        return api_error(str(exc), exc.status)
    except IntegrityError:
        return api_error("Presensi hari ini sudah tercatat.", 409)
    return JsonResponse({"status": "ok", "event": event, "message": f"Presensi {event} {guru.nama_lengkap} berhasil dicatat."})


@login_required
def private_leave_document(request, pk):
    leave = get_object_or_404(PengajuanIzin.objects.select_related("guru"), pk=pk)
    if request.user.pk != leave.guru_id and request.user.role != "kamad" and not request.user.is_staff:
        raise Http404
    return private_file_response(leave.file_bukti)


@login_required
def private_attendance_photo(request, pk):
    log = get_object_or_404(AbsensiLog.objects.select_related("guru"), pk=pk)
    if request.user.pk != log.guru_id and request.user.role != "kamad" and not request.user.is_staff:
        raise Http404
    if not log.foto_masuk:
        raise Http404
    return private_file_response(log.foto_masuk)


def private_file_response(field_file):
    try:
        file_handle = field_file.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404 from None
    response = FileResponse(file_handle, content_type=mimetypes.guess_type(field_file.name)[0] or "application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response