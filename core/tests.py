from datetime import time, timedelta
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

from django.contrib.staticfiles import finders
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from attendance.models import AbsensiLog, PengajuanIzin
from accounts.models import UserGuru
from core.geo import calculate_haversine, parse_coordinates
from core.models import (
    JadwalWaktuPresensiKhusus,
    JadwalWaktuPresensiMingguan,
    LokasiSekolah,
    PengaturanWaktuPresensi,
    TitikQRCetak,
    WhatsAppSettings,
)
from core.qr_engine import generate_dynamic_qr_token, verify_dynamic_qr_token
from core.qr_generator import generate_printable_qr_pdf
from core.whatsapp_links import build_leave_notification_link
from core.forms import normalize_phone_number
from openpyxl import Workbook, load_workbook


class GeoUtilityTests(SimpleTestCase):
    def test_same_coordinate_has_zero_distance(self):
        self.assertEqual(calculate_haversine("-6.2", "106.8", "-6.2", "106.8"), 0)

    def test_invalid_coordinates_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_coordinates(91, 0)

    def test_whatsapp_phone_number_normalization(self):
        self.assertEqual(normalize_phone_number("0812-3456-7890"), "+6281234567890")
        self.assertEqual(normalize_phone_number("6281234567890"), "+6281234567890")


@override_settings(SECRET_KEY="test-secret-key-that-is-long-enough-for-hs256")
class QREngineTests(SimpleTestCase):
    def test_dynamic_token_is_valid_and_expires_after_fifteen_seconds(self):
        now = timezone.now()
        payload = generate_dynamic_qr_token(now)
        claims, valid = verify_dynamic_qr_token(payload.split(":", 1)[1], now + timedelta(seconds=14))
        self.assertTrue(valid)
        self.assertEqual(claims["typ"], "school-tv-qr")
        claims, valid = verify_dynamic_qr_token(payload.split(":", 1)[1], now + timedelta(seconds=15))
        self.assertFalse(valid)

    def test_print_pdf_is_generated(self):
        point = TitikQRCetak(label_titik="Pintu Gerbang")
        pdf = generate_printable_qr_pdf(point)
        self.assertTrue(pdf.startswith(b"%PDF"))


