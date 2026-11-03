# PRD & Technical Specification: Sistem Absensi Guru Berbasis Web (Multi-Mode QR)

## 1. Overview & Tech Stack Recommendations

### 1.1 Objective
Membangun sistem presensi guru berbasis web yang cepat, aman dari kecurangan, serta mendukung metode scan yang sangat fleksibel:
1. **Dynamic QR di TV/Monitor** (Akurat & cepat).
2. **Printable / Static QR Code** (Dicetak di banner/kertas poster meja piket).
3. **Kiosk Tablet Sekolah** (Scan QR HP guru atau input manual jika HP guru rusak/mati).

Sistem dilengkapi dashboard *real-time monitoring* dan *approval center* untuk Kepala Madrasah.

### 1.2 Selected Tech Stack
* **Backend Framework:** Python 3.11+ / Django 5.x (Admin Panel bawaan, ORM kuat, Auth terintegrasi, dan keamanan tinggi).
* **Real-time Engine:** Django Channels + WebSockets / Server-Sent Events (SSE).
* **Database:** PostgreSQL (Production) / SQLite (Development).
* **Frontend & PWA:** HTML5, Tailwind CSS, Alpine.js, HTMX, Service Workers (PWA), HTML5 QR Code Scanner Library (`html5-qrcode`).
* **PDF & QR Generator Engine:** `qrcode` (Python Library) & `WeasyPrint` / `ReportLab` (Untuk cetak QR Poster PDF).

---

## 2. System Architecture & Flow

```
[ MODUL SCAN UTAMA ]
┌────────────────────────────────────────┐
│ Option A: TV/Monitor Ruang Guru        │ <── Dynamic QR (Berganti tiap 15s via WebSocket)
│ Option B: Poster QR Cetak (Banner/Paper)│ <── Static QR (Wajib GPS Geofencing Strict + Selfie)
└────────────────────────────────────────┘
                   ▲
                   │ Scan QR via Kamera HP
┌──────────────────┴─────────────────────┐
│ HP Guru (PWA - Persistent Login)       │ ───► POST /api/v1/absen/scan
│ - Auto Launch Camera                   │      Payload: { qr_payload, lat, lng, photo_blob }
│ - Background Geolocation Fetch         │
└────────────────────────────────────────┘

[ MODUL KIOSK CADANGAN (MEJA PIKET) ]
┌────────────────────────────────────────┐
│ Tablet / Laptop Piket                  │
│ - Mode 1: Scan QR Dinamis di HP Guru   │ ───► POST /api/v1/absen/kiosk-scan
│ - Mode 2: Input Manual NIP + Foto Live │ ───► POST /api/v1/absen/kiosk-manual
└────────────────────────────────────────┘
                   │
                   ▼ (Database Transaction & Realtime Push)
┌────────────────────────────────────────┐
│ Dashboard Kepala Madrasah              │ ◄─── SSE / WebSocket Live Feed Update
└────────────────────────────────────────┘
```

---

## 3. Database Schema Blueprint (Django ORM Models)

### 3.1 Model `UserGuru` (Custom User Model)
```python
# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class UserGuru(AbstractUser):
    ROLE_CHOICES = (
        ('guru', 'Guru / Staf'),
        ('kamad', 'Kepala Madrasah'),
        ('admin', 'Administrator System'),
    )
    nip = models.CharField(max_length=20, unique=True, db_index=True)
    nama_lengkap = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='guru')
    foto_profil = models.ImageField(upload_to='profiles/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    USERNAME_FIELD = 'nip'
    REQUIRED_FIELDS = ['username', 'nama_lengkap', 'email']
```

### 3.2 Model `LokasiSekolah` & `TitikQRCetak`
```python
# core/models.py
from django.db import models
import uuid

class LokasiSekolah(models.Model):
    nama_lokasi = models.CharField(max_length=100, default="Gedung MTs Utama")
    latitude = models.DecimalField(max_digits=11, decimal_places=8)
    longitude = models.DecimalField(max_digits=11, decimal_places=8)
    radius_toleransi_meter = models.PositiveIntegerField(default=50)

class TitikQRCetak(models.Model):
    """Model untuk mengelola QR Code yang dicetak di kertas/banner/poster"""
    kode_lokasi = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    label_titik = models.CharField(max_length=100) # Misal: "Poster Pintu Gerbang", "Meja Piket"
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### 3.3 Model `AbsensiLog` & `PengajuanIzin`
```python
# attendance/models.py
from django.db import models
from accounts.models import UserGuru

class AbsensiLog(models.Model):
    METODE_CHOICES = (
        ('qr_tv', 'HP Guru Scan Dynamic QR TV'),
        ('qr_cetak', 'HP Guru Scan Poster QR Cetak'),
        ('qr_guru', 'Tablet Kiosk Scan QR HP Guru'),
        ('manual_kiosk', 'Manual Input Kiosk Darurat'),
    )
    STATUS_CHOICES = (
        ('hadir', 'Hadir Tepat Waktu'),
        ('terlambat', 'Terlambat'),
        ('pulang_cepat', 'Pulang Lebih Awal'),
    )
    guru = models.ForeignKey(UserGuru, on_delete=models.CASCADE, related_name='absensilogs')
    tanggal = models.DateField(auto_now_add=True, db_index=True)
    waktu_masuk = models.DateTimeField(null=True, blank=True)
    waktu_pulang = models.DateTimeField(null=True, blank=True)
    lat_masuk = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    long_masuk = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    foto_masuk = models.ImageField(upload_to='attendance_photos/', null=True, blank=True)
    metode_scan = models.CharField(max_length=20, choices=METODE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='hadir')
    catatan = models.TextField(blank=True, null=True)

