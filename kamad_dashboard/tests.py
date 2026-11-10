from datetime import date, time, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import UserGuru
from attendance.models import AbsensiLog, JadwalPelajaranIzin, PengajuanIzin
from core.models import JadwalWaktuPresensiGuru


class DashboardTests(TestCase):
    def test_live_feed_lists_active_teachers_without_today_attendance(self):
        kamad = UserGuru.objects.create_user(
            username="dashboard-live-kamad",
            nip="900010",
            nama_lengkap="Kamad Live",
            email="dashboard-live-kamad@example.test",
            password="test-password-123",
            role="kamad",
        )
        present_teacher = UserGuru.objects.create_user(
            username="dashboard-present-teacher",
            nip="900011",
            nama_lengkap="Guru Sudah Absen",
            email="dashboard-present@example.test",
            password="test-password-123",
        )
        missing_teacher = UserGuru.objects.create_user(
            username="dashboard-missing-teacher",
            nip="900012",
            nama_lengkap="Guru Belum Absen",
            email="dashboard-missing@example.test",
            password="test-password-123",
        )
        inactive_teacher = UserGuru.objects.create_user(
            username="dashboard-inactive-teacher",
            nip="900013",
            nama_lengkap="Guru Nonaktif",
            email="dashboard-inactive@example.test",
            password="test-password-123",
            is_active=False,
        )
        AbsensiLog.objects.create(
            guru=present_teacher,
            tanggal=timezone.localdate(),
            metode_scan="qr_tv",
        )
        self.client.force_login(kamad)

        response = self.client.get(reverse("kamad-live-feed"))

        self.assertEqual(response.status_code, 200)
        missing_teachers = response.json()["belum_absen"]
        self.assertEqual(missing_teachers, [{"nama": missing_teacher.nama_lengkap, "nip": missing_teacher.nip}])
        self.assertNotIn(present_teacher.nama_lengkap, [teacher["nama"] for teacher in missing_teachers])
        self.assertNotIn(inactive_teacher.nama_lengkap, [teacher["nama"] for teacher in missing_teachers])

    def test_kamad_dashboard_displays_missing_attendance_table(self):
        kamad = UserGuru.objects.create_user(
            username="dashboard-table-kamad",
            nip="900014",
            nama_lengkap="Kamad Tabel",
            email="dashboard-table-kamad@example.test",
            password="test-password-123",
            role="kamad",
        )
        self.client.force_login(kamad)

        response = self.client.get(reverse("kamad-dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Guru belum absen hari ini")
        self.assertContains(response, "Semua guru aktif sudah tercatat absen hari ini.")


class ApprovalTests(TestCase):
    def test_kamad_can_approve_pending_leave(self):
        media_dir = TemporaryDirectory()
        self.addCleanup(media_dir.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=media_dir.name, MEDIA_ENCRYPTION_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="))
        proof_storage = PengajuanIzin._meta.get_field("file_bukti").storage
        original_location = proof_storage.location
        proof_storage.location = media_dir.name
        self.addCleanup(setattr, proof_storage, "location", original_location)
        kamad = UserGuru.objects.create_user(
            username="kamad", nip="900001", nama_lengkap="Kepala", email="kamad@example.test", password="StrongPass123!", role="kamad"
        )
        teacher = UserGuru.objects.create_user(
            username="guru", nip="900002", nama_lengkap="Guru", email="guru@example.test", password="StrongPass123!"
        )
        leave = PengajuanIzin.objects.create(
            guru=teacher,
            jenis_izin="sakit",
            tgl_mulai=date.today(),
            tgl_selesai=date.today() + timedelta(days=1),
            alasan="Sakit",
            file_bukti=SimpleUploadedFile("bukti.txt", b"dokumen-rahasia"),
        )
        self.client.force_login(kamad)
        with open(leave.file_bukti.path, "rb") as stored_file:
            self.assertNotEqual(stored_file.read(), b"dokumen-rahasia")
        evidence = self.client.get(reverse("private-leave-document", args=(leave.pk,)))
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(b"".join(evidence.streaming_content), b"dokumen-rahasia")
        response = self.client.post(reverse("approve-leave", args=(leave.pk,)), {"decision": "disetujui"})
        self.assertEqual(response.status_code, 200)
        leave.refresh_from_db()
        self.assertEqual(leave.status_approval, "disetujui")
        self.assertEqual(leave.approved_by, kamad)

    def test_kamad_and_tu_can_approve_early_departure_requests(self):
        kamad = UserGuru.objects.create_user(
            username="early-leave-kamad",
            nip="900003",
            nama_lengkap="Kepala",
            email="early-kamad@example.test",
            password="test-password-123",
            role="kamad",
        )
        operator = UserGuru.objects.create_user(
            username="early-leave-operator",
            nip="900004",
            nama_lengkap="Tata Usaha",
            email="early-tu@example.test",
            password="test-password-123",
            is_staff=True,
        )
        teacher = UserGuru.objects.create_user(
            username="early-leave-teacher",
            nip="900005",
            nama_lengkap="Guru",
            email="early-teacher@example.test",
            password="test-password-123",
        )
        other_teacher = UserGuru.objects.create_user(
            username="early-leave-other",
            nip="900006",
            nama_lengkap="Guru Lain",
            email="early-other@example.test",
            password="test-password-123",
        )
        departure_date = timezone.localdate() + timedelta(days=1)

        def create_request(guru, start, departure):
            return PengajuanIzin.objects.create(
                guru=guru,
                jenis_izin="pulang_awal",
                tgl_mulai=departure_date,
                tgl_selesai=departure_date,
                jam_mulai_pulang_diminta=start,
                jam_pulang_diminta=departure,
                alasan="Keperluan keluarga.",
            )

        tu_request = create_request(teacher, time(8, 45), time(9, 0))
        kamad_request = create_request(other_teacher, time(10, 45), time(11, 0))

        self.client.force_login(operator)
        queue = self.client.get(reverse("leave-approvals"))
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, teacher.nama_lengkap)
        self.assertContains(queue, other_teacher.nama_lengkap)
        response = self.client.post(reverse("approve-leave", args=(tu_request.pk,)), {"decision": "disetujui"})
        self.assertEqual(response.status_code, 200)
        tu_request.refresh_from_db()
        self.assertEqual(tu_request.approved_by, operator)
        self.assertEqual(
            JadwalWaktuPresensiGuru.objects.get(guru=teacher, tanggal=departure_date).jam_pulang,
            time(9, 0),
        )

        self.client.force_login(kamad)
        response = self.client.post(reverse("approve-leave", args=(kamad_request.pk,)), {"decision": "disetujui"})
        self.assertEqual(response.status_code, 200)
        kamad_request.refresh_from_db()
        self.assertEqual(kamad_request.approved_by, kamad)
        self.assertEqual(
            JadwalWaktuPresensiGuru.objects.get(guru=other_teacher, tanggal=departure_date).jam_pulang,
            time(11, 0),
        )

    def test_operator_cannot_approve_regular_leave(self):
        operator = UserGuru.objects.create_user(
            username="regular-leave-operator",
            nip="900007",
            nama_lengkap="TU",
            email="regular-tu@example.test",
            password="test-password-123",
            is_staff=True,
        )
        teacher = UserGuru.objects.create_user(
            username="regular-leave-teacher",
            nip="900008",
            nama_lengkap="Guru",
            email="regular-teacher@example.test",
            password="test-password-123",
        )
        leave = PengajuanIzin.objects.create(
            guru=teacher,
            jenis_izin="izin",
            tgl_mulai=timezone.localdate(),
            tgl_selesai=timezone.localdate(),
            alasan="Keperluan.",
            file_bukti="bukti.pdf",
        )
        self.client.force_login(operator)

        response = self.client.post(reverse("approve-leave", args=(leave.pk,)), {"decision": "disetujui"})

        self.assertEqual(response.status_code, 403)
        leave.refresh_from_db()
        self.assertEqual(leave.status_approval, "pending")

    def test_teacher_cannot_open_approval_queue(self):
        teacher = UserGuru.objects.create_user(
            username="approval-queue-teacher",
            nip="900009",
            nama_lengkap="Guru",
            email="approval-teacher@example.test",
            password="test-password-123",
        )
        self.client.force_login(teacher)

        self.assertEqual(self.client.get(reverse("leave-approvals")).status_code, 404)


class LeaveReportTests(TestCase):
    def test_kamad_exports_monthly_leave_history_and_summary(self):
        media_dir = TemporaryDirectory()
        self.addCleanup(media_dir.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=media_dir.name, MEDIA_ENCRYPTION_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="))
        proof_storage = PengajuanIzin._meta.get_field("file_bukti").storage
        original_location = proof_storage.location
        proof_storage.location = media_dir.name
        self.addCleanup(setattr, proof_storage, "location", original_location)
        kamad = UserGuru.objects.create_user(
            username="leave-report-kamad", nip="900040", nama_lengkap="Kamad Rekap", email="leave-report-kamad@example.test", password="StrongPass123!", role="kamad"
        )
        teacher = UserGuru.objects.create_user(
            username="leave-report-guru", nip="198040", nama_lengkap="Guru Rekap", email="leave-report-guru@example.test", password="StrongPass123!"
        )
        leave = PengajuanIzin.objects.create(
            guru=teacher,
            jenis_izin="sakit",
            tgl_mulai=date.today(),
            tgl_selesai=date.today(),
            alasan="Sakit",
            file_bukti=SimpleUploadedFile("bukti.pdf", b"%PDF bukti", content_type="application/pdf"),
        )
        JadwalPelajaranIzin.objects.create(
            pengajuan=leave,
            hari="senin",
            tanggal=date(2026, 10, 19),
            mapel_diampu="IPA",
            jam_pelajaran_diampu="Jam ke-1",
            mapel_lukiran="Matematika",
            jam_lukiran="Jam ke-2",
            keterangan_kelas="VII-A",
            guru_lukiran=UserGuru.objects.create_user(
                username="leave-report-buddy", nip="198042", nama_lengkap="Guru Rekan", email="leave-report-buddy@example.test", password="StrongPass123!"
            ),
        )
        self.client.force_login(kamad)
        today = timezone.localdate()
        params = {"bulan": today.month, "tahun": today.year}
        preview = self.client.get(reverse("leave-report"), params)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Histori perizinan bulanan")
        self.assertContains(preview, "data-download-progress")
        params["aksi"] = "xlsx"
        response = self.client.get(reverse("leave-report"), params)
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(workbook["Ringkasan"]["B2"].value, 1)
        self.assertEqual(workbook["Ringkasan"]["B5"].value, 1)
        self.assertEqual(workbook["Histori Perizinan"].max_row, 2)
        self.assertEqual(workbook["Rincian Jam Lukiran"].max_row, 2)
        self.assertEqual(workbook["Rincian Jam Lukiran"]["F2"].value, "IPA")
        self.assertEqual(workbook["Rincian Jam Lukiran"]["J2"].value, "VII-A")

    def test_teacher_cannot_open_kamad_leave_report(self):
        teacher = UserGuru.objects.create_user(
            username="leave-report-unauthorized", nip="198041", nama_lengkap="Guru", email="leave-report-unauth@example.test", password="StrongPass123!"
        )
        self.client.force_login(teacher)
        self.assertEqual(self.client.get(reverse("leave-report")).status_code, 404)