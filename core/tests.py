from datetime import timedelta

import json
from pathlib import Path

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, override_settings
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from accounts.models import UserGuru
from core.geo import calculate_haversine, parse_coordinates
from core.models import TitikQRCetak
from core.qr_engine import generate_dynamic_qr_token, verify_dynamic_qr_token
from core.qr_generator import generate_printable_qr_pdf


class GeoUtilityTests(SimpleTestCase):
    def test_same_coordinate_has_zero_distance(self):
        self.assertEqual(calculate_haversine("-6.2", "106.8", "-6.2", "106.8"), 0)

    def test_invalid_coordinates_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_coordinates(91, 0)


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