class PengajuanIzin(models.Model):
    JENIS_CHOICES = (
        ('sakit', 'Sakit'),
        ('izin', 'Izin Personal'),
        ('dinas_luar', 'Dinas Luar'),
        ('cuti', 'Cuti'),
    )
    APPROVAL_CHOICES = (
        ('pending', 'Menunggu Persetujuan'),
        ('disetujui', 'Disetujui'),
        ('ditolak', 'Ditolak'),
    )
    guru = models.ForeignKey(UserGuru, on_delete=models.CASCADE)
    jenis_izin = models.CharField(max_length=20, choices=JENIS_CHOICES)
    tgl_mulai = models.DateField()
    tgl_selesai = models.DateField()
    alasan = models.TextField()
    file_bukti = models.FileField(upload_to='dokumen_izin/')
    status_approval = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='pending')
    approved_by = models.ForeignKey(UserGuru, on_delete=models.SET_NULL, null=True, blank=True, related_name='approvals')
    catatan_kamad = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

---

## 4. Keamanan & Generator QR Cetak (Printable Engine)

### 4.1 Pembuatan & Cetak QR Code Poster (Admin Feature)
Admin/Operator sekolah dapat mengunduh file PNG/PDF QR Code khusus yang siap dicetak di printer:
```python
# utils/qr_generator.py
import qrcode
from io import BytesIO

def generate_printable_qr_image(kode_lokasi_uuid):
    """Menghasilkan gambar QR Code statis untuk dicetak di kertas/banner"""
    qr_payload = f"MTS-PRINTABLE-QR:{kode_lokasi_uuid}"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()
```

### 4.2 Logika Validasi Scan QR Cetak
Karena QR cetak bersifat statis (bisa difoto), backend **WAJIB** memvalidasi koordinat GPS dan meminta foto selfie dari HP guru.
```python
# attendance/views.py (Logic Excerpt)
def validate_scan_request(request):
    qr_data = request.POST.get('qr_payload')
    user_lat = request.POST.get('latitude')
    user_long = request.POST.get('longitude')
    
    # 1. Jika QR berasal dari Poster Cetak
    if qr_data.startswith("MTS-PRINTABLE-QR:"):
        # Wajibkan validasi GPS Geofencing Haversine secara STRICT
        distance = calculate_haversine(user_lat, user_long, sekolah.latitude, sekolah.longitude)
        if distance > sekolah.radius_toleransi_meter:
            return JsonResponse({
                "status": "error",
                "message": f"Absen Ditolak! Anda berada {int(distance)}m di luar lokasi sekolah."
            }, status=400)
            
        # Wajibkan adanya upload foto selfie saat scan poster cetak
        if 'foto_selfie' not in request.FILES:
            return JsonResponse({
                "status": "error",
                "message": "Foto bukti selfie diperlukan untuk scan QR Cetak!"
            }, status=400)

    # 2. Jika QR berasal dari TV Dinamis
    elif qr_data.startswith("MTS-TV-DYNAMIC:"):
        decoded_token, is_valid = verify_dynamic_qr_token(qr_data.split(":")[1])
        if not is_valid:
            return JsonResponse({"status": "error", "message": decoded_token['error']}, status=400)
```

---

## 5. Endpoints & API Structure

| HTTP Method | Route Endpoint | Access Role | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/login` | Public | Login awal, mengembalikan Session / Token |
| `GET` | `/admin/cetak-qr/<id>/pdf` | Admin | Download file PDF/PNG QR Code siap cetak |
| `GET` | `/display/qr-sekolah` | Public/Monitor | Tampilan UI TV monitor (Dynamic QR via WebSocket) |
| `POST` | `/api/v1/absen/scan` | Guru | Unified scan endpoint (Mendukung QR TV & QR Cetak) |
| `GET` | `/guru/my-qr` | Guru | Tampilan UI QR Code di HP Guru |
| `POST` | `/api/v1/absen/kiosk-scan` | Kiosk Tablet | Tablet membaca QR di HP Guru |
| `POST` | `/api/v1/absen/kiosk-manual` | Kiosk Tablet | Input NIP + Foto Kamera Tablet saat HP Guru mati |
| `GET` | `/kamad/dashboard` | Kamad | Page Dashboard Monitoring Kepala Madrasah |
| `GET` | `/api/v1/kamad/live-feed` | Kamad | Stream data absensi real-time (SSE/WebSocket) |

---

## 6. Frontend Layout & User Experience (UX) Blueprint

### 6.1 Tampilan Admin: Halaman Cetak QR Poster (`/admin/titik-qr/`)
* UI sederhana dengan tombol **"Generate & Cetak QR Baru"**.
* Menampilkan pratinjau QR Code dengan header nama sekolah dan label titik (misal: *"Poster Meja Piket - MTs Sunan Kalijaga"*).
* Ada tombol **"Download PDF Siap Cetak"** berukuran A4 / A5.

### 6.2 PWA Application (HP Guru)
* **Auto-Detect Jenis QR:** Kamera HP secara otomatis mengenali apakah QR yang di-scan adalah milik TV Dinamis atau Poster Cetak.
* **Geolocator Pasif:** Mengambil koordinat GPS di latar belakang saat pemindaian berhasil.

---