class AdminDashboardTests(TestCase):
    def test_admin_can_configure_attendance_times_and_date_specific_early_departure(self):
        admin_user = UserGuru.objects.create_superuser(
            username="schedule-admin",
            nip="900099",
            nama_lengkap="Admin Jadwal",
            email="schedule-admin@example.test",
            password="ScheduleAdmin!734",
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse("attendance-settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="13:40"')

        response = self.client.post(reverse("attendance-settings"), {
            "action": "save_settings",
            "jam_mulai_masuk": "05:00",
            "batas_terlambat": "07:30",
            "jam_mulai_pulang": "14:00",
            "jam_pulang_normal": "13:40",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jam pulang normal harus setelah waktu presensi pulang dibuka.")
        self.assertEqual(PengaturanWaktuPresensi.objects.get(pk=1).jam_pulang_normal, time(13, 40))

        response = self.client.post(reverse("attendance-settings"), {
            "action": "save_settings",
            "jam_mulai_masuk": "05:00",
            "batas_terlambat": "07:30",
            "jam_mulai_pulang": "12:00",
            "jam_pulang_normal": "13:40",
        })
        self.assertRedirects(response, reverse("attendance-settings"))

        response = self.client.post(reverse("attendance-settings"), {
            "action": "save_weekly_schedule",
            "hari": "4",
            "jam_mulai_pulang": "10:30",
            "jam_pulang": "11:00",
        })
        self.assertRedirects(response, reverse("attendance-settings"))
        friday_schedule = JadwalWaktuPresensiMingguan.objects.get(hari=4)
        self.assertEqual(friday_schedule.jam_pulang, time(11, 0))

        response = self.client.get(reverse("attendance-settings"))
        self.assertContains(response, "Jumat")
        self.assertContains(response, "11:00")
        response = self.client.post(reverse("attendance-settings"), {
            "action": "delete_weekly_schedule",
            "weekly_schedule_id": friday_schedule.pk,
        })
        self.assertRedirects(response, reverse("attendance-settings"))
        self.assertFalse(JadwalWaktuPresensiMingguan.objects.filter(pk=friday_schedule.pk).exists())

        special_date = timezone.localdate() + timedelta(days=1)
        response = self.client.post(reverse("attendance-settings"), {
            "action": "save_override",
            "tanggal": special_date.isoformat(),
            "jam_mulai_pulang": "11:30",
            "jam_pulang": "12:00",
            "keterangan": "Kegiatan sekolah selesai lebih awal",
        })
        self.assertRedirects(response, reverse("attendance-settings"))
        override = JadwalWaktuPresensiKhusus.objects.get(tanggal=special_date)
        self.assertEqual(override.jam_pulang, time(12, 0))

        response = self.client.post(reverse("attendance-settings"), {
            "action": "delete_override",
            "override_id": override.pk,
        })
        self.assertRedirects(response, reverse("attendance-settings"))
        self.assertFalse(JadwalWaktuPresensiKhusus.objects.filter(pk=override.pk).exists())

        teacher = UserGuru.objects.create_user(
            username="schedule-teacher",
            nip="910099",
            nama_lengkap="Guru",
            email="schedule-teacher@example.test",
            password="ScheduleTeacher!734",
        )
        self.client.force_login(teacher)
        self.assertEqual(self.client.get(reverse("attendance-settings")).status_code, 404)

    def test_admin_dashboard_is_available_only_to_admin(self):
        admin_user = UserGuru.objects.create_superuser(
            username="dashboard-admin",
            nip="900010",
            nama_lengkap="Admin Dashboard",
            email="dash-admin@example.test",
            password="StrongPass123!",
        )
        self.client.force_login(admin_user)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="page-loading-overlay"')
        self.assertContains(response, "Membuka halaman...")
        self.assertContains(response, "prefers-reduced-motion: reduce")
        self.assertContains(response, "Monitor TV")
        self.assertContains(response, "Antrean WhatsApp")
        self.assertContains(response, 'class="admin-sidebar"')
        self.assertContains(response, "Akun &amp; Hak Akses")
        self.assertContains(response, "Perizinan &amp; Notifikasi")
        self.assertContains(response, "Lokasi &amp; Perangkat QR")
        self.assertContains(response, "Menu Pengelolaan")
        self.assertContains(response, "Kelola akun")
        self.assertContains(response, "Grup dan izin")

        teacher = UserGuru.objects.create_user(
            username="dashboard-guru",
            nip="900011",
            nama_lengkap="Guru Dashboard",
            email="dash-guru@example.test",
            password="StrongPass123!",
        )
        self.client.force_login(teacher)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertEqual(response.status_code, 404)
        teacher.is_staff = True
        teacher.save(update_fields=("is_staff",))
        response = self.client.get(reverse("guru-scan"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/ GURU")
        self.assertNotContains(response, "/ OPERATOR")
        self.assertNotContains(response, "Antrean Notifikasi Izin")
        self.assertNotContains(response, "Pengaturan WhatsApp")
        self.assertNotContains(response, reverse("leave-notifications"))
        self.assertNotContains(response, reverse("whatsapp-settings"))
        self.assertNotContains(response, reverse("admin-users"))
        response = self.client.get("/django-admin/")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_configure_kamad_whatsapp_number(self):
        admin_user = UserGuru.objects.create_superuser(
            username="whatsapp-admin",
            nip="900012",
            nama_lengkap="Admin WhatsApp",
            email="whatsapp-admin@example.test",
            password="StrongPass123!",
        )
        self.client.force_login(admin_user)
        response = self.client.get(reverse("whatsapp-settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tautan WhatsApp tidak dapat mengirim pesan otomatis.")

        response = self.client.post(reverse("whatsapp-settings"), {
            "kamad_phone_number": "0812-3456-7891",
        })
        self.assertRedirects(response, reverse("whatsapp-settings"))
        config = WhatsAppSettings.get_settings()
        self.assertEqual(config.kamad_phone_number, "+6281234567891")

    def test_staff_operator_can_open_leave_queue_but_not_django_admin(self):
        operator = UserGuru.objects.create_user(
            username="leave-operator",
            nip="900014",
            nama_lengkap="Operator",
            email="operator@example.test",
            password="operator-test-password",
            is_staff=True,
        )
        WhatsAppSettings.objects.create(pk=1, kamad_phone_number="+6281234567890")
        leave = PengajuanIzin.objects.create(
            guru=operator,
            jenis_izin="izin",
            tgl_mulai=timezone.localdate(),
            tgl_selesai=timezone.localdate(),
            alasan="Informasi privat yang tidak boleh masuk pesan WhatsApp.",
            file_bukti="bukti.pdf",
        )
        self.client.force_login(operator)

        response = self.client.get(reverse("leave-notifications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, leave.guru.nama_lengkap)
        self.assertContains(response, "wa.me/6281234567890")
        self.assertNotContains(response, "Informasi privat")
        self.assertEqual(self.client.get(reverse("admin-dashboard")).status_code, 404)
        self.assertEqual(self.client.get(reverse("qr-points")).status_code, 404)
        self.assertEqual(self.client.get("/django-admin/").status_code, 403)

    def test_leave_whatsapp_link_contains_only_basic_notification_details(self):
        teacher = UserGuru.objects.create_user(
            username="link-teacher",
            nip="900015",
            nama_lengkap="Guru Contoh",
            email="link-teacher@example.test",
            password="teacher-test-password",
        )
        leave = PengajuanIzin(
            guru=teacher,
            jenis_izin="sakit",
            tgl_mulai=timezone.localdate(),
            tgl_selesai=timezone.localdate(),
            alasan="Alasan pribadi yang tidak boleh dibagikan.",
            file_bukti="bukti.pdf",
        )

        url = build_leave_notification_link("+6281234567890", leave, "https://example.test/kamad/dashboard")
        message = parse_qs(urlsplit(url).query)["text"][0]

        self.assertTrue(url.startswith("https://wa.me/6281234567890?"))
        self.assertIn("Guru Contoh", message)
        self.assertIn("Sakit", message)
        self.assertIn("https://example.test/kamad/dashboard", message)
        self.assertNotIn("Alasan pribadi", message)

    def test_non_admin_cannot_access_whatsapp_settings(self):
        teacher = UserGuru.objects.create_user(
            username="whatsapp-teacher",
            nip="900013",
            nama_lengkap="Guru",
            email="whatsapp-teacher@example.test",
            password="StrongPass123!",
        )
        self.client.force_login(teacher)
        self.assertEqual(self.client.get(reverse("whatsapp-settings")).status_code, 404)
        self.assertEqual(self.client.get(reverse("leave-notifications")).status_code, 404)

    def test_school_monitor_is_public_and_renders(self):
        response = self.client.get(reverse("school-qr-display"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pindai untuk presensi")

    def test_pwa_worker_scope_and_manifest_icons_are_available(self):
        worker = self.client.get(reverse("service-worker"))
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker["Service-Worker-Allowed"], "/")
        self.assertContains(worker, "presensi-static-v4")

        manifest_response = self.client.get(reverse("pwa-manifest"))
        self.assertEqual(manifest_response.status_code, 200)
        manifest = manifest_response.json()
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(
            {icon["src"] for icon in manifest["icons"]},
            {
                reverse("pwa-icon", args=(192,)),
                reverse("pwa-icon", args=(512,)),
            },
        )
        for icon in manifest["icons"]:
            icon_response = self.client.get(icon["src"])
            self.assertEqual(icon_response.status_code, 200)
            self.assertEqual(icon_response["Content-Type"], "image/png")
            with Image.open(BytesIO(icon_response.content)) as image:
                self.assertEqual(image.size, (int(icon["sizes"].split("x")[0]),) * 2)

        self.assertEqual(self.client.get(reverse("pwa-icon", args=(64,))).status_code, 200)
        self.assertEqual(self.client.get(reverse("pwa-icon", args=(180,))).status_code, 200)
        self.assertEqual(self.client.get(reverse("pwa-icon", args=(1024,))).status_code, 404)


class AdminManagementCRUDTests(TestCase):
    def setUp(self):
        self.admin = UserGuru.objects.create_superuser(
            username="crud-admin",
            nip="910000",
            nama_lengkap="Admin CRUD",
            email="crud-admin@example.test",
            password="AdminCrudPass!734",
        )
        self.client.force_login(self.admin)

    def test_dashboard_links_to_all_django_admin_management_sections(self):
        response = self.client.get(reverse("admin-dashboard"))

        self.assertEqual(response.status_code, 200)
        for route_name in (
            "admin-users",
            "admin-groups",
            "admin-attendance",
            "admin-leaves",
            "admin-locations",
            "admin-qr-points",
        ):
            self.assertContains(response, reverse(route_name))
        self.assertNotContains(response, "Panel Data")
        self.assertNotContains(response, reverse("admin:index"))

    def test_all_management_lists_and_create_forms_are_available(self):
        routes = (
            "admin-users",
            "admin-groups",
            "admin-attendance",
            "admin-leaves",
            "admin-locations",
            "admin-qr-points",
            "admin-user-add",
            "admin-group-add",
            "admin-attendance-add",
            "admin-leave-add",
            "admin-location-add",
            "admin-qr-point-add",
        )

        for route_name in routes:
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                if route_name == "admin-leave-add":
                    self.assertContains(response, 'id="add-schedule-form"')

        response = self.client.get(reverse("admin-users"))
        self.assertContains(response, "Unduh template Excel")
        self.assertContains(response, "data-download-progress")
        self.assertContains(response, "Impor akun guru dari Excel")
        self.assertNotContains(
            response,
            reverse("admin-user-delete-confirm", args=(self.admin.pk,)),
        )

    def test_guru_template_download_contains_required_columns_and_instructions(self):
        response = self.client.get(reverse("admin-users-template"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("template-data-guru.xlsx", response["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        self.assertEqual(
            tuple(cell.value for cell in workbook["Data Guru"][1]),
            ("nip", "nama_lengkap", "email", "password"),
        )
        self.assertIn("Petunjuk", workbook.sheetnames)
        workbook.close()

    def test_import_creates_all_guru_accounts_from_template(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Data Guru"
        sheet.append(("nip", "nama_lengkap", "email", "password"))
        sheet.append(("001234", "Guru Pertama", "guru1-import@example.test", "ImportGuru!Pass734"))
        sheet.append(("001235", "Guru Kedua", "guru2-import@example.test", "ImportGuru!Pass735"))
        file_buffer = BytesIO()
        workbook.save(file_buffer)

        response = self.client.post(reverse("admin-users-import"), {
            "file": SimpleUploadedFile(
                "guru.xlsx",
                file_buffer.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("admin-users"))
        self.assertContains(response, "Berhasil membuat 2 akun guru.")
        self.assertEqual(UserGuru.objects.filter(role="guru", nip__in=("001234", "001235")).count(), 2)
        first = UserGuru.objects.get(nip="001234")
        self.assertEqual(first.username, "001234")
        self.assertTrue(first.is_active)
        self.assertTrue(first.check_password("ImportGuru!Pass734"))

    def test_invalid_guru_import_is_atomic_and_reports_row_errors(self):
        UserGuru.objects.create_user(
            username="existing-imported",
            nip="009999",
            nama_lengkap="Guru Lama",
            email="existing-imported@example.test",
            password="ExistingGuru!Pass734",
        )
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Data Guru"
        sheet.append(("nip", "nama_lengkap", "email", "password"))
        sheet.append(("009998", "Guru Baru", "new-imported@example.test", "NewGuru!Pass734"))
        sheet.append(("009999", "Guru Duplikat", "duplicate@example.test", "DuplicateGuru!Pass734"))
        file_buffer = BytesIO()
        workbook.save(file_buffer)

        response = self.client.post(reverse("admin-users-import"), {
            "file": SimpleUploadedFile("guru.xlsx", file_buffer.getvalue()),
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("admin-users"))
        self.assertFalse(UserGuru.objects.filter(nip="009998").exists())
        self.assertContains(response, "Impor dibatalkan")
        self.assertContains(response, "Baris 3")

    def test_import_rejects_non_xlsx_and_empty_file(self):
        for file in (
            SimpleUploadedFile("guru.csv", b"nip,nama_lengkap,email,password"),
            None,
        ):
            with self.subTest(file=file):
                response = self.client.post(reverse("admin-users-import"), {"file": file} if file else {})
                self.assertRedirects(response, reverse("admin-users"))
                self.assertEqual(UserGuru.objects.count(), 1)

    def test_only_admin_can_download_or_import_guru_template(self):
        operator = UserGuru.objects.create_user(
            username="template-operator",
            nip="910006",
            nama_lengkap="Operator Template",
            email="template-operator@example.test",
            password="Operator!Pass734",
            is_staff=True,
        )
        self.client.force_login(operator)
        self.assertEqual(self.client.get(reverse("admin-users-template")).status_code, 404)
        self.assertEqual(self.client.post(reverse("admin-users-import")).status_code, 404)

    def test_user_group_location_and_qr_crud(self):
        response = self.client.post(reverse("admin-user-add"), {
            "username": "managed-teacher",
            "nip": "910001",
            "nama_lengkap": "Guru Dikelola",
            "email": "managed@example.test",
            "role": "guru",
            "password1": "ManagedTeacherPass!734",
            "password2": "ManagedTeacherPass!734",
            "is_active": "on",
        })
        self.assertRedirects(response, reverse("admin-users"))
        managed_user = UserGuru.objects.get(nip="910001")
        self.assertTrue(managed_user.check_password("ManagedTeacherPass!734"))

        response = self.client.post(reverse("admin-user-edit", args=(managed_user.pk,)), {
            "username": "managed-teacher",
            "nip": "910001",
            "nama_lengkap": "Nama Diperbarui",
            "email": "managed@example.test",
            "role": "kamad",
            "password1": "",
            "password2": "",
            "is_active": "on",
        })
        self.assertRedirects(response, reverse("admin-users"))
        managed_user.refresh_from_db()
        self.assertEqual(managed_user.nama_lengkap, "Nama Diperbarui")
        self.assertEqual(managed_user.role, "kamad")
        self.assertTrue(managed_user.check_password("ManagedTeacherPass!734"))

        response = self.client.post(reverse("admin-group-add"), {
            "name": "Operator Tes",
            "permissions": [],
        })
        self.assertRedirects(response, reverse("admin-groups"))
        group = Group.objects.get(name="Operator Tes")
        response = self.client.post(reverse("admin-group-edit", args=(group.pk,)), {
            "name": "Operator Aktif",
            "permissions": [],
        })
        self.assertRedirects(response, reverse("admin-groups"))
        group.refresh_from_db()
        self.assertEqual(group.name, "Operator Aktif")

        response = self.client.post(reverse("admin-location-add"), {
            "nama_lokasi": "Gedung Baru",
            "latitude": "-6.20000000",
            "longitude": "106.80000000",
            "radius_toleransi_meter": "75",
        })
        self.assertRedirects(response, reverse("admin-locations"))
        location = LokasiSekolah.objects.get(nama_lokasi="Gedung Baru")
        response = self.client.post(reverse("admin-location-edit", args=(location.pk,)), {
            "nama_lokasi": "Gedung Utama",
            "latitude": "-6.20000000",
            "longitude": "106.80000000",
            "radius_toleransi_meter": "80",
        })
        self.assertRedirects(response, reverse("admin-locations"))
        location.refresh_from_db()
        self.assertEqual(location.radius_toleransi_meter, 80)

        response = self.client.post(reverse("admin-qr-point-add"), {
            "label_titik": "Pintu Depan",
            "is_active": "on",
        })
        self.assertRedirects(response, reverse("admin-qr-points"))
        point = TitikQRCetak.objects.get(label_titik="Pintu Depan")
        response = self.client.post(reverse("admin-qr-point-edit", args=(point.pk,)), {
            "label_titik": "Pintu Utama",
            "is_active": "on",
        })
        self.assertRedirects(response, reverse("admin-qr-points"))
        point.refresh_from_db()
        self.assertEqual(point.label_titik, "Pintu Utama")

        for model_name, record, list_route in (
            ("user", managed_user, "admin-users"),
            ("group", group, "admin-groups"),
            ("location", location, "admin-locations"),
            ("qr-point", point, "admin-qr-points"),
        ):
            confirm = reverse(f"admin-{model_name.replace('-', '-')}-delete-confirm", args=(record.pk,))
            self.assertEqual(self.client.get(confirm).status_code, 200)
            response = self.client.post(reverse("admin-record-delete", args=(model_name, record.pk)))
            self.assertRedirects(response, reverse(list_route))
            self.assertFalse(type(record).objects.filter(pk=record.pk).exists())

    def test_attendance_and_leave_records_can_be_created_edited_and_deleted(self):
        teacher = UserGuru.objects.create_user(
            username="managed-attendance-teacher",
            nip="910002",
            nama_lengkap="Guru Presensi",
            email="attendance-managed@example.test",
            password="TeacherPass!734",
        )
        response = self.client.post(reverse("admin-attendance-add"), {
            "guru": teacher.pk,
            "waktu_masuk": "2026-11-04T07:00",
            "waktu_pulang": "",
            "lat_masuk": "",
            "long_masuk": "",
            "metode_scan": "manual_kiosk",
            "status": "hadir",
            "catatan": "Data awal",
        })
        self.assertRedirects(response, reverse("admin-attendance"))
        attendance = AbsensiLog.objects.get(guru=teacher)
        response = self.client.get(reverse("admin-attendance-edit", args=(attendance.pk,)))
        self.assertContains(response, 'type="datetime-local"')
        self.assertContains(response, 'value="2026-11-04T07:00"')
        response = self.client.post(reverse("admin-attendance-edit", args=(attendance.pk,)), {
            "guru": teacher.pk,
            "waktu_masuk": "2026-11-04T07:00",
            "waktu_pulang": "",
            "lat_masuk": "",
            "long_masuk": "",
            "metode_scan": "manual_kiosk",
            "status": "terlambat",
            "catatan": "Data diperbarui",
        })
        self.assertRedirects(response, reverse("admin-attendance"))
        attendance.refresh_from_db()
        self.assertEqual(attendance.status, "terlambat")

        leave = PengajuanIzin.objects.create(
            guru=teacher,
            jenis_izin="izin",
            tgl_mulai=timezone.localdate(),
            tgl_selesai=timezone.localdate(),
            alasan="Pengajuan awal",
            file_bukti="existing-evidence.pdf",
        )
        self.assertEqual(self.client.get(reverse("admin-leave-edit", args=(leave.pk,))).status_code, 200)
        response = self.client.post(reverse("admin-leave-edit", args=(leave.pk,)), {
            "guru": teacher.pk,
            "jenis_izin": "cuti",
            "tgl_mulai": timezone.localdate().isoformat(),
            "tgl_selesai": timezone.localdate().isoformat(),
            "alasan": "Pengajuan diperbarui",
            "status_approval": "disetujui",
            "approved_by": "",
            "approved_at": "",
            "catatan_kamad": "Disetujui",
            "jadwal_pelajaran-TOTAL_FORMS": "0",
            "jadwal_pelajaran-INITIAL_FORMS": "0",
            "jadwal_pelajaran-MIN_NUM_FORMS": "0",
            "jadwal_pelajaran-MAX_NUM_FORMS": "20",
        })
        self.assertRedirects(response, reverse("admin-leaves"))
        leave.refresh_from_db()
        self.assertEqual(leave.jenis_izin, "cuti")
        self.assertEqual(leave.status_approval, "disetujui")

        for model_name, record, list_route in (
            ("attendance", attendance, "admin-attendance"),
            ("leave", leave, "admin-leaves"),
        ):
            response = self.client.post(reverse("admin-record-delete", args=(model_name, record.pk)))
            self.assertRedirects(response, reverse(list_route))
            self.assertFalse(type(record).objects.filter(pk=record.pk).exists())

    def test_leave_can_be_created_with_schedule_details(self):
        media_dir = TemporaryDirectory()
        self.addCleanup(media_dir.cleanup)
        self.enterContext(override_settings(
            MEDIA_ROOT=media_dir.name,
            MEDIA_ENCRYPTION_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        ))
        evidence_storage = PengajuanIzin._meta.get_field("file_bukti").storage
        original_location = evidence_storage.location
        evidence_storage.location = media_dir.name
        self.addCleanup(setattr, evidence_storage, "location", original_location)

        teacher = UserGuru.objects.create_user(
            username="leave-managed-teacher",
            nip="910004",
            nama_lengkap="Guru Izin Dashboard",
            email="leave-managed@example.test",
            password="TeacherPass!734",
        )
        buddy = UserGuru.objects.create_user(
            username="leave-managed-buddy",
            nip="910005",
            nama_lengkap="Guru Pengganti Dashboard",
            email="leave-buddy@example.test",
            password="BuddyPass!734",
        )
        today = timezone.localdate()
        weekdays = ("senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu")

        response = self.client.post(reverse("admin-leave-add"), {
            "guru": teacher.pk,
            "jenis_izin": "sakit",
            "tgl_mulai": today.isoformat(),
            "tgl_selesai": today.isoformat(),
            "alasan": "Perlu beristirahat.",
            "file_bukti": SimpleUploadedFile(
                "bukti.pdf", b"%PDF-1.4 bukti", content_type="application/pdf"
            ),
            "status_approval": "pending",
            "approved_by": "",
            "approved_at": "",
            "catatan_kamad": "",
            "jadwal_pelajaran-TOTAL_FORMS": "1",
            "jadwal_pelajaran-INITIAL_FORMS": "0",
            "jadwal_pelajaran-MIN_NUM_FORMS": "0",
            "jadwal_pelajaran-MAX_NUM_FORMS": "20",
            "jadwal_pelajaran-0-hari": weekdays[today.weekday()],
            "jadwal_pelajaran-0-tanggal": today.isoformat(),
            "jadwal_pelajaran-0-mapel_diampu": "Matematika",
            "jadwal_pelajaran-0-jam_pelajaran_diampu": "Jam ke-1",
            "jadwal_pelajaran-0-mapel_lukiran": "IPA",
            "jadwal_pelajaran-0-jam_lukiran": "Jam ke-2",
            "jadwal_pelajaran-0-keterangan_kelas": "VII-A",
            "jadwal_pelajaran-0-guru_lukiran": buddy.pk,
        })

        self.assertRedirects(response, reverse("admin-leaves"))
        leave = PengajuanIzin.objects.get(guru=teacher)
        schedule = leave.jadwal_pelajaran.get()
        self.assertEqual(schedule.guru_lukiran, buddy)
        self.assertEqual(schedule.mapel_diampu, "Matematika")

    def test_staff_operator_cannot_access_dashboard_crud(self):
        operator = UserGuru.objects.create_user(
            username="crud-operator",
            nip="910003",
            nama_lengkap="Operator CRUD",
            email="crud-operator@example.test",
            password="OperatorPass!734",
            is_staff=True,
        )
        self.client.force_login(operator)

        for route_name in ("admin-users", "admin-groups", "admin-attendance", "admin-leaves", "admin-locations", "admin-qr-points"):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 404)