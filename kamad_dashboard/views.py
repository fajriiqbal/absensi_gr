from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from attendance.models import AbsensiLog, PengajuanIzin
from attendance.reporting import MONTH_NAMES, build_leave_workbook, report_month_name, resolve_report_period


REPORT_MONTH_OPTIONS = tuple(enumerate(MONTH_NAMES, start=1))


def kamad_required(view):
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != "kamad" and not request.user.is_superuser:
            raise Http404
        return view(request, *args, **kwargs)
    return wrapped


@kamad_required
def dashboard(request):
    today = timezone.localdate()
    return render(request, "kamad_dashboard/dashboard.html", {
        "pending_leaves": PengajuanIzin.objects.filter(status_approval="pending")
        .select_related("guru")
        .prefetch_related("jadwal_pelajaran__guru_lukiran"),
        "today": today,
    })


@kamad_required
def leave_report(request):
    year, month, error = resolve_report_period(request.GET)
    requests = list(
        PengajuanIzin.objects.filter(created_at__year=year, created_at__month=month)
        .select_related("guru", "approved_by")
        .prefetch_related("jadwal_pelajaran__guru_lukiran")
        .order_by("-created_at")
    )
    counts = {"pending": 0, "disetujui": 0, "ditolak": 0}
    for leave in requests:
        counts[leave.status_approval] = counts.get(leave.status_approval, 0) + 1
    if request.GET.get("aksi") == "xlsx" and not error:
        workbook = build_leave_workbook(requests, year, month)
        response = HttpResponse(workbook, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="rekap-perizinan-{year}-{month:02d}.xlsx"'
        return response
    return render(request, "kamad_dashboard/leave_report.html", {
        "year": year,
        "month": month,
        "month_name": report_month_name(month),
        "month_options": REPORT_MONTH_OPTIONS,
        "requests": requests,
        "counts": counts,
        "error": error,
    })


@require_GET
@kamad_required
def live_feed(request):
    logs = AbsensiLog.objects.filter(tanggal=timezone.localdate()).select_related("guru").order_by("-waktu_masuk")[:100]
    return JsonResponse({"items": [{
        "nama": log.guru.nama_lengkap,
        "nip": log.guru.nip,
        "waktu_masuk": timezone.localtime(log.waktu_masuk).strftime("%H:%M") if log.waktu_masuk else "-",
        "waktu_pulang": timezone.localtime(log.waktu_pulang).strftime("%H:%M") if log.waktu_pulang else "-",
        "metode": log.get_metode_scan_display(),
        "status": log.get_status_display(),
        "status_pulang": log.get_status_pulang_display() if log.status_pulang else "-",
    } for log in logs]})


@require_POST
@kamad_required
def approve_leave(request, pk):
    leave = get_object_or_404(PengajuanIzin, pk=pk)
    if leave.status_approval != "pending":
        return JsonResponse({"status": "error", "message": "Pengajuan sudah diproses."}, status=409)
    decision = request.POST.get("decision")
    if decision not in {"disetujui", "ditolak"}:
        return JsonResponse({"status": "error", "message": "Keputusan tidak valid."}, status=400)
    leave.status_approval = decision
    leave.approved_by = request.user
    leave.approved_at = timezone.now()
    leave.catatan_kamad = request.POST.get("catatan", "").strip()[:2000]
    leave.save(update_fields=("status_approval", "approved_by", "approved_at", "catatan_kamad"))
    return JsonResponse({"status": "ok", "message": "Keputusan pengajuan berhasil disimpan."})