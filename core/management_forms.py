from django import forms
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from attendance.forms import JadwalPelajaranIzinFormSetFactory
from attendance.models import AbsensiLog, PengajuanIzin

from .models import JadwalWaktuPresensiKhusus, LokasiSekolah, PengaturanWaktuPresensi, TitikQRCetak


UserGuru = get_user_model()


class UserGuruManagementForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Kata sandi",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "field", "autocomplete": "new-password"}),
        required=False,
    )
    password2 = forms.CharField(
        label="Ulangi kata sandi",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "field", "autocomplete": "new-password"}),
        required=False,
    )

    class Meta:
        model = UserGuru
        fields = (
            "username",
            "nip",
            "nama_lengkap",
            "email",
            "role",
            "foto_profil",
            "is_active",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
        )
        widgets = {
            "username": forms.TextInput(attrs={"class": "field"}),
            "nip": forms.TextInput(attrs={"class": "field"}),
            "nama_lengkap": forms.TextInput(attrs={"class": "field"}),
            "email": forms.EmailInput(attrs={"class": "field"}),
            "role": forms.Select(attrs={"class": "field"}),
            "foto_profil": forms.ClearableFileInput(attrs={"class": "field"}),
            "groups": forms.SelectMultiple(attrs={"class": "field", "size": 6}),
            "user_permissions": forms.SelectMultiple(attrs={"class": "field", "size": 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        creating = self.instance._state.adding
        self.fields["password1"].required = creating
        self.fields["password2"].required = creating
        self.fields["password1"].help_text = (
            "Wajib diisi untuk akun baru. Kosongkan saat mengubah akun jika kata sandi tidak diganti."
        )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "Kata sandi tidak sama.")
            else:
                try:
                    validate_password(password1, self.instance)
                except forms.ValidationError as exc:
                    self.add_error("password1", exc)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
        elif user._state.adding:
            raise ValueError("Akun baru harus memiliki kata sandi.")
        if commit:
            user.save()
            self.save_m2m()
        return user


class AbsensiLogManagementForm(forms.ModelForm):
    class Meta:
        model = AbsensiLog
        fields = (
            "guru",
            "waktu_masuk",
            "waktu_pulang",
            "lat_masuk",
            "long_masuk",
            "foto_masuk",
            "metode_scan",
            "status",
            "status_pulang",
            "catatan",
        )
        widgets = {
            "guru": forms.Select(attrs={"class": "field"}),
            "waktu_masuk": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"class": "field", "type": "datetime-local"}),
            "waktu_pulang": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"class": "field", "type": "datetime-local"}),
            "lat_masuk": forms.NumberInput(attrs={"class": "field", "step": "any"}),
            "long_masuk": forms.NumberInput(attrs={"class": "field", "step": "any"}),
            "foto_masuk": forms.FileInput(attrs={"class": "field"}),
            "metode_scan": forms.Select(attrs={"class": "field"}),
            "status": forms.Select(attrs={"class": "field"}),
            "status_pulang": forms.Select(attrs={"class": "field"}),
            "catatan": forms.Textarea(attrs={"class": "field", "rows": 3}),
        }
        help_texts = {
            "foto_masuk": "Opsional. Berkas lama tetap tersimpan jika tidak ada foto baru yang diunggah.",
            "status": "Status presensi masuk.",
            "status_pulang": "Status pulang dikosongkan jika guru belum mencatat presensi pulang.",
        }


