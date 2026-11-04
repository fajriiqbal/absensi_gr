from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.conf import settings
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from accounts.models import UserGuru
from attendance.models import AbsensiLog, PengajuanIzin

from .forms import WhatsAppSettingsForm
from .models import TitikQRCetak, WhatsAppSettings
from .qr_engine import generate_dynamic_qr_token
from .qr_generator import generate_printable_qr_pdf
from .whatsapp_links import build_leave_notification_link


def admin_or_operator(user):
    return user.is_authenticated and (user.role == "admin" or user.is_superuser)


def whatsapp_operator(user):
    return user.is_authenticated and (
        user.is_staff or user.role == "admin" or user.is_superuser
    )


@login_required
def admin_dashboard(request):
    if not admin_or_operator(request.user):
        raise Http404
    return render(request, "core/admin_dashboard.html", {
        "teacher_count": UserGuru.objects.filter(role="guru", is_active=True).count(),
        "today_attendance_count": AbsensiLog.objects.filter(tanggal=timezone.localdate()).count(),
        "active_qr_count": TitikQRCetak.objects.filter(is_active=True).count(),
        "pending_leave_count": PengajuanIzin.objects.filter(status_approval="pending").count(),
    })


@login_required
def whatsapp_settings(request):
    if not whatsapp_operator(request.user):
        raise Http404
    config = WhatsAppSettings.get_settings()
    if request.method == "POST":
        form = WhatsAppSettingsForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Pengaturan notifikasi WhatsApp berhasil disimpan.")
            return redirect("whatsapp-settings")
    else:
        form = WhatsAppSettingsForm(instance=config)
    return render(request, "core/whatsapp_settings.html", {
        "form": form,
        "is_ready": bool(config.kamad_phone_number),
    })


@login_required
def leave_notifications(request):
    if not whatsapp_operator(request.user):
        raise Http404
    config = WhatsAppSettings.get_settings()
    paginator = Paginator(
        PengajuanIzin.objects.filter(status_approval="pending")
        .select_related("guru")
        .order_by("-created_at"),
        25,
    )
    page = paginator.get_page(request.GET.get("page"))
    dashboard_url = request.build_absolute_uri(reverse("kamad-dashboard"))
    if config.kamad_phone_number:
        for leave in page.object_list:
            leave.whatsapp_url = build_leave_notification_link(
                config.kamad_phone_number, leave, dashboard_url
            )
    return render(request, "core/leave_notifications.html", {
        "page": page,
        "kamad_phone_number": config.kamad_phone_number,
    })


@login_required
def qr_points(request):
    if not admin_or_operator(request.user):
        raise Http404
    if request.method == "POST":
        label = request.POST.get("label_titik", "").strip()
        if not label or len(label) > 100:
            messages.error(request, "Label titik wajib diisi (maksimal 100 karakter).")
        else:
            titik = TitikQRCetak.objects.create(label_titik=label)
            messages.success(request, "Titik QR berhasil dibuat.")
            return redirect("qr-points")
    return render(request, "core/qr_points.html", {"points": TitikQRCetak.objects.order_by("label_titik")})


@login_required
def qr_pdf(request, pk):
    if not admin_or_operator(request.user):
        raise Http404
    point = get_object_or_404(TitikQRCetak, pk=pk, is_active=True)
    response = HttpResponse(generate_printable_qr_pdf(point), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="qr-{point.kode_lokasi}.pdf"'
    return response


def school_qr_display(request):
    return render(request, "core/school_qr_display.html", {"school_name": settings.SCHOOL_NAME})


@require_GET
def dynamic_qr(request):
    response = JsonResponse({"payload": generate_dynamic_qr_token(), "ttl": 15})
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    return response


@require_GET
def service_worker(request):
    worker_path = settings.BASE_DIR / "static" / "app" / "sw.js"
    response = HttpResponse(worker_path.read_bytes(), content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response