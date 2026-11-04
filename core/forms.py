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
        fields = ("kamad_phone_number",)
        labels = {
            "kamad_phone_number": "Nomor WhatsApp Kamad",
        }
        help_texts = {
            "kamad_phone_number": "Masukkan nomor WhatsApp Kamad. Nomor lokal yang diawali 0 otomatis diubah ke +62.",
        }
        widgets = {
            "kamad_phone_number": forms.TextInput(attrs={"class": "field", "placeholder": "081234567890", "inputmode": "tel"}),
        }

    def clean_kamad_phone_number(self):
        value = self.cleaned_data["kamad_phone_number"].strip()
        if not value:
            return ""
        return normalize_phone_number(value)
