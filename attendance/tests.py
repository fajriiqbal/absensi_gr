from datetime import timedelta
from io import BytesIO
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from PIL import Image

from accounts.models import UserGuru
from core.models import LokasiSekolah, TitikQRCetak, WhatsAppSettings
from core.qr_engine import PRINTABLE_PREFIX, generate_dynamic_qr_token
from core.whatsapp import WhatsAppDeliveryError

from attendance.models import AbsensiLog, PengajuanIzin


class AttendanceScanTests(TestCase):
    def setUp(self):
        media_dir = TemporaryDirectory()
        self.addCleanup(media_dir.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=media_dir.name, MEDIA_ENCRYPTION_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="))
        photo_storage = AbsensiLog._meta.get_field("foto_masuk").storage
        original_location = photo_storage.location
        photo_storage.location = media_dir.name
        self.addCleanup(setattr, photo_storage, "location", original_location)
        self.teacher = UserGuru.objects.create_user(
            username="guru1", nip="198001", nama_lengkap="Guru Satu", email="guru@example.test", password="StrongPass123!"
        )
        self.client.force_login(self.teacher)

    def test_scan_page_has_mobile_center_action_and_camera_button(self):
        response = self.client.get(reverse("guru-scan"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-scan-shortcut')
        self.assertContains(response, 'id="activate-camera"')
        self.assertContains(response, "attendance-scan-start")
        self.assertContains(response, "selfie tidak diperlukan")
        self.assertNotContains(response, 'id="selfie"')
        self.assertContains(response, 'id="glass-toast-region"')
        self.assertContains(response, "window.showGlassNotification(this.result, this.success ? 'success' : 'error')")

    def test_teacher_qr_page_refreshes_expired_tokens(self):
        response = self.client.get(reverse("guru-my-qr"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "visibilitychange")
        self.assertContains(response, "cache: 'no-store'")

    def test_tv_qr_records_arrival_and_departure_once(self):
        payload = generate_dynamic_qr_token()
        response = self.client.post(reverse("attendance-scan"), {"qr_payload": payload})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["event"], "masuk")
        response = self.client.post(reverse("attendance-scan"), {"qr_payload": generate_dynamic_qr_token()})
        self.assertEqual(response.json()["event"], "pulang")
        self.assertEqual(AbsensiLog.objects.count(), 1)

    def test_printed_qr_enforces_geofence_but_not_selfie(self):
        LokasiSekolah.objects.create(latitude=0, longitude=0, radius_toleransi_meter=100)
        point = TitikQRCetak.objects.create(label_titik="Gerbang")
        payload = f"{PRINTABLE_PREFIX}{point.kode_lokasi}"
        response = self.client.post(reverse("attendance-scan"), {
            "qr_payload": payload, "latitude": "0.01", "longitude": "0", "foto_selfie": self.make_image(),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("di luar lokasi", response.json()["message"])
        response = self.client.post(reverse("attendance-scan"), {
            "qr_payload": payload, "latitude": "0", "longitude": "0",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["event"], "masuk")
        self.assertFalse(AbsensiLog.objects.get(guru=self.teacher).foto_masuk)

    def test_printed_qr_accepts_optional_selfie_and_keeps_it_encrypted(self):
        LokasiSekolah.objects.create(latitude=0, longitude=0, radius_toleransi_meter=100)
        point = TitikQRCetak.objects.create(label_titik="Gerbang")
        payload = f"{PRINTABLE_PREFIX}{point.kode_lokasi}"
        photo_upload = self.make_image()
        plaintext = photo_upload.read()
        photo_upload.seek(0)
        response = self.client.post(reverse("attendance-scan"), {
            "qr_payload": payload, "latitude": "0", "longitude": "0", "foto_selfie": photo_upload,
        })
        self.assertEqual(response.status_code, 200)
        log = AbsensiLog.objects.get(guru=self.teacher)
        with open(log.foto_masuk.path, "rb") as stored_file:
            encrypted = stored_file.read()
        self.assertNotEqual(encrypted, plaintext)
        with log.foto_masuk.open("rb") as decrypted_file:
            self.assertEqual(decrypted_file.read(), plaintext)
        private_response = self.client.get(reverse("private-attendance-photo", args=(log.pk,)))
        self.assertEqual(private_response.status_code, 200)
        self.assertEqual(b"".join(private_response.streaming_content), plaintext)

    def test_kiosk_scan_requires_staff_and_valid_teacher_qr(self):
        response = self.client.post(reverse("kiosk-scan"), {"qr_payload": "invalid"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(reverse("kiosk-scan-page")).status_code, 403)
        self.teacher.is_staff = True
        self.teacher.save(update_fields=("is_staff",))
        page = self.client.get(reverse("kiosk-scan-page"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Pindai QR Guru")
        self.assertContains(page, reverse("kiosk-scan"))

        response = self.client.post(reverse("kiosk-scan"), {"qr_payload": "invalid"})
        self.assertEqual(response.status_code, 400)
        qr_response = self.client.post(reverse("teacher-qr"))
        self.assertEqual(qr_response.status_code, 200)
        self.assertIn("no-store", qr_response["Cache-Control"])
        response = self.client.post(reverse("kiosk-scan"), {"qr_payload": qr_response.json()["payload"]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("berhasil", response.json()["message"])
        log = AbsensiLog.objects.get(guru=self.teacher)
        self.assertEqual(log.metode_scan, "qr_guru")

    @staticmethod
    def make_image():
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="JPEG")
        return SimpleUploadedFile("selfie.jpg", buffer.getvalue(), content_type="image/jpeg")


class LeaveRequestWorkflowTests(TestCase):
    def setUp(self):
        media_dir = TemporaryDirectory()
        self.addCleanup(media_dir.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=media_dir.name, MEDIA_ENCRYPTION_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="))
        evidence_storage = PengajuanIzin._meta.get_field("file_bukti").storage
        original_location = evidence_storage.location
        evidence_storage.location = media_dir.name
        self.addCleanup(setattr, evidence_storage, "location", original_location)
        self.teacher = UserGuru.objects.create_user(
            username="leave-teacher", nip="198020", nama_lengkap="Guru Izin", email="leave@example.test", password="StrongPass123!"
        )
        self.client.force_login(self.teacher)

    def test_teacher_submits_and_downloads_letter_after_approval(self):
        start = timezone.localdate() + timedelta(days=1)
        schedule_buddy = UserGuru.objects.create_user(
            username="schedule-buddy", nip="198022", nama_lengkap="Guru Rekan", email="schedule-buddy@example.test", password="StrongPass123!"
        )
        day_name = ("senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu")[start.weekday()]
        response = self.client.post(reverse("leave-requests"), {
            "jenis_izin": "sakit",
            "tgl_mulai": start.isoformat(),
            "tgl_selesai": (start + timedelta(days=1)).isoformat(),
            "alasan": "Perlu beristirahat karena sakit.",
            "file_bukti": SimpleUploadedFile("bukti.pdf", b"%PDF-1.4 bukti", content_type="application/pdf"),
            "jadwal_pelajaran-TOTAL_FORMS": "1",
            "jadwal_pelajaran-INITIAL_FORMS": "0",
            "jadwal_pelajaran-MIN_NUM_FORMS": "0",
            "jadwal_pelajaran-MAX_NUM_FORMS": "20",
            "jadwal_pelajaran-0-hari": day_name,
            "jadwal_pelajaran-0-tanggal": start.isoformat(),
            "jadwal_pelajaran-0-mapel_diampu": "Bahasa Indonesia",
            "jadwal_pelajaran-0-jam_pelajaran_diampu": "Jam ke-2",
            "jadwal_pelajaran-0-mapel_lukiran": "Bahasa Inggris",
            "jadwal_pelajaran-0-jam_lukiran": "Jam ke-3",
            "jadwal_pelajaran-0-keterangan_kelas": "VII-A",
            "jadwal_pelajaran-0-guru_lukiran": schedule_buddy.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("leave-requests"))
        response = self.client.get(response["Location"])
        self.assertContains(response, "Pengajuan izin berhasil dikirim untuk persetujuan.")
        self.assertContains(response, 'data-message-level="success"')
        leave = PengajuanIzin.objects.get(guru=self.teacher)
        self.assertEqual(leave.status_approval, "pending")
        schedule = leave.jadwal_pelajaran.get()
        self.assertEqual(schedule.mapel_diampu, "Bahasa Indonesia")
        self.assertEqual(schedule.guru_lukiran, schedule_buddy)
        self.assertEqual(schedule.keterangan_kelas, "VII-A")
        self.assertEqual(self.client.get(reverse("leave-letter", args=(leave.pk,))).status_code, 404)

        kamad = UserGuru.objects.create_user(
            username="leave-kamad", nip="900020", nama_lengkap="Kepala Madrasah", email="leave-kamad@example.test", password="StrongPass123!", role="kamad"
        )
        self.client.force_login(kamad)
        approval = self.client.post(reverse("approve-leave", args=(leave.pk,)), {"decision": "disetujui"})
        self.assertEqual(approval.status_code, 200)
        leave.refresh_from_db()
        self.assertIsNotNone(leave.approved_at)

        self.client.force_login(self.teacher)
        letter = self.client.get(reverse("leave-letter", args=(leave.pk,)))
        self.assertEqual(letter.status_code, 200)
        self.assertEqual(letter["Content-Type"], "application/pdf")
        self.assertTrue(letter.content.startswith(b"%PDF"))

        another_teacher = UserGuru.objects.create_user(
            username="other-teacher", nip="198021", nama_lengkap="Guru Lain", email="other@example.test", password="StrongPass123!"
        )
        self.client.force_login(another_teacher)
        self.assertEqual(self.client.get(reverse("leave-letter", args=(leave.pk,))).status_code, 404)

    def test_leave_submission_sends_approved_whatsapp_template(self):
        WhatsAppSettings.objects.create(
            pk=1,
            sender_phone_number_id="123456789012345",
            sender_phone_number="+6281234567890",
            kamad_phone_number="+6281234567891",
            template_name="notifikasi_pengajuan_izin",
            template_language="id",
        )
        api_response = BytesIO(b'{"messages":[{"id":"wamid.test"}]}')
        api_response.status = 200
        today = timezone.localdate()
        with override_settings(WHATSAPP_ACCESS_TOKEN="test-access-token"), patch(
            "core.whatsapp.urlopen", return_value=api_response
        ) as send_request:
            response = self.client.post(reverse("leave-requests"), {
                "jenis_izin": "sakit",
                "tgl_mulai": today.isoformat(),
                "tgl_selesai": today.isoformat(),
                "alasan": "Informasi medis yang tidak boleh dikirim ke WhatsApp.",
                "file_bukti": SimpleUploadedFile("bukti.pdf", b"%PDF-1.4 bukti", content_type="application/pdf"),
                "jadwal_pelajaran-TOTAL_FORMS": "0",
                "jadwal_pelajaran-INITIAL_FORMS": "0",
                "jadwal_pelajaran-MIN_NUM_FORMS": "0",
                "jadwal_pelajaran-MAX_NUM_FORMS": "20",
            })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(send_request.call_count, 1)
        request = send_request.call_args.args[0]
        self.assertIn("/123456789012345/messages", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-access-token")
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], "6281234567891")
        self.assertEqual(payload["type"], "template")
        self.assertEqual(len(payload["template"]["components"][0]["parameters"]), 4)
        self.assertNotIn("Informasi medis", request.data.decode())

    def test_whatsapp_failure_does_not_discard_leave_request(self):
        today = timezone.localdate()
        with patch(
            "attendance.views.send_leave_notification",
            side_effect=WhatsAppDeliveryError("Meta API error"),
        ):
            response = self.client.post(reverse("leave-requests"), {
                "jenis_izin": "izin",
                "tgl_mulai": today.isoformat(),
                "tgl_selesai": today.isoformat(),
                "alasan": "Keperluan keluarga.",
                "file_bukti": SimpleUploadedFile("bukti.pdf", b"%PDF-1.4 bukti", content_type="application/pdf"),
                "jadwal_pelajaran-TOTAL_FORMS": "0",
                "jadwal_pelajaran-INITIAL_FORMS": "0",
                "jadwal_pelajaran-MIN_NUM_FORMS": "0",
                "jadwal_pelajaran-MAX_NUM_FORMS": "20",
            })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PengajuanIzin.objects.filter(guru=self.teacher).count(), 1)
        response = self.client.get(response["Location"])
        self.assertContains(response, "notifikasi WhatsApp ke Kamad gagal dikirim")

    def test_invalid_date_range_does_not_create_request(self):
        today = timezone.localdate()
        response = self.client.post(reverse("leave-requests"), {
            "jenis_izin": "izin",
            "tgl_mulai": (today + timedelta(days=2)).isoformat(),
            "tgl_selesai": (today + timedelta(days=1)).isoformat(),
            "alasan": "Keperluan keluarga.",
            "file_bukti": SimpleUploadedFile("bukti.pdf", b"%PDF-1.4 bukti", content_type="application/pdf"),
            "jadwal_pelajaran-TOTAL_FORMS": "0",
            "jadwal_pelajaran-INITIAL_FORMS": "0",
            "jadwal_pelajaran-MIN_NUM_FORMS": "0",
            "jadwal_pelajaran-MAX_NUM_FORMS": "20",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pengajuan izin belum terkirim. Periksa kembali data yang wajib diisi.")
        self.assertEqual(PengajuanIzin.objects.filter(guru=self.teacher).count(), 0)

    def test_schedule_requires_matching_day_and_leave_date_range(self):
        buddy = UserGuru.objects.create_user(
            username="validation-buddy", nip="198023", nama_lengkap="Guru Pengganti", email="validation-buddy@example.test", password="StrongPass123!"
        )
        start = timezone.localdate() + timedelta(days=1)
        wrong_day = ("senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu")[(start.weekday() + 1) % 7]
        response = self.client.post(reverse("leave-requests"), {
            "jenis_izin": "izin",
            "tgl_mulai": start.isoformat(),
            "tgl_selesai": start.isoformat(),
            "alasan": "Keperluan keluarga.",
            "file_bukti": SimpleUploadedFile("bukti.pdf", b"%PDF bukti", content_type="application/pdf"),
            "jadwal_pelajaran-TOTAL_FORMS": "1",
            "jadwal_pelajaran-INITIAL_FORMS": "0",
            "jadwal_pelajaran-MIN_NUM_FORMS": "0",
            "jadwal_pelajaran-MAX_NUM_FORMS": "20",
            "jadwal_pelajaran-0-hari": wrong_day,
            "jadwal_pelajaran-0-tanggal": start.isoformat(),
            "jadwal_pelajaran-0-mapel_diampu": "IPA",
            "jadwal_pelajaran-0-jam_pelajaran_diampu": "Jam ke-1",
            "jadwal_pelajaran-0-mapel_lukiran": "Matematika",
            "jadwal_pelajaran-0-jam_lukiran": "Jam ke-2",
            "jadwal_pelajaran-0-keterangan_kelas": "VIII-B",
            "jadwal_pelajaran-0-guru_lukiran": buddy.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PengajuanIzin.objects.filter(guru=self.teacher).count(), 0)

    def test_leave_form_renders_schedule_fields_and_required_evidence(self):
        response = self.client.get(reverse("leave-requests"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mapel yang diampu")
        self.assertContains(response, "Keterangan kelas yang dilukirkan")
        self.assertContains(response, "Nama guru yang diajak lukiran")
        self.assertContains(response, "Lampiran bukti")


class AttendanceReportTests(TestCase):
    def test_admin_exports_monthly_attendance_per_teacher(self):
        admin_user = UserGuru.objects.create_superuser(
            username="report-admin", nip="900030", nama_lengkap="Admin Rekap", email="report-admin@example.test", password="StrongPass123!"
        )
        first_teacher = UserGuru.objects.create_user(
            username="report-guru-1", nip="198030", nama_lengkap="Guru Rekap Satu", email="report-guru-1@example.test", password="StrongPass123!"
        )
        second_teacher = UserGuru.objects.create_user(
            username="report-guru-2", nip="198031", nama_lengkap="Guru Rekap Dua", email="report-guru-2@example.test", password="StrongPass123!"
        )
        today = timezone.localdate()
        for teacher, status in ((first_teacher, "hadir"), (second_teacher, "terlambat")):
            AbsensiLog.objects.create(
                guru=teacher,
                waktu_masuk=timezone.now(),
                metode_scan="qr_tv",
                status=status,
            )
        self.client.force_login(admin_user)
        params = {"bulan": today.month, "tahun": today.year, "guru": first_teacher.pk}
        preview = self.client.get(reverse("attendance-report"), params)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Ringkasan per guru")
        params["aksi"] = "xlsx"
        response = self.client.get(reverse("attendance-report"), params)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Disposition"].endswith(".xlsx\""))
        workbook = load_workbook(BytesIO(response.content))
        summary = workbook["Rekap Per Guru"]
        self.assertEqual(summary.max_row, 2)
        self.assertEqual(summary["A2"].value, first_teacher.nip)
        self.assertEqual(summary["C2"].value, 1)
        self.assertEqual(workbook["Detail Absensi"].max_row, 2)

    def test_teacher_cannot_open_admin_attendance_report(self):
        teacher = UserGuru.objects.create_user(
            username="report-guru", nip="198032", nama_lengkap="Guru", email="report-guru@example.test", password="StrongPass123!"
        )
        self.client.force_login(teacher)
        response = self.client.get(reverse("attendance-report"))
        self.assertEqual(response.status_code, 404)