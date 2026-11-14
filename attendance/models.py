from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.storage import encrypted_private_storage


class AbsensiLog(models.Model):
    METODE_CHOICES = (
        ("qr_tv", "HP Guru Scan Dynamic QR TV"),
        ("qr_cetak", "HP Guru Scan Poster QR Cetak"),
        ("qr_guru", "Tablet Kiosk Scan QR HP Guru"),
        ("manual_kiosk", "Manual Input Kiosk Darurat"),
        ("izin_telat", "Otomatis dari Izin Datang Terlambat"),
    )
    STATUS_CHOICES = (
        ("hadir", "Hadir Tepat Waktu"),
        ("terlambat", "Terlambat"),
        ("pulang_cepat", "Pulang Lebih Awal"),
    )
    STATUS_PULANG_CHOICES = (
        ("tepat_waktu", "Tidak Pulang Cepat"),
        ("pulang_cepat", "Pulang Lebih Awal"),
    )

    guru = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="absensilogs")
    tanggal = models.DateField(auto_now_add=True, db_index=True)
    waktu_masuk = models.DateTimeField(null=True, blank=True)
    waktu_pulang = models.DateTimeField(null=True, blank=True)
    lat_masuk = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    long_masuk = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    foto_masuk = models.ImageField(upload_to="attendance_photos/", storage=encrypted_private_storage, null=True, blank=True)
    metode_scan = models.CharField(max_length=20, choices=METODE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="hadir")
    status_pulang = models.CharField(max_length=20, choices=STATUS_PULANG_CHOICES, blank=True)
    catatan = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ("-waktu_masuk",)
        constraints = [models.UniqueConstraint(fields=("guru", "tanggal"), name="one_attendance_per_guru_day")]

    def __str__(self):
        return f"{self.guru.nama_lengkap} - {self.tanggal}"


class PengajuanIzin(models.Model):
    JENIS_CHOICES = (
        ("sakit", "Sakit"),
        ("izin", "Izin Personal"),
        ("dinas_luar", "Dinas Luar"),
        ("cuti", "Cuti"),
        ("datang_terlambat", "Izin Datang Terlambat"),
        ("pulang_awal", "Izin Pulang Lebih Awal"),
    )
    APPROVAL_CHOICES = (
        ("pending", "Menunggu Persetujuan"),
        ("disetujui", "Disetujui"),
        ("ditolak", "Ditolak"),
    )

    guru = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    jenis_izin = models.CharField(max_length=20, choices=JENIS_CHOICES)
    tgl_mulai = models.DateField()
    tgl_selesai = models.DateField()
    jam_datang_diminta = models.TimeField(null=True, blank=True)
    jam_mulai_pulang_diminta = models.TimeField(null=True, blank=True)
    jam_pulang_diminta = models.TimeField(null=True, blank=True)
    alasan = models.TextField()
    tugas_kelas = models.TextField(blank=True)
    file_bukti = models.FileField(upload_to="dokumen_izin/", storage=encrypted_private_storage, blank=True)
    status_approval = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default="pending")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approvals")
    approved_at = models.DateTimeField(null=True, blank=True)
    catatan_kamad = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [models.CheckConstraint(check=Q(tgl_selesai__gte=models.F("tgl_mulai")), name="leave_end_on_or_after_start")]

    def clean(self):
        super().clean()
        if self.tgl_mulai and self.tgl_selesai and self.tgl_selesai < self.tgl_mulai:
            raise ValidationError({"tgl_selesai": "Tanggal selesai tidak boleh sebelum tanggal mulai."})
        if self.jenis_izin == "pulang_awal":
            errors = {}
            if self.tgl_mulai and self.tgl_selesai and self.tgl_mulai != self.tgl_selesai:
                errors["tgl_selesai"] = "Izin pulang lebih awal hanya berlaku untuk satu tanggal."
            if not self.jam_pulang_diminta:
                errors["jam_pulang_diminta"] = "Jam pulang yang diminta wajib diisi."
            if errors:
                raise ValidationError(errors)
        if self.jenis_izin == "datang_terlambat":
            errors = {}
            if self.tgl_mulai and self.tgl_selesai and self.tgl_mulai != self.tgl_selesai:
                errors["tgl_selesai"] = "Izin datang terlambat hanya berlaku untuk satu tanggal."
            if not self.jam_datang_diminta:
                errors["jam_datang_diminta"] = "Jam datang yang diminta wajib diisi."
            if errors:
                raise ValidationError(errors)

    def __str__(self):
        return f"{self.guru.nama_lengkap} - {self.get_jenis_izin_display()}"


class JadwalPelajaranIzin(models.Model):
    HARI_CHOICES = (
        ("senin", "Senin"),
        ("selasa", "Selasa"),
        ("rabu", "Rabu"),
        ("kamis", "Kamis"),
        ("jumat", "Jumat"),
        ("sabtu", "Sabtu"),
        ("minggu", "Minggu"),
    )

    pengajuan = models.ForeignKey(PengajuanIzin, on_delete=models.CASCADE, related_name="jadwal_pelajaran")
    hari = models.CharField(max_length=10, choices=HARI_CHOICES)
    tanggal = models.DateField()
    mapel_diampu = models.CharField(max_length=100)
    jam_pelajaran_diampu = models.CharField(max_length=50)
    mapel_lukiran = models.CharField(max_length=100)
    jam_lukiran = models.CharField(max_length=50)
    keterangan_kelas = models.CharField(max_length=100, default="")
    guru_lukiran = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jadwal_lukiran",
        limit_choices_to={"role": "guru"},
    )

    class Meta:
        ordering = ("tanggal", "jam_pelajaran_diampu", "pk")
        verbose_name = "Jadwal Pelajaran Izin"
        verbose_name_plural = "Jadwal Pelajaran Izin"

    def clean(self):
        super().clean()
        if not self.tanggal or not self.hari:
            return
        expected_day = self.HARI_CHOICES[self.tanggal.weekday()][0]
        if self.hari != expected_day:
            raise ValidationError({"hari": "Hari tidak sesuai dengan tanggal yang dipilih."})
        if self.pengajuan_id and self.pengajuan.tgl_mulai and self.pengajuan.tgl_selesai:
            if not self.pengajuan.tgl_mulai <= self.tanggal <= self.pengajuan.tgl_selesai:
                raise ValidationError({"tanggal": "Tanggal jadwal harus berada dalam rentang tanggal izin."})

    def __str__(self):
        return f"{self.get_hari_display()}, {self.tanggal}: {self.mapel_diampu} ({self.jam_pelajaran_diampu})"