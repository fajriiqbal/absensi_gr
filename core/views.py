from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.conf import settings
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.models import UserGuru
from attendance.models import AbsensiLog

from .models import TitikQRCetak
from .qr_engine import generate_dynamic_qr_token
from .qr_generator import generate_printable_qr_pdf


def admin_or_operator(user):
    return user.is_authenticated and (user.role == "admin" or user.is_superuser)


@login_required
def admin_dashboard(request):
    if not admin_or_operator(request.user):
        raise Http404
    return render(request, "core/admin_dashboard.html", {
        "teacher_count": UserGuru.objects.filter(role="guru", is_active=True).count(),
        "today_attendance_count": AbsensiLog.objects.filter(tanggal=timezone.localdate()).count(),
        "active_qr_count": TitikQRCetak.objects.filter(is_active=True).count(),
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