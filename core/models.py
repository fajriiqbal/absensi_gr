import uuid
from datetime import time, datetime

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models


class LokasiSekolah(models.Model):
    nama_lokasi = models.CharField(max_length=100, default="Gedung MTs Utama")
    latitude = models.DecimalField(max_digits=11, decimal_places=8)
    longitude = models.DecimalField(max_digits=11, decimal_places=8)
    radius_toleransi_meter = models.PositiveIntegerField(default=50)

    def __str__(self):
        return self.nama_lokasi


class TitikQRCetak(models.Model):
    kode_lokasi = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    label_titik = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.label_titik


class WhatsAppSettings(models.Model):
    kamad_phone_number = models.CharField(max_length=20, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pengaturan WhatsApp"
        verbose_name_plural = "Pengaturan WhatsApp"

    @classmethod
    def get_settings(cls):
        settings_obj, _ = cls.objects.get_or_create(pk=1)
        return settings_obj

    def __str__(self):
        return "Pengaturan notifikasi WhatsApp"


class PengaturanWaktuPresensi(models.Model):
    jam_mulai_masuk = models.TimeField(default=time(5, 0), verbose_name="Presensi masuk dibuka")
    batas_terlambat = models.TimeField(default=time(7, 30), verbose_name="Batas waktu tepat waktu")
    jam_mulai_pulang = models.TimeField(default=time(12, 0), verbose_name="Presensi pulang dibuka")
    jam_pulang_normal = models.TimeField(default=time(13, 40), verbose_name="Jam pulang normal")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pengaturan waktu presensi"
        verbose_name_plural = "Pengaturan waktu presensi"

    def clean(self):
        super().clean()
        if self.jam_mulai_masuk and self.batas_terlambat and self.jam_mulai_masuk >= self.batas_terlambat:
            raise ValidationError({"batas_terlambat": "Batas terlambat harus setelah waktu presensi masuk dibuka."})
        if self.batas_terlambat and self.jam_mulai_pulang and self.batas_terlambat >= self.jam_mulai_pulang:
            raise ValidationError({"jam_mulai_pulang": "Presensi pulang harus dibuka setelah batas waktu masuk."})
        if self.jam_mulai_pulang and self.jam_pulang_normal and self.jam_mulai_pulang >= self.jam_pulang_normal:
            raise ValidationError({"jam_pulang_normal": "Jam pulang normal harus setelah waktu presensi pulang dibuka."})

    @classmethod
    def get_settings(cls):
        try:
            late_after = datetime.strptime(
                getattr(settings, "ATTENDANCE_LATE_AFTER", "07:30"), "%H:%M"
            ).time()
        except ValueError as exc:
            raise ImproperlyConfigured("ATTENDANCE_LATE_AFTER harus berformat HH:MM.") from exc
        instance, _ = cls.objects.get_or_create(
            pk=1,
            defaults={"batas_terlambat": late_after},
        )
        return instance

    def __str__(self):
        return "Pengaturan waktu presensi sekolah"


class JadwalWaktuPresensiMingguan(models.Model):
    HARI_CHOICES = (
        (0, "Senin"),
        (1, "Selasa"),
        (2, "Rabu"),
        (3, "Kamis"),
        (4, "Jumat"),
        (5, "Sabtu"),
        (6, "Minggu"),
    )

    hari = models.PositiveSmallIntegerField(choices=HARI_CHOICES, unique=True, verbose_name="Hari")
    jam_mulai_pulang = models.TimeField(verbose_name="Presensi pulang dibuka")
    jam_pulang = models.TimeField(verbose_name="Jam pulang")

    class Meta:
        ordering = ("hari",)
        verbose_name = "Jadwal waktu presensi mingguan"
        verbose_name_plural = "Jadwal waktu presensi mingguan"

    def clean(self):
        super().clean()
        if self.jam_mulai_pulang and self.jam_pulang and self.jam_mulai_pulang >= self.jam_pulang:
            raise ValidationError({"jam_pulang": "Jam pulang harus setelah presensi pulang dibuka."})

    def __str__(self):
        return f"{self.get_hari_display()} - Pulang {self.jam_pulang:%H:%M}"


class JadwalWaktuPresensiKhusus(models.Model):
    tanggal = models.DateField(unique=True)
    jam_mulai_pulang = models.TimeField(verbose_name="Presensi pulang dibuka")
    jam_pulang = models.TimeField(verbose_name="Jam pulang khusus")
    keterangan = models.CharField(max_length=200, verbose_name="Keterangan")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("tanggal",)
        verbose_name = "Jadwal waktu presensi khusus"
        verbose_name_plural = "Jadwal waktu presensi khusus"

    def clean(self):
        super().clean()
        if self.jam_mulai_pulang and self.jam_pulang and self.jam_mulai_pulang >= self.jam_pulang:
            raise ValidationError({"jam_pulang": "Jam pulang khusus harus setelah presensi pulang dibuka."})

    def __str__(self):
        return f"{self.tanggal:%d-%m-%Y} - Pulang {self.jam_pulang:%H:%M}"