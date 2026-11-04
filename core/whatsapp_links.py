from urllib.parse import urlencode


def build_leave_notification_link(phone_number, leave, dashboard_url):
    recipient = phone_number.removeprefix("+")
    message = "\n".join((
        "Assalamu'alaikum, ada pengajuan izin baru yang menunggu persetujuan.",
        f"Nama guru: {leave.guru.nama_lengkap}",
        f"Jenis izin: {leave.get_jenis_izin_display()}",
        f"Periode: {leave.tgl_mulai:%d-%m-%Y} s.d. {leave.tgl_selesai:%d-%m-%Y}",
        f"Silakan tinjau pengajuan di dashboard: {dashboard_url}",
    ))
    return f"https://wa.me/{recipient}?{urlencode({'text': message})}"
