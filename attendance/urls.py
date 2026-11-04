from django.urls import path

from . import views

urlpatterns = [
	path("admin/rekap-absensi/", views.attendance_report, name="attendance-report"),
	path("guru/perijinan/", views.leave_requests, name="leave-requests"),
	path("guru/perijinan/<int:pk>/surat.pdf", views.download_leave_letter, name="leave-letter"),
	path("guru/scan", views.scan_page, name="guru-scan"),
	path("guru/my-qr", views.my_qr, name="guru-my-qr"),
	path("kiosk/scan", views.kiosk_scan_page, name="kiosk-scan-page"),
	path("api/v1/guru/qr", views.teacher_qr_api, name="teacher-qr"),
	path("api/v1/absen/scan", views.scan_api, name="attendance-scan"),
	path("api/v1/absen/kiosk-scan", views.kiosk_scan_api, name="kiosk-scan"),
	path("api/v1/absen/kiosk-manual", views.kiosk_manual_api, name="kiosk-manual"),
	path("media/private/izin/<int:pk>", views.private_leave_document, name="private-leave-document"),
	path("media/private/absensi/<int:pk>", views.private_attendance_photo, name="private-attendance-photo"),
]