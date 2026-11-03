from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import UserGuru


@admin.register(UserGuru)
class UserGuruAdmin(UserAdmin):
    model = UserGuru
    list_display = ("nip", "nama_lengkap", "role", "is_active", "is_staff")
    search_fields = ("nip", "nama_lengkap", "email")
    fieldsets = UserAdmin.fieldsets + (("Data sekolah", {"fields": ("nip", "nama_lengkap", "role", "foto_profil")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Data sekolah", {"fields": ("nip", "nama_lengkap", "email", "role")}),)