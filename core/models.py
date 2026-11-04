import uuid

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
    sender_phone_number_id = models.CharField(max_length=32, blank=True)
    sender_phone_number = models.CharField(max_length=20, blank=True)
    kamad_phone_number = models.CharField(max_length=20, blank=True)
    template_name = models.CharField(max_length=100, default="notifikasi_pengajuan_izin")
    template_language = models.CharField(max_length=20, default="id")
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