from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone

from accounts.models import UserGuru
from core.models import JadwalWaktuPresensiGuru, PengaturanWaktuPresensi
from .models import JadwalPelajaranIzin, PengajuanIzin


class PengajuanIzinForm(forms.ModelForm):
    tugas_kelas = forms.CharField(
        required=False,
        max_length=5000,
        widget=forms.Textarea(attrs={"class": "field", "rows": 4}),
    )

    class Meta:
        model = PengajuanIzin
        fields = (
            "jenis_izin",
            "tgl_mulai",
            "tgl_selesai",
            "jam_datang_diminta",
            "jam_pulang_diminta",
            "alasan",
            "file_bukti",
            "tugas_kelas",
        )
        widgets = {
            "jenis_izin": forms.Select(attrs={"class": "field"}),
            "tgl_mulai": forms.DateInput(attrs={"class": "field", "type": "date"}),
            "tgl_selesai": forms.DateInput(attrs={"class": "field", "type": "date"}),
            "jam_datang_diminta": forms.TimeInput(format="%H:%M", attrs={"class": "field", "type": "time"}),
            "jam_pulang_diminta": forms.TimeInput(format="%H:%M", attrs={"class": "field", "type": "time"}),
            "alasan": forms.Textarea(attrs={"class": "field", "rows": 4, "maxlength": 2000}),
            "file_bukti": forms.ClearableFileInput(attrs={"class": "field", "accept": ".pdf,.jpg,.jpeg,.png"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["jenis_izin"].choices = (
            ("sakit", "Sakit"),
            ("datang_terlambat", "Izin Datang Terlambat"),
            ("pulang_awal", "Izin Pulang Lebih Awal"),
        )
        leave_type = (
            self.data.get("jenis_izin")
            if self.is_bound
            else self.initial.get("jenis_izin")
        )
        self.fields["jam_pulang_diminta"].required = leave_type == "pulang_awal"
        self.fields["jam_datang_diminta"].required = leave_type == "datang_terlambat"
        self.fields["file_bukti"].required = leave_type == "sakit"

    def clean(self):
        cleaned_data = super().clean()
        leave_type = cleaned_data.get("jenis_izin")
        start = cleaned_data.get("tgl_mulai")
        end = cleaned_data.get("tgl_selesai")
        if start and end and end < start:
            self.add_error("tgl_selesai", "Tanggal selesai tidak boleh sebelum tanggal mulai.")
        if leave_type in {"pulang_awal", "datang_terlambat"}:
            leave_label = "pulang lebih awal" if leave_type == "pulang_awal" else "datang terlambat"
            if start and end and start != end:
                self.add_error("tgl_selesai", f"Izin {leave_label} hanya berlaku untuk satu tanggal.")
            if start and start < timezone.localdate():
                self.add_error("tgl_mulai", f"Tanggal izin {leave_label} tidak boleh sudah lewat.")
        if leave_type == "pulang_awal":
            departure = cleaned_data.get("jam_pulang_diminta")
            if not departure:
                self.add_error("jam_pulang_diminta", "Jam pulang yang diminta wajib diisi.")
            elif departure <= PengaturanWaktuPresensi.get_settings().batas_terlambat:
                self.add_error("jam_pulang_diminta", "Jam pulang harus setelah batas waktu tepat waktu.")
            elif start == timezone.localdate() and departure <= timezone.localtime().time().replace(tzinfo=None):
                self.add_error("jam_pulang_diminta", "Jam pulang yang diminta sudah lewat.")
            if start and self.instance.guru_id:
                existing_request = PengajuanIzin.objects.filter(
                    guru=self.instance.guru,
                    jenis_izin="pulang_awal",
                    tgl_mulai=start,
                    status_approval__in=("pending", "disetujui"),
                )
                if self.instance.pk:
                    existing_request = existing_request.exclude(pk=self.instance.pk)
                if existing_request.exists() or JadwalWaktuPresensiGuru.objects.filter(
                    guru=self.instance.guru,
                    tanggal=start,
                ).exists():
                    self.add_error("tgl_mulai", "Sudah ada pengajuan atau jadwal pulang khusus untuk tanggal tersebut.")
        else:
            cleaned_data["jam_pulang_diminta"] = None
        if leave_type == "datang_terlambat":
            arrival = cleaned_data.get("jam_datang_diminta")
            if not arrival:
                self.add_error("jam_datang_diminta", "Jam datang yang diminta wajib diisi.")
            elif arrival <= PengaturanWaktuPresensi.get_settings().batas_terlambat:
                self.add_error("jam_datang_diminta", "Jam datang harus setelah batas waktu tepat waktu.")
            if start and self.instance.guru_id and PengajuanIzin.objects.filter(
                guru=self.instance.guru,
                jenis_izin="datang_terlambat",
                tgl_mulai=start,
                status_approval__in=("pending", "disetujui"),
            ).exists():
                self.add_error("tgl_mulai", "Sudah ada pengajuan datang terlambat untuk tanggal tersebut.")
        else:
            cleaned_data["jam_datang_diminta"] = None
        if leave_type != "sakit":
            cleaned_data["tugas_kelas"] = ""
            cleaned_data["file_bukti"] = None
        return cleaned_data

    def clean_file_bukti(self):
        evidence = self.cleaned_data.get("file_bukti")
        if not evidence:
            return evidence
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