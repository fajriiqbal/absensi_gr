from django.contrib import admin

from .models import AbsensiLog, JadwalPelajaranIzin, PengajuanIzin


@admin.register(AbsensiLog)
class AbsensiLogAdmin(admin.ModelAdmin):
    list_display = ("guru", "tanggal", "waktu_masuk", "waktu_pulang", "metode_scan", "status", "status_pulang")
    list_filter = ("tanggal", "metode_scan", "status", "status_pulang")
    search_fields = ("guru__nama_lengkap", "guru__nip")


class JadwalPelajaranIzinInline(admin.TabularInline):
    model = JadwalPelajaranIzin
    extra = 0


@admin.register(PengajuanIzin)
class PengajuanIzinAdmin(admin.ModelAdmin):
    list_display = ("guru", "jenis_izin", "tgl_mulai", "tgl_selesai", "status_approval")
    list_filter = ("status_approval", "jenis_izin")
    search_fields = ("guru__nama_lengkap", "guru__nip")
    inlines = [JadwalPelajaranIzinInline]