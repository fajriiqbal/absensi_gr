from datetime import date, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import UserGuru
from attendance.models import JadwalPelajaranIzin, PengajuanIzin


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