import re

from django import forms

from .models import WhatsAppSettings


def normalize_phone_number(value):
    value = re.sub(r"[\s()-]", "", value)
    if value.startswith("00"):
        value = f"+{value[2:]}"
    elif value.startswith("0"):
        value = f"+62{value[1:]}"
    elif value.startswith("62"):
        value = f"+{value}"
    if not re.fullmatch(r"\+[1-9]\d{7,14}", value):
        raise forms.ValidationError("Gunakan nomor internasional, contoh +6281234567890.")
    return value


class WhatsAppSettingsForm(forms.ModelForm):
    class Meta:
        model = WhatsAppSettings
        fields = (
            "sender_phone_number_id",
            "sender_phone_number",
            "kamad_phone_number",
            "template_name",
            "template_language",
        )
        labels = {
            "sender_phone_number_id": "Phone Number ID Meta",
            "sender_phone_number": "Nomor WhatsApp pengirim",
            "kamad_phone_number": "Nomor WhatsApp Kamad",
            "template_name": "Nama template pesan",
            "template_language": "Kode bahasa template",
        }
        help_texts = {
            "sender_phone_number_id": "ID dari WhatsApp Manager, bukan nomor telepon. Contoh: 123456789012345.",
            "sender_phone_number": "Nomor bisnis terdaftar pada Cloud API, dalam format internasional.",
            "kamad_phone_number": "Nomor penerima notifikasi. Nomor lokal yang diawali 0 otomatis diubah ke +62.",
            "template_name": "Nama template Utility yang sudah disetujui di WhatsApp Manager.",
            "template_language": "Kode bahasa yang dipakai saat template disetujui Meta, contoh id atau id_ID.",
        }
        widgets = {
            "sender_phone_number_id": forms.TextInput(attrs={"class": "field", "inputmode": "numeric"}),
            "sender_phone_number": forms.TextInput(attrs={"class": "field", "placeholder": "+6281234567890", "inputmode": "tel"}),
            "kamad_phone_number": forms.TextInput(attrs={"class": "field", "placeholder": "+6281234567890", "inputmode": "tel"}),
            "template_name": forms.TextInput(attrs={"class": "field", "placeholder": "notifikasi_pengajuan_izin"}),
            "template_language": forms.TextInput(attrs={"class": "field", "placeholder": "id"}),
        }

    def clean_sender_phone_number_id(self):
        phone_number_id = self.cleaned_data["sender_phone_number_id"].strip()
        if phone_number_id and not phone_number_id.isdigit():
            raise forms.ValidationError("Phone Number ID harus berupa angka dari WhatsApp Manager.")
        return phone_number_id

    def clean_sender_phone_number(self):
        value = self.cleaned_data["sender_phone_number"].strip()
        return normalize_phone_number(value) if value else ""

    def clean_kamad_phone_number(self):
        value = self.cleaned_data["kamad_phone_number"].strip()
        return normalize_phone_number(value) if value else ""

    def clean_template_name(self):
        value = self.cleaned_data["template_name"].strip()
        if not re.fullmatch(r"[a-z0-9_]{1,100}", value):
            raise forms.ValidationError("Nama template harus huruf kecil, angka, atau garis bawah.")
        return value

    def clean_template_language(self):
        value = self.cleaned_data["template_language"].strip()
        if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", value):
            raise forms.ValidationError("Masukkan kode bahasa template, contoh id atau id_ID.")
        return value
