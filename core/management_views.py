from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import UserGuru
from attendance.models import AbsensiLog, PengajuanIzin

from .management_forms import (
    AbsensiLogManagementForm,
    GroupManagementForm,
    JadwalPelajaranIzinManagementFormSet,
    LokasiSekolahManagementForm,
    PengajuanIzinManagementForm,
    TitikQRCetakManagementForm,
    UserGuruManagementForm,
)
from .models import LokasiSekolah, TitikQRCetak
from .views import admin_or_operator


def _require_admin(request):
    if not admin_or_operator(request.user):
        raise Http404


def _record_list(request, *, title, records, search_fields, route, delete_route, list_url, add_url, describe, pdf_route=None):
    query = request.GET.get("q", "").strip()
    if query:
        search = Q()
        for field in search_fields:
            search |= Q(**{f"{field}__icontains": query})
        records = records.filter(search)
    page = Paginator(records, 25).get_page(request.GET.get("page"))
    entries = [
        {
            "record": record,
            "details": describe(record),
            "edit_url": reverse(route, args=(record.pk,)),
            "delete_url": reverse(delete_route, args=(record.pk,)),
            "pdf_url": reverse(pdf_route, args=(record.pk,)) if pdf_route else "",
            "can_delete": not isinstance(record, UserGuru) or record.pk != request.user.pk,
        }
        for record in page.object_list
    ]
    return render(request, "core/admin_record_list.html", {
        "title": title,
        "entries": entries,
        "page": page,
        "query": query,
        "route": route,
        "add_url": add_url,
        "list_url": reverse(list_url),
        "delete_route": delete_route,
    })


@login_required
def manage_users(request):
    _require_admin(request)
    return _record_list(
        request,
        title="Kelola akun",
        records=UserGuru.objects.order_by("nama_lengkap", "pk"),
        search_fields=("nip", "nama_lengkap", "username", "email"),
        route="admin-user-edit",
        delete_route="admin-user-delete-confirm",
        list_url="admin-users",
        add_url=reverse("admin-user-add"),
        describe=lambda user: (
            user.get_role_display(),
            f"NIP {user.nip}",
            "Aktif" if user.is_active else "Nonaktif",
        ),
    )


@login_required
def manage_groups(request):
    _require_admin(request)
    return _record_list(
        request,
        title="Kelola grup dan izin",
        records=Group.objects.prefetch_related("permissions").order_by("name"),
        search_fields=("name",),
        route="admin-group-edit",
        delete_route="admin-group-delete-confirm",
        list_url="admin-groups",
        add_url=reverse("admin-group-add"),
        describe=lambda group: (f"{group.permissions.count()} izin",),
    )


@login_required
def manage_attendance(request):
    _require_admin(request)
    return _record_list(
        request,
        title="Kelola data presensi",
        records=AbsensiLog.objects.select_related("guru").order_by("-tanggal", "-waktu_masuk"),
        search_fields=("guru__nama_lengkap", "guru__nip", "metode_scan", "status"),
        route="admin-attendance-edit",
        delete_route="admin-attendance-delete-confirm",
        list_url="admin-attendance",
        add_url=reverse("admin-attendance-add"),
        describe=lambda log: (
            f"{log.tanggal:%d-%m-%Y}",
            log.get_status_display(),
            log.get_metode_scan_display(),
        ),
    )


@login_required
def manage_leaves(request):
    _require_admin(request)
    return _record_list(
        request,
        title="Kelola pengajuan izin",
        records=PengajuanIzin.objects.select_related("guru", "approved_by").order_by("-created_at"),
        search_fields=("guru__nama_lengkap", "guru__nip", "jenis_izin", "status_approval"),
        route="admin-leave-edit",
        delete_route="admin-leave-delete-confirm",
        list_url="admin-leaves",
        add_url=reverse("admin-leave-add"),
        describe=lambda leave: (
            leave.get_jenis_izin_display(),
            f"{leave.tgl_mulai:%d-%m-%Y} s.d. {leave.tgl_selesai:%d-%m-%Y}",
            leave.get_status_approval_display(),
        ),
    )


@login_required
def manage_locations(request):
    _require_admin(request)
    return _record_list(
        request,
        title="Kelola lokasi sekolah",
        records=LokasiSekolah.objects.order_by("nama_lokasi"),
        search_fields=("nama_lokasi",),
        route="admin-location-edit",
        delete_route="admin-location-delete-confirm",
        list_url="admin-locations",
        add_url=reverse("admin-location-add"),
        describe=lambda location: (
            f"Koordinat {location.latitude}, {location.longitude}",
            f"Radius {location.radius_toleransi_meter} meter",
        ),
    )


@login_required
def manage_qr_points(request):
    _require_admin(request)
    return _record_list(
        request,
        title="Kelola titik QR cetak",
        records=TitikQRCetak.objects.order_by("label_titik"),
        search_fields=("label_titik", "kode_lokasi"),
        route="admin-qr-point-edit",
        delete_route="admin-qr-point-delete-confirm",
        list_url="admin-qr-points",
        add_url=reverse("admin-qr-point-add"),
        pdf_route="qr-pdf",
        describe=lambda point: (
            str(point.kode_lokasi),
            "Aktif" if point.is_active else "Nonaktif",
        ),
    )