class PengajuanIzinManagementForm(forms.ModelForm):
    class Meta:
        model = PengajuanIzin
        fields = (
            "guru",
            "jenis_izin",
            "tgl_mulai",
            "tgl_selesai",
            "alasan",
            "file_bukti",
            "status_approval",
            "approved_by",
            "approved_at",
            "catatan_kamad",
        )
        widgets = {
            "guru": forms.Select(attrs={"class": "field"}),
            "jenis_izin": forms.Select(attrs={"class": "field"}),
            "tgl_mulai": forms.DateInput(attrs={"class": "field", "type": "date"}),
            "tgl_selesai": forms.DateInput(attrs={"class": "field", "type": "date"}),
            "alasan": forms.Textarea(attrs={"class": "field", "rows": 4}),
            "file_bukti": forms.FileInput(attrs={"class": "field", "accept": ".pdf,.jpg,.jpeg,.png"}),
            "status_approval": forms.Select(attrs={"class": "field"}),
            "approved_by": forms.Select(attrs={"class": "field"}),
            "approved_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"class": "field", "type": "datetime-local"}),
            "catatan_kamad": forms.Textarea(attrs={"class": "field", "rows": 3}),
        }
        help_texts = {
            "file_bukti": "Berkas lama tetap tersimpan jika tidak ada bukti baru yang diunggah.",
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("tgl_mulai")
        end = cleaned_data.get("tgl_selesai")
        if start and end and end < start:
            self.add_error("tgl_selesai", "Tanggal selesai tidak boleh sebelum tanggal mulai.")
        return cleaned_data


class LokasiSekolahManagementForm(forms.ModelForm):
    class Meta:
        model = LokasiSekolah
        fields = ("nama_lokasi", "latitude", "longitude", "radius_toleransi_meter")
        widgets = {
            "nama_lokasi": forms.TextInput(attrs={"class": "field"}),
            "latitude": forms.NumberInput(attrs={"class": "field", "step": "any"}),
            "longitude": forms.NumberInput(attrs={"class": "field", "step": "any"}),
            "radius_toleransi_meter": forms.NumberInput(attrs={"class": "field", "min": 1}),
        }


class TitikQRCetakManagementForm(forms.ModelForm):
    class Meta:
        model = TitikQRCetak
        fields = ("label_titik", "is_active")
        widgets = {
            "label_titik": forms.TextInput(attrs={"class": "field"}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4"}),
        }


class PengaturanWaktuPresensiForm(forms.ModelForm):
    class Meta:
        model = PengaturanWaktuPresensi
        fields = ("jam_mulai_masuk", "batas_terlambat", "jam_mulai_pulang", "jam_pulang_normal")
        widgets = {
            "jam_mulai_masuk": forms.TimeInput(format="%H:%M", attrs={"class": "field", "type": "time"}),
            "batas_terlambat": forms.TimeInput(format="%H:%M", attrs={"class": "field", "type": "time"}),
            "jam_mulai_pulang": forms.TimeInput(format="%H:%M", attrs={"class": "field", "type": "time"}),
            "jam_pulang_normal": forms.TimeInput(format="%H:%M", attrs={"class": "field", "type": "time"}),
        }


class JadwalWaktuPresensiKhususForm(forms.ModelForm):
    class Meta:
        model = JadwalWaktuPresensiKhusus
        fields = ("tanggal", "jam_mulai_pulang", "jam_pulang", "keterangan")
        widgets = {
            "tanggal": forms.DateInput(attrs={"class": "field", "type": "date"}),
            "jam_mulai_pulang": forms.TimeInput(format="%H:%M", attrs={"class": "field", "type": "time"}),
            "jam_pulang": forms.TimeInput(format="%H:%M", attrs={"class": "field", "type": "time"}),
            "keterangan": forms.TextInput(attrs={"class": "field", "maxlength": 200}),
        }

    def clean_tanggal(self):
        tanggal = self.cleaned_data["tanggal"]
        if tanggal < timezone.localdate():
            raise forms.ValidationError("Jadwal pulang khusus hanya dapat dibuat untuk hari ini atau tanggal mendatang.")
        return tanggal

    def clean(self):
        cleaned_data = super().clean()
        checkout_start = cleaned_data.get("jam_mulai_pulang")
        if checkout_start and checkout_start <= PengaturanWaktuPresensi.get_settings().batas_terlambat:
            self.add_error("jam_mulai_pulang", "Presensi pulang khusus harus dibuka setelah batas waktu tepat waktu.")
        return cleaned_data


class GroupManagementForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ("name", "permissions")
        widgets = {
            "name": forms.TextInput(attrs={"class": "field"}),
            "permissions": forms.SelectMultiple(attrs={"class": "field", "size": 12}),
        }


JadwalPelajaranIzinManagementFormSet = JadwalPelajaranIzinFormSetFactory
