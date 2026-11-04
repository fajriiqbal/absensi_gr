from django.test import TestCase
from django.urls import reverse

from accounts.models import UserGuru


class LoginPageTests(TestCase):
    def test_root_redirects_to_login(self):
        response = self.client.get("/")
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)

    def test_superuser_defaults_to_admin_role(self):
        admin_user = UserGuru.objects.create_superuser(
            username="root",
            nip="900000",
            nama_lengkap="Administrator",
            email="admin@example.test",
            password="StrongPass123!",
        )
        self.assertEqual(admin_user.role, "admin")

    def test_superuser_home_opens_admin_dashboard(self):
        admin_user = UserGuru.objects.create_superuser(
            username="root2",
            nip="900003",
            nama_lengkap="Administrator Dua",
            email="admin2@example.test",
            password="StrongPass123!",
        )
        self.client.force_login(admin_user)
        response = self.client.get(reverse("role-home"))
        self.assertRedirects(response, reverse("admin-dashboard"), fetch_redirect_response=False)

    def test_login_page_renders_and_login_uses_nip(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NIP")
        self.assertContains(response, "/static/app/images/logo-madrasah.png?v=4")
        self.assertContains(response, "/pwa/icon/v4/64.png")
        self.assertContains(response, "/pwa/icon/v4/180.png")
        self.assertContains(response, "/pwa/manifest-v4.json")
        UserGuru.objects.create_user(
            username="guru", nip="198002", nama_lengkap="Guru Dua", email="guru2@example.test", password="StrongPass123!"
        )
        response = self.client.post(reverse("login"), {"username": "198002", "password": "StrongPass123!"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("role-home"))

    def test_api_login_returns_only_basic_account_data(self):
        UserGuru.objects.create_user(
            username="guru", nip="198003", nama_lengkap="Guru Tiga", email="guru3@example.test", password="StrongPass123!"
        )
        response = self.client.post(reverse("api-login"), {"nip": "198003", "password": "StrongPass123!"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["role"], "guru")
        self.assertNotIn("password", response.json()["user"])

    def test_pwa_setup_renders_install_status_and_root_worker(self):
        teacher = UserGuru.objects.create_user(
            username="pwa-guru", nip="198004", nama_lengkap="Guru PWA", email="pwa@example.test", password="StrongPass123!"
        )
        self.client.force_login(teacher)
        response = self.client.get(reverse("pwa-setup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "install-status")
        self.assertContains(response, "/service-worker.js")