# Sistem Absensi Guru

Project Django modular untuk presensi guru dengan QR TV dinamis, QR poster cetak, dashboard Kamad, dan PWA.

## Menjalankan lokal

Gunakan Python 3.11 atau lebih baru. Buat virtual environment, aktifkan, lalu jalankan:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Atur `DJANGO_SECRET_KEY` dan `MEDIA_ENCRYPTION_KEY` pada environment sebelum deployment. Buat media key dengan `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` dan simpan di secret manager; jangan menggantinya setelah ada file terenkripsi. Tambahkan lokasi sekolah melalui `/django-admin/` sebelum QR poster digunakan. Akun admin/kamad/guru dapat dibuat dari admin Django dan diberi role yang sesuai.

## Deployment cPanel

Repo menyertakan `passenger_wsgi.py` untuk entry point aplikasi Python cPanel. Buat Python App dengan application root di folder hasil clone repo dan startup file `passenger_wsgi.py`, lalu entry point `application`. Atur environment variables aplikasi di cPanel berdasarkan `.env.example`; ganti semua placeholder, gunakan `DJANGO_DEBUG=0`, secret key acak, dan media encryption key Fernet yang valid. Django tidak membaca `.env` secara otomatis. Gunakan database PostgreSQL cPanel dan sesuaikan `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, serta `DB_PORT`. Jangan mengunggah `.env` atau memasukkan kredensial ke Git. Lihat [panduan deployment cPanel](deployment_guide_for_cpanel.md) untuk langkah dan pemeriksaan error 500.

Setelah dependencies terpasang di virtual environment aplikasi, jalankan `python manage.py migrate` dan `python manage.py collectstatic --noinput`, lalu restart Python App dari cPanel. WhiteNoise melayani hasil `collectstatic` (termasuk CSS admin) melalui `/static/`. Pastikan DNS subdomain `absen.mtssunankalijagatulung.sch.id` mengarah ke hosting dan SSL aktif sebelum mengakses aplikasi. Folder `MEDIA_ROOT` harus tetap privat; jangan arahkan document root subdomain ke folder media.

## Halaman

- Login: `/login/`
- Setup PWA: `/guru/pwa-setup/`
- Dashboard Admin: `/admin/dashboard`
- Rekap absensi bulanan per guru (Excel): `/admin/rekap-absensi/`
- Cetak QR poster (admin/operator): `/admin/cetak-qr`
- QR dinamis untuk TV: `/display/qr-sekolah`
- Pemindai guru: `/guru/scan`
- Pengajuan dan riwayat izin guru: `/guru/perijinan/`
- Dashboard Kamad: `/kamad/dashboard`
- Histori perizinan bulanan Kamad (Excel): `/kamad/rekap-perizinan/`
- Admin Django: `/django-admin/`

Gunakan akun dengan role `admin` untuk Dashboard Admin dan panel data. Akun `guru` hanya mendapat halaman scan/QR kiosk; akun `kamad` mendapat dashboard monitoring dan approval. Monitor TV dapat dibuka tanpa login.

Guru mengajukan izin pada `/guru/perijinan/` dengan mengisi tanggal, alasan, dan lampiran bukti PDF/JPG/PNG (maksimal 5 MB). Setiap pengajuan dapat memuat beberapa rincian jadwal: hari/tanggal, mapel dan jam yang diampu, mapel/jam lukiran, keterangan kelas (contoh `VII-A`), serta guru rekan. Kamad melihat rincian tersebut saat approval. Setelah disetujui, guru dapat mengunduh surat persetujuan PDF dari riwayatnya; rekap Excel Kamad menyertakan sheet rincian jadwal.

QR TV ditandatangani HS256 dan berlaku 15 detik. QR poster membutuhkan koordinat GPS dalam radius lokasi sekolah serta selfie JPEG/PNG/WEBP maksimal 5 MB. Koordinat harus berasal dari Geolocation API pada browser dan HTTPS diperlukan di luar localhost.

Media bukti dienkripsi dengan Fernet saat disimpan dan hanya dapat diakses lewat endpoint privat yang memeriksa pemilik atau role Kamad/staff. Untuk production, gunakan PostgreSQL melalui variabel `DB_*`, HTTPS, `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` acak, serta `MEDIA_ENCRYPTION_KEY` permanen. Backup media dan kedua kunci melalui secret manager dengan rotasi terencana. Jangan menayangkan folder `MEDIA_ROOT` langsung ke publik.

## Pemeriksaan

```powershell
python manage.py check
python manage.py test accounts.tests core.tests attendance.tests kamad_dashboard.tests
```