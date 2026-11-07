from datetime import date, datetime, time, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from PIL import Image

from accounts.models import UserGuru
from core.models import (
    JadwalWaktuPresensiKhusus,
    JadwalWaktuPresensiGuru,
    JadwalWaktuPresensiMingguan,
    LokasiSekolah,
    PengaturanWaktuPresensi,
    TitikQRCetak,
)
from core.qr_engine import PRINTABLE_PREFIX, generate_dynamic_qr_token, verify_dynamic_qr_token

from attendance.models import AbsensiLog, PengajuanIzin
from attendance.schedule import AttendanceScheduleError, record_attendance_event


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
        PengaturanWaktuPresensi.objects.create(
            pk=1,
            jam_mulai_masuk=time(0, 0),
            batas_terlambat=time(0, 1),
            jam_mulai_pulang=time(23, 58),
            jam_pulang_normal=time(23, 59),
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
        settings_obj = PengaturanWaktuPresensi.objects.get(pk=1)
        settings_obj.jam_mulai_pulang = time(12, 0)
        settings_obj.jam_pulang_normal = time(13, 40)
        settings_obj.save()
        today = timezone.localdate()
        local_timezone = timezone.get_current_timezone()
        arrival = timezone.make_aware(datetime.combine(today, time(7, 0)), local_timezone)
        departure = timezone.make_aware(datetime.combine(today, time(12, 0)), local_timezone)
        with (
            patch("attendance.schedule.timezone.now", return_value=arrival),
            patch(
                "attendance.views.verify_dynamic_qr_token",
                side_effect=lambda token: verify_dynamic_qr_token(token, arrival),
            ),
        ):
            payload = generate_dynamic_qr_token(arrival)
            response = self.client.post(reverse("attendance-scan"), {"qr_payload": payload})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["event"], "masuk")
        with (
            patch("attendance.schedule.timezone.now", return_value=departure),
            patch(
                "attendance.views.verify_dynamic_qr_token",
                side_effect=lambda token: verify_dynamic_qr_token(token, departure),
            ),
        ):
            payload = generate_dynamic_qr_token(departure)
            response = self.client.post(reverse("attendance-scan"), {"qr_payload": payload})
            self.assertEqual(response.json()["event"], "pulang")
        self.assertEqual(AbsensiLog.objects.count(), 1)
        self.assertEqual(AbsensiLog.objects.get(guru=self.teacher).status_pulang, "pulang_cepat")

    def test_schedule_windows_and_arrival_and_departure_statuses_are_separate(self):
        settings_obj = PengaturanWaktuPresensi.objects.get(pk=1)
        settings_obj.jam_mulai_masuk = time(5, 0)
        settings_obj.batas_terlambat = time(7, 30)
        settings_obj.jam_mulai_pulang = time(12, 0)
        settings_obj.jam_pulang_normal = time(13, 40)
        settings_obj.save()
        today = timezone.localdate()
        local_timezone = timezone.get_current_timezone()

        def at(hour, minute):
            return timezone.make_aware(datetime.combine(today, time(hour, minute)), local_timezone)

        with self.assertRaisesMessage(AttendanceScheduleError, "dibuka pukul 05:00"):
            record_attendance_event(self.teacher, method="qr_tv", now=at(4, 59))

        log, event = record_attendance_event(self.teacher, method="qr_tv", now=at(7, 31))
        self.assertEqual(event, "masuk")
        self.assertEqual(log.status, "terlambat")
        with self.assertRaisesMessage(AttendanceScheduleError, "dibuka pukul 12:00"):
            record_attendance_event(self.teacher, method="qr_tv", now=at(11, 59))

        log, event = record_attendance_event(self.teacher, method="qr_tv", now=at(13, 39))
        self.assertEqual(event, "pulang")
        self.assertEqual(log.status, "terlambat")
        self.assertEqual(log.status_pulang, "pulang_cepat")

        punctual_teacher = UserGuru.objects.create_user(
            username="punctual-guru",
            nip="198002",
            nama_lengkap="Guru Tepat Waktu",
            email="punctual@example.test",
            password="GuruTepat!734",
        )
        record_attendance_event(punctual_teacher, method="qr_tv", now=at(7, 30))
        log, _ = record_attendance_event(punctual_teacher, method="qr_tv", now=at(13, 40))
        self.assertEqual(log.status, "hadir")
        self.assertEqual(log.status_pulang, "tepat_waktu")

        late_teacher = UserGuru.objects.create_user(
            username="late-guru",
            nip="198003",
            nama_lengkap="Guru Sangat Terlambat",
            email="very-late@example.test",
            password="GuruTelat!734",
        )
        with self.assertRaisesMessage(AttendanceScheduleError, "sudah berakhir pukul 12:00"):
            record_attendance_event(late_teacher, method="qr_tv", now=at(13, 40))

    def test_date_specific_early_departure_schedule_is_used_for_checkout(self):
        settings_obj = PengaturanWaktuPresensi.objects.get(pk=1)
        settings_obj.jam_mulai_masuk = time(5, 0)
        settings_obj.batas_terlambat = time(7, 30)
        settings_obj.jam_mulai_pulang = time(12, 0)
        settings_obj.jam_pulang_normal = time(13, 40)
        settings_obj.save()
        today = timezone.localdate()
        JadwalWaktuPresensiKhusus.objects.create(
            tanggal=today,
            jam_mulai_pulang=time(11, 30),
            jam_pulang=time(12, 0),
            keterangan="Kegiatan sekolah selesai lebih awal",
        )
        local_timezone = timezone.get_current_timezone()

        def at(hour, minute):
            return timezone.make_aware(datetime.combine(today, time(hour, minute)), local_timezone)

        record_attendance_event(self.teacher, method="qr_tv", now=at(7, 0))
        log, _ = record_attendance_event(self.teacher, method="qr_tv", now=at(12, 0))
        self.assertEqual(log.status_pulang, "tepat_waktu")

    def test_weekly_early_departure_schedule_is_used_on_configured_weekday(self):
        settings_obj = PengaturanWaktuPresensi.objects.get(pk=1)
        settings_obj.jam_mulai_masuk = time(5, 0)
        settings_obj.batas_terlambat = time(7, 30)
        settings_obj.jam_mulai_pulang = time(12, 0)
        settings_obj.jam_pulang_normal = time(13, 40)
        settings_obj.save()
        today = timezone.localdate()
        friday = today + timedelta(days=(4 - today.weekday()) % 7)
        JadwalWaktuPresensiMingguan.objects.create(
            hari=4,
            jam_mulai_pulang=time(10, 30),
            jam_pulang=time(11, 0),
        )
        local_timezone = timezone.get_current_timezone()

        def at(hour, minute):
            return timezone.make_aware(datetime.combine(friday, time(hour, minute)), local_timezone)

        record_attendance_event(self.teacher, method="qr_tv", now=at(7, 0))
        with self.assertRaisesMessage(AttendanceScheduleError, "dibuka pukul 10:30"):
            record_attendance_event(self.teacher, method="qr_tv", now=at(10, 29))

        log, event = record_attendance_event(self.teacher, method="qr_tv", now=at(11, 0))
        self.assertEqual(event, "pulang")
        self.assertEqual(log.status_pulang, "tepat_waktu")

    def test_teacher_specific_departure_overrides_global_schedule_for_that_teacher_only(self):
        settings_obj = PengaturanWaktuPresensi.objects.get(pk=1)
        settings_obj.jam_mulai_masuk = time(5, 0)
        settings_obj.batas_terlambat = time(7, 30)
        settings_obj.jam_mulai_pulang = time(12, 0)
        settings_obj.jam_pulang_normal = time(13, 40)
        settings_obj.save()
        today = timezone.localdate()
        JadwalWaktuPresensiKhusus.objects.create(
            tanggal=today,
            jam_mulai_pulang=time(12, 0),
            jam_pulang=time(13, 0),
            keterangan="Jadwal umum",
        )
        JadwalWaktuPresensiGuru.objects.create(
            guru=self.teacher,
            tanggal=today,
            jam_mulai_pulang=time(8, 45),
            jam_pulang=time(9, 0),
        )
        other_teacher = UserGuru.objects.create_user(
            username="other-schedule-teacher",
            nip="198004",
            nama_lengkap="Guru Jadwal Umum",
            email="other-schedule@example.test",
            password="test-password-123",
        )
        local_timezone = timezone.get_current_timezone()

        def at(hour, minute):
            return timezone.make_aware(datetime.combine(today, time(hour, minute)), local_timezone)

        record_attendance_event(self.teacher, method="qr_tv", now=at(7, 0))
        with self.assertRaisesMessage(AttendanceScheduleError, "dibuka pukul 08:45"):
            record_attendance_event(self.teacher, method="qr_tv", now=at(8, 44))
        log, event = record_attendance_event(self.teacher, method="qr_tv", now=at(9, 0))
        self.assertEqual(event, "pulang")
        self.assertEqual(log.status_pulang, "tepat_waktu")

        record_attendance_event(other_teacher, method="qr_tv", now=at(7, 0))
        with self.assertRaisesMessage(AttendanceScheduleError, "dibuka pukul 12:00"):
            record_attendance_event(other_teacher, method="qr_tv", now=at(9, 0))
        log, event = record_attendance_event(other_teacher, method="qr_tv", now=at(12, 0))
        self.assertEqual(event, "pulang")
        self.assertEqual(log.status_pulang, "pulang_cepat")

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
        settings_obj = PengaturanWaktuPresensi.objects.get(pk=1)
        settings_obj.jam_mulai_pulang = time(12, 0)
        settings_obj.jam_pulang_normal = time(13, 40)
        settings_obj.save()
        today = timezone.localdate()
        local_timezone = timezone.get_current_timezone()
        arrival = timezone.make_aware(datetime.combine(today, time(7, 0)), local_timezone)
        departure = timezone.make_aware(datetime.combine(today, time(12, 0)), local_timezone)
        with patch("attendance.schedule.timezone.now", return_value=arrival):
            qr_response = self.client.post(reverse("teacher-qr"))
            self.assertEqual(qr_response.status_code, 200)
            self.assertIn("no-store", qr_response["Cache-Control"])
            response = self.client.post(reverse("kiosk-scan"), {"qr_payload": qr_response.json()["payload"]})
            self.assertEqual(response.status_code, 200)
            self.assertIn("berhasil", response.json()["message"])
            self.assertEqual(response.json()["event"], "masuk")
        with patch("attendance.schedule.timezone.now", return_value=departure):
            qr_response = self.client.post(reverse("teacher-qr"))
            response = self.client.post(reverse("kiosk-scan"), {"qr_payload": qr_response.json()["payload"]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["event"], "pulang")
        log = AbsensiLog.objects.get(guru=self.teacher)
        self.assertEqual(log.metode_scan, "qr_guru")
        self.assertEqual(log.status_pulang, "pulang_cepat")

    def test_kiosk_manual_allows_checkout_without_a_second_selfie(self):
        self.teacher.is_staff = True
        self.teacher.save(update_fields=("is_staff",))
        settings_obj = PengaturanWaktuPresensi.objects.get(pk=1)
        settings_obj.jam_mulai_pulang = time(12, 0)
        settings_obj.jam_pulang_normal = time(13, 40)
        settings_obj.save()
        today = timezone.localdate()
        local_timezone = timezone.get_current_timezone()
        arrival = timezone.make_aware(datetime.combine(today, time(7, 0)), local_timezone)
        departure = timezone.make_aware(datetime.combine(today, time(12, 0)), local_timezone)

        with patch("attendance.schedule.timezone.now", return_value=arrival):
            response = self.client.post(reverse("kiosk-manual"), {
                "nip": self.teacher.nip,
                "foto_selfie": self.make_image(),
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["event"], "masuk")

        with patch("attendance.schedule.timezone.now", return_value=departure):
            response = self.client.post(reverse("kiosk-manual"), {"nip": self.teacher.nip})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["event"], "pulang")
        log = AbsensiLog.objects.get(guru=self.teacher)
        self.assertEqual(log.status_pulang, "pulang_cepat")

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

    def test_teacher_history_shows_only_own_attendance_and_leave_and_replaces_monitor_link(self):
        another_teacher = UserGuru.objects.create_user(
            username="history-other", nip="198024", nama_lengkap="Guru Lain", email="history-other@example.test", password="HistoryTeacher!734",
        )
        AbsensiLog.objects.create(
            guru=self.teacher,
            waktu_masuk=timezone.now(),
            metode_scan="qr_tv",
            status="terlambat",
        )
        AbsensiLog.objects.create(
            guru=another_teacher,
            waktu_masuk=timezone.now(),
            metode_scan="qr_tv",
            status="hadir",
        )
        PengajuanIzin.objects.create(
            guru=self.teacher,
            jenis_izin="izin",
            tgl_mulai=timezone.localdate(),
            tgl_selesai=timezone.localdate(),
            alasan="Keperluan keluarga guru sendiri.",
            file_bukti=SimpleUploadedFile("history-own.pdf", b"%PDF-1.4 own"),
        )
        PengajuanIzin.objects.create(
            guru=another_teacher,
            jenis_izin="izin",
            tgl_mulai=timezone.localdate(),
            tgl_selesai=timezone.localdate(),
            alasan="Catatan rahasia guru lain.",
            file_bukti=SimpleUploadedFile("history-other.pdf", b"%PDF-1.4 other"),
        )

        response = self.client.get(reverse("teacher-history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Riwayat presensi")
        self.assertContains(response, "Riwayat izin")
        self.assertContains(response, "Terlambat")
        self.assertContains(response, "Keperluan keluarga guru sendiri.")
        self.assertContains(response, f'href="{reverse("teacher-history")}"')
        self.assertNotContains(response, "Catatan rahasia guru lain.")
        self.assertNotContains(response, reverse("school-qr-display"))
        self.assertNotContains(response, "Pindai untuk presensi")

    def test_non_teacher_cannot_open_teacher_history(self):
        kamad = UserGuru.objects.create_user(
            username="history-kamad", nip="900024", nama_lengkap="Kepala Madrasah", email="history-kamad@example.test", password="HistoryKamad!734", role="kamad"
        )
        self.client.force_login(kamad)

        self.assertEqual(self.client.get(reverse("teacher-history")).status_code, 403)

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
        leave_requests_page = self.client.get(reverse("leave-requests"))
        self.assertContains(leave_requests_page, "Unduh surat izin PDF")
        self.assertContains(leave_requests_page, "data-download-progress")
        teacher_history_page = self.client.get(reverse("teacher-history"))
        self.assertContains(teacher_history_page, "Unduh surat izin PDF")
        self.assertContains(teacher_history_page, "data-download-progress")
        letter = self.client.get(reverse("leave-letter", args=(leave.pk,)))
        self.assertEqual(letter.status_code, 200)
        self.assertEqual(letter["Content-Type"], "application/pdf")
        self.assertTrue(letter.content.startswith(b"%PDF"))

        another_teacher = UserGuru.objects.create_user(
            username="other-teacher", nip="198021", nama_lengkap="Guru Lain", email="other@example.test", password="StrongPass123!"
        )
        self.client.force_login(another_teacher)
        self.assertEqual(self.client.get(reverse("leave-letter", args=(leave.pk,))).status_code, 404)

    def test_teacher_submits_early_departure_request_without_evidence(self):
        departure_date = timezone.localdate() + timedelta(days=1)
        response = self.client.post(reverse("leave-requests"), {
            "jenis_izin": "pulang_awal",
            "tgl_mulai": departure_date.isoformat(),
            "tgl_selesai": departure_date.isoformat(),
            "jam_mulai_pulang_diminta": "08:45",
            "jam_pulang_diminta": "09:00",
            "alasan": "Keperluan keluarga yang mendesak.",
            "jadwal_pelajaran-TOTAL_FORMS": "0",
            "jadwal_pelajaran-INITIAL_FORMS": "0",
            "jadwal_pelajaran-MIN_NUM_FORMS": "0",
            "jadwal_pelajaran-MAX_NUM_FORMS": "20",
        })

        self.assertRedirects(response, reverse("leave-requests"))
        leave = PengajuanIzin.objects.get(guru=self.teacher, jenis_izin="pulang_awal")
        self.assertEqual(leave.status_approval, "pending")
        self.assertEqual(leave.jam_mulai_pulang_diminta, time(8, 45))
        self.assertEqual(leave.jam_pulang_diminta, time(9, 0))
        self.assertFalse(leave.file_bukti)

    def test_early_departure_request_requires_one_date_and_valid_times(self):
        departure_date = timezone.localdate() + timedelta(days=1)
        response = self.client.post(reverse("leave-requests"), {
            "jenis_izin": "pulang_awal",
            "tgl_mulai": departure_date.isoformat(),
            "tgl_selesai": (departure_date + timedelta(days=1)).isoformat(),
            "jam_mulai_pulang_diminta": "08:45",
            "jam_pulang_diminta": "09:00",
            "alasan": "Keperluan keluarga.",
            "jadwal_pelajaran-TOTAL_FORMS": "0",
            "jadwal_pelajaran-INITIAL_FORMS": "0",
            "jadwal_pelajaran-MIN_NUM_FORMS": "0",
            "jadwal_pelajaran-MAX_NUM_FORMS": "20",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PengajuanIzin.objects.filter(guru=self.teacher).count(), 0)
        self.assertContains(response, "hanya berlaku untuk satu tanggal")

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
        today = date(2026, 1, 15)
        for teacher, status in ((first_teacher, "hadir"), (second_teacher, "terlambat")):
            log = AbsensiLog.objects.create(
                guru=teacher,
                waktu_masuk=timezone.make_aware(datetime(2026, 1, 15, 7, 45)),
                waktu_pulang=timezone.make_aware(datetime(2026, 1, 15, 13, 35)),
                metode_scan="qr_tv",
                status=status,
            )
            log.tanggal = today
            log.save(update_fields=("tanggal",))
            if teacher == first_teacher:
                log.status_pulang = "pulang_cepat"
                log.save(update_fields=("status_pulang",))
        self.client.force_login(admin_user)
        params = {"bulan": today.month, "tahun": today.year, "guru": first_teacher.pk}
        preview = self.client.get(reverse("attendance-report"), params)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Ringkasan per guru")
        self.assertContains(preview, "data-download-progress")
        params["aksi"] = "xlsx"
        response = self.client.get(reverse("attendance-report"), params)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Disposition"].endswith(".xlsx\""))
        workbook = load_workbook(BytesIO(response.content))
        report = workbook["Laporan Guru 1"]
        self.assertEqual(report["B4"].value, f"PIN : {first_teacher.pk}")
        self.assertEqual(report["B5"].value, "NIK : 198030")
        self.assertEqual(report["I4"].value, ": Guru Rekap Satu")
        self.assertEqual(report["A8"].value, "Kamis,")
        self.assertEqual(report["B8"].value.date(), today.replace(day=1))
        self.assertEqual(report["F22"].value, time(7, 45))
        self.assertEqual(report["G22"].value, "15")
        self.assertEqual(report["I22"].value, time(13, 35))
        self.assertEqual(report["J22"].value, "25")
        self.assertEqual(report["A9"].value, "Jum'at,")
        self.assertEqual(report["A11"].value, "Minggu,")
        self.assertEqual(report["A9"].fill.fgColor.rgb, "FFFF00FF")
        self.assertNotEqual(report["A11"].fill.fgColor.rgb, "FFFF00FF")
        self.assertEqual(report["B38"].value.date(), date(2026, 1, 31))
        self.assertEqual(report["K38"].value, "=I38-F38")
        self.assertEqual(report["C39"].value, 1)
        self.assertEqual(report["K39"].value, "5.50")
        self.assertEqual(report["P40"].value, "Klaten, 31 Januari 2026")
        self.assertIn("C39:D39", [str(merged) for merged in report.merged_cells.ranges])
        summary = workbook["Rekap Per Guru"]
        self.assertEqual(summary.max_row, 2)
        self.assertEqual(summary["A2"].value, first_teacher.nip)
        self.assertEqual(summary["C2"].value, 1)
        self.assertEqual(summary["E2"].value, 1)
        self.assertEqual(workbook["Detail Absensi"].max_row, 2)
        self.assertEqual(workbook["Detail Absensi"]["H1"].value, "Status Pulang")

        params.pop("guru")
        all_teachers_response = self.client.get(reverse("attendance-report"), params)
        all_teachers_workbook = load_workbook(BytesIO(all_teachers_response.content))
        self.assertEqual(all_teachers_response.status_code, 200)
        self.assertCountEqual(
            (
                all_teachers_workbook["Laporan Guru 1"]["I4"].value,
                all_teachers_workbook["Laporan Guru 2"]["I4"].value,
            ),
            (": Guru Rekap Satu", ": Guru Rekap Dua"),
        )

    def test_teacher_cannot_open_admin_attendance_report(self):
        teacher = UserGuru.objects.create_user(
            username="report-guru", nip="198032", nama_lengkap="Guru", email="report-guru@example.test", password="StrongPass123!"
        )
        self.client.force_login(teacher)
        response = self.client.get(reverse("attendance-report"))
        self.assertEqual(response.status_code, 404)