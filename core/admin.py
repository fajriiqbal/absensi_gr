from django.contrib import admin

from .models import LokasiSekolah, TitikQRCetak, WhatsAppSettings


@admin.register(LokasiSekolah)
class LokasiSekolahAdmin(admin.ModelAdmin):
    list_display = ("nama_lokasi", "latitude", "longitude", "radius_toleransi_meter")


@admin.register(TitikQRCetak)
class TitikQRCetakAdmin(admin.ModelAdmin):
    list_display = ("label_titik", "kode_lokasi", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("label_titik", "kode_lokasi")


@admin.register(WhatsAppSettings)
class WhatsAppSettingsAdmin(admin.ModelAdmin):
    list_display = ("sender_phone_number", "kamad_phone_number", "template_name", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not WhatsAppSettings.objects.exists()