from django.contrib import admin

from .models import LokasiSekolah, TitikQRCetak


@admin.register(LokasiSekolah)
class LokasiSekolahAdmin(admin.ModelAdmin):
    list_display = ("nama_lokasi", "latitude", "longitude", "radius_toleransi_meter")


@admin.register(TitikQRCetak)
class TitikQRCetakAdmin(admin.ModelAdmin):
    list_display = ("label_titik", "kode_lokasi", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("label_titik", "kode_lokasi")