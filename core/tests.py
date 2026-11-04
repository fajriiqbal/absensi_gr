from datetime import timedelta
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from attendance.models import PengajuanIzin
from accounts.models import UserGuru
from core.geo import calculate_haversine, parse_coordinates
from core.models import TitikQRCetak, WhatsAppSettings
from core.qr_engine import generate_dynamic_qr_token, verify_dynamic_qr_token
from core.qr_generator import generate_printable_qr_pdf
from core.whatsapp_links import build_leave_notification_link
from core.forms import normalize_phone_number


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
        self.assertContains(response, "Buka monitor TV")
        self.assertContains(response, "Antrean notifikasi izin")
        self.assertContains(response, 'class="admin-sidebar"')

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

        manifest_path = finders.find("app/manifest.json")
        self.assertIsNotNone(manifest_path)
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["scope"], "/")
        for icon in manifest["icons"]:
            self.assertIsNotNone(finders.find(icon["src"].removeprefix("/static/")))