def _record_form(request, *, model, form_class, title, list_url, pk=None, formset_factory=None):
    creating = pk is None
    record = None if creating else get_object_or_404(model, pk=pk)
    form = form_class(
        request.POST or None,
        request.FILES or None,
        instance=record,
    )
    formset = None
    if formset_factory:
        formset = formset_factory(
            request.POST or None,
            instance=form.instance,
            prefix="jadwal_pelajaran",
        )
    if request.method == "POST":
        is_valid = form.is_valid()
        if formset is not None:
            is_valid = formset.is_valid() and is_valid
        if is_valid:
            with transaction.atomic():
                saved_record = form.save()
                if formset is not None:
                    formset.instance = saved_record
                    formset.save()
            messages.success(request, f"{title} berhasil {'ditambahkan' if creating else 'diperbarui'}.")
            return redirect(list_url)
    return render(request, "core/admin_record_form.html", {
        "title": title,
        "form": form,
        "formset": formset,
        "list_url": reverse(list_url),
    })


@login_required
def user_add(request):
    _require_admin(request)
    return _record_form(
        request, model=UserGuru, form_class=UserGuruManagementForm,
        title="Tambah akun", list_url="admin-users",
    )


@login_required
def user_edit(request, pk):
    _require_admin(request)
    return _record_form(
        request, model=UserGuru, form_class=UserGuruManagementForm,
        title="Ubah akun", list_url="admin-users", pk=pk,
    )


@login_required
def group_add(request):
    _require_admin(request)
    return _record_form(
        request, model=Group, form_class=GroupManagementForm,
        title="Tambah grup", list_url="admin-groups",
    )


@login_required
def group_edit(request, pk):
    _require_admin(request)
    return _record_form(
        request, model=Group, form_class=GroupManagementForm,
        title="Ubah grup", list_url="admin-groups", pk=pk,
    )


@login_required
def attendance_add(request):
    _require_admin(request)
    return _record_form(
        request, model=AbsensiLog, form_class=AbsensiLogManagementForm,
        title="Tambah data presensi", list_url="admin-attendance",
    )


@login_required
def attendance_edit(request, pk):
    _require_admin(request)
    return _record_form(
        request, model=AbsensiLog, form_class=AbsensiLogManagementForm,
        title="Ubah data presensi", list_url="admin-attendance", pk=pk,
    )


@login_required
def leave_add(request):
    _require_admin(request)
    return _record_form(
        request, model=PengajuanIzin, form_class=PengajuanIzinManagementForm,
        title="Tambah pengajuan izin", list_url="admin-leaves",
        formset_factory=JadwalPelajaranIzinManagementFormSet,
    )


@login_required
def leave_edit(request, pk):
    _require_admin(request)
    return _record_form(
        request, model=PengajuanIzin, form_class=PengajuanIzinManagementForm,
        title="Ubah pengajuan izin", list_url="admin-leaves", pk=pk,
        formset_factory=JadwalPelajaranIzinManagementFormSet,
    )


@login_required
def location_add(request):
    _require_admin(request)
    return _record_form(
        request, model=LokasiSekolah, form_class=LokasiSekolahManagementForm,
        title="Tambah lokasi sekolah", list_url="admin-locations",
    )


@login_required
def location_edit(request, pk):
    _require_admin(request)
    return _record_form(
        request, model=LokasiSekolah, form_class=LokasiSekolahManagementForm,
        title="Ubah lokasi sekolah", list_url="admin-locations", pk=pk,
    )


@login_required
def qr_point_add(request):
    _require_admin(request)
    return _record_form(
        request, model=TitikQRCetak, form_class=TitikQRCetakManagementForm,
        title="Tambah titik QR cetak", list_url="admin-qr-points",
    )


@login_required
def qr_point_edit(request, pk):
    _require_admin(request)
    return _record_form(
        request, model=TitikQRCetak, form_class=TitikQRCetakManagementForm,
        title="Ubah titik QR cetak", list_url="admin-qr-points", pk=pk,
    )


@login_required
@require_POST
def delete_record(request, model_name, pk):
    _require_admin(request)
    record_types = {
        "user": (UserGuru, "admin-users", "akun"),
        "group": (Group, "admin-groups", "grup"),
        "attendance": (AbsensiLog, "admin-attendance", "data presensi"),
        "leave": (PengajuanIzin, "admin-leaves", "pengajuan izin"),
        "location": (LokasiSekolah, "admin-locations", "lokasi sekolah"),
        "qr-point": (TitikQRCetak, "admin-qr-points", "titik QR"),
    }
    if model_name not in record_types:
        raise Http404
    model, list_url, label = record_types[model_name]
    record = get_object_or_404(model, pk=pk)
    if model is UserGuru and record.pk == request.user.pk:
        messages.error(request, "Akun yang sedang digunakan tidak dapat dihapus.")
        return redirect(list_url)
    record.delete()
    messages.success(request, f"{label.capitalize()} berhasil dihapus.")
    return redirect(list_url)


@login_required
def delete_confirmation(request, model_name, pk):
    _require_admin(request)
    record_types = {
        "user": (UserGuru, "admin-users", "akun"),
        "group": (Group, "admin-groups", "grup"),
        "attendance": (AbsensiLog, "admin-attendance", "data presensi"),
        "leave": (PengajuanIzin, "admin-leaves", "pengajuan izin"),
        "location": (LokasiSekolah, "admin-locations", "lokasi sekolah"),
        "qr-point": (TitikQRCetak, "admin-qr-points", "titik QR"),
    }
    if model_name not in record_types:
        raise Http404
    model, list_url, label = record_types[model_name]
    record = get_object_or_404(model, pk=pk)
    if model is UserGuru and record.pk == request.user.pk:
        raise Http404
    return render(request, "core/admin_record_delete.html", {
        "record": record,
        "record_label": label,
        "list_url": reverse(list_url),
        "delete_url": reverse("admin-record-delete", args=(model_name, pk)),
    })
