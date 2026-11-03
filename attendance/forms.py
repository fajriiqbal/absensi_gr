from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet, inlineformset_factory

from accounts.models import UserGuru
from .models import JadwalPelajaranIzin, PengajuanIzin


class PengajuanIzinForm(forms.ModelForm):
    class Meta:
        model = PengajuanIzin
        fields = ("jenis_izin", "tgl_mulai", "tgl_selesai", "alasan", "file_bukti")
        widgets = {
            "jenis_izin": forms.Select(attrs={"class": "field"}),
            "tgl_mulai": forms.DateInput(attrs={"class": "field", "type": "date"}),
            "tgl_selesai": forms.DateInput(attrs={"class": "field", "type": "date"}),
            "alasan": forms.Textarea(attrs={"class": "field", "rows": 4, "maxlength": 2000}),
            "file_bukti": forms.ClearableFileInput(attrs={"class": "field", "accept": ".pdf,.jpg,.jpeg,.png"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("tgl_mulai")
        end = cleaned_data.get("tgl_selesai")
        if start and end and end < start:
            self.add_error("tgl_selesai", "Tanggal selesai tidak boleh sebelum tanggal mulai.")
        return cleaned_data

    def clean_file_bukti(self):
        evidence = self.cleaned_data["file_bukti"]
        if evidence.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Ukuran lampiran maksimal 5 MB.")
        extension = evidence.name.rsplit(".", 1)[-1].lower() if "." in evidence.name else ""
        if extension not in {"pdf", "jpg", "jpeg", "png"}:
            raise forms.ValidationError("Lampiran harus berupa PDF, JPG, atau PNG.")
        return evidence


class JadwalPelajaranIzinForm(forms.ModelForm):
    class Meta:
        model = JadwalPelajaranIzin
        fields = (
            "hari",
            "tanggal",
            "mapel_diampu",
            "jam_pelajaran_diampu",
            "mapel_lukiran",
            "jam_lukiran",
            "keterangan_kelas",
            "guru_lukiran",
        )
        widgets = {
            "hari": forms.Select(attrs={"class": "field jadwal-hari"}),
            "tanggal": forms.DateInput(attrs={"class": "field jadwal-tanggal", "type": "date"}),
            "mapel_diampu": forms.TextInput(attrs={"class": "field", "maxlength": 100, "placeholder": "Contoh: Matematika"}),
            "jam_pelajaran_diampu": forms.TextInput(attrs={"class": "field", "maxlength": 50, "placeholder": "Contoh: Jam ke-1 atau 07.00-07.40"}),
            "mapel_lukiran": forms.TextInput(attrs={"class": "field", "maxlength": 100, "placeholder": "Mapel yang dialihkan"}),
            "jam_lukiran": forms.TextInput(attrs={"class": "field", "maxlength": 50, "placeholder": "Jam yang dialihkan"}),
            "keterangan_kelas": forms.TextInput(attrs={"class": "field", "maxlength": 100, "placeholder": "Contoh: VII-A"}),
            "guru_lukiran": forms.Select(attrs={"class": "field"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        teachers = UserGuru.objects.filter(role="guru", is_active=True).order_by("nama_lengkap")
        parent = getattr(self.instance, "pengajuan", None)
        if parent and parent.guru_id:
            teachers = teachers.exclude(pk=parent.guru_id)
        self.fields["guru_lukiran"].queryset = teachers


class JadwalPelajaranIzinFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        start = getattr(self.instance, "tgl_mulai", None)
        end = getattr(self.instance, "tgl_selesai", None)
        if not start or not end:
            return
        for form in self.forms:
            data = getattr(form, "cleaned_data", {})
            if not data or data.get("DELETE"):
                continue
            lesson_date = data.get("tanggal")
            if lesson_date and not start <= lesson_date <= end:
                form.add_error("tanggal", "Tanggal jadwal harus berada dalam rentang tanggal izin.")
        if any(self.errors):
            raise ValidationError("Periksa kembali tanggal rincian jam pelajaran.")


JadwalPelajaranIzinFormSetFactory = inlineformset_factory(
    PengajuanIzin,
    JadwalPelajaranIzin,
    form=JadwalPelajaranIzinForm,
    formset=JadwalPelajaranIzinFormSet,
    extra=1,
    can_delete=True,
    max_num=20,
    validate_max=True,
)