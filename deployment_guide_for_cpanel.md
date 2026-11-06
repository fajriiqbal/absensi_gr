# Panduan Deployment Django ke cPanel

Panduan ini untuk aplikasi **absensi_gr** pada domain `absen.mtssunankalijagatulung.sch.id`.

---

## 1. Siapkan repository dan Python App

1. Pastikan DNS domain mengarah ke hosting dan SSL aktif.
2. Di **Git Version Control**, clone `https://github.com/fajriiqbal/absensi_gr.git` ke direktori aplikasi, misalnya `~/absensi_gr`.
3. Di **Setup Python App**, buat aplikasi dengan:
   - Python 3.11 atau lebih baru yang didukung provider.
   - Application root menunjuk ke direktori clone (bukan `public_html`).
   - Application URL menunjuk ke `absen.mtssunankalijagatulung.sch.id`.
   - Startup file `passenger_wsgi.py` dan entry point `application`.
4. Gunakan `passenger_wsgi.py` dari repository; file itu sudah menambahkan root aplikasi ke Python path. Jangan menggantinya dengan contoh yang memuat path `/home/USERNAME` placeholder.
5. Salin perintah aktivasi virtual environment yang ditampilkan cPanel. Semua perintah berikut dijalankan di Terminal cPanel setelah environment diaktifkan:

   ```bash
   cd ~/absensi_gr
   python -m pip install -r requirements.txt
   ```

## 2. Atur environment variables di cPanel

**Jangan mengubah `config/settings.py` untuk memasukkan rahasia.** Django tidak membaca file `.env` secara otomatis; `.env.example` hanya contoh. Tambahkan variabel berikut pada bagian environment variables di halaman **Setup Python App**, tanpa tanda kutip. Ganti semua nilai contoh dengan nilai asli sebelum restart aplikasi.

| Nama | Nilai |
|---|---|
| `DJANGO_SECRET_KEY` | Kunci acak rahasia. Buat dengan `python -c "import secrets; print(secrets.token_urlsafe(64))"` di Terminal. |
| `DJANGO_DEBUG` | `0` |
| `DJANGO_ALLOWED_HOSTS` | `absen.mtssunankalijagatulung.sch.id,www.absen.mtssunankalijagatulung.sch.id` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://absen.mtssunankalijagatulung.sch.id,https://www.absen.mtssunankalijagatulung.sch.id` |
| `MEDIA_ENCRYPTION_KEY` | Kunci Fernet valid. Buat setelah instalasi requirements dengan `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `DB_ENGINE` | `django.db.backends.postgresql` |
| `DB_NAME` | Nama database PostgreSQL cPanel |
| `DB_USER` | User PostgreSQL cPanel dengan hak akses ke database |
| `DB_PASSWORD` | Password user database |
| `DB_HOST` | Host PostgreSQL dari penyedia hosting (sering `localhost`) |
| `DB_PORT` | Port PostgreSQL dari penyedia hosting (sering `5432`) |
| `SECURE_SSL_REDIRECT` | `1` |

`SCHOOL_NAME` dan `ATTENDANCE_LATE_AFTER` bersifat opsional. `ATTENDANCE_LATE_AFTER` hanya menjadi nilai awal batas terlambat ketika pengaturan waktu presensi pertama kali dibuat; setelah itu, atur jam masuk, batas terlambat, jam mulai pulang, jam pulang normal, dan jadwal pulang khusus per tanggal dari Dashboard Admin → Presensi → Pengaturan Waktu Presensi. Buat database PostgreSQL dan berikan hak akses kepada user melalui **PostgreSQL Databases** cPanel. Nama database/user di cPanel dapat memiliki awalan akun hosting.

`DJANGO_SECRET_KEY` dan `MEDIA_ENCRYPTION_KEY` wajib ada saat `DJANGO_DEBUG=0`; jika tidak, aplikasi gagal mulai dan Passenger akan menampilkan HTTP 500. Simpan kedua kunci dengan aman. Jangan mengganti `MEDIA_ENCRYPTION_KEY` setelah ada foto atau dokumen tersimpan karena file lama tidak dapat didekripsi dengan kunci baru. Jangan unggah nilai rahasia ke Git atau kirimkannya melalui tiket/log publik.

## 3. Migrasi, static files, dan restart

Pastikan semua environment variables di atas sudah disimpan di cPanel, lalu di Terminal yang sama (virtual environment aktif):

```bash
cd ~/absensi_gr
python manage.py check
python manage.py migrate
python manage.py collectstatic --noinput
```

Jika `check` atau `migrate` gagal, perbaiki error yang ditampilkan sebelum melanjutkan. Setelah itu, kembali ke **Setup Python App**, restart aplikasi, lalu buka `https://absen.mtssunankalijagatulung.sch.id`.

WhiteNoise melayani file hasil `collectstatic` (termasuk CSS admin Django) melalui `/static/`. Pastikan direktori `STATIC_ROOT` dapat ditulis oleh akun aplikasi. Jika halaman admin tidak memiliki CSS setelah update, tarik kode terbaru, aktifkan virtualenv, jalankan `python -m pip install -r requirements.txt` dan `python manage.py collectstatic --noinput`, lalu restart Python App.

## 4. Jika masih HTTP 500

1. Periksa **Errors** di cPanel atau error log Passenger untuk aplikasi/domain dan baca traceback paling baru.
2. Pastikan environment variables tersimpan pada Python App yang URL-nya benar, bukan hanya di file `.env` atau Terminal.
3. Cocokkan traceback dengan konfigurasi: `ImproperlyConfigured` biasanya menandakan secret/key produksi belum diatur; `ModuleNotFoundError` berarti requirements belum terpasang di virtual environment aplikasi; error koneksi database berarti `DB_*`, database, atau hak aksesnya belum benar.
4. Setelah memperbaiki konfigurasi atau menarik commit terbaru, restart Python App lagi.

Jangan mengaktifkan `DJANGO_DEBUG=1` pada situs publik untuk melihat traceback. Bila perlu bantuan mendiagnosis, bagikan traceback dari log setelah menghapus password, secret key, dan data pribadi. Tanpa traceback dari hosting, penyebab spesifik HTTP 500 tidak dapat dipastikan dari sisi repository saja. 