from django.urls import path

from . import views

urlpatterns = [
	path("admin/dashboard", views.admin_dashboard, name="admin-dashboard"),
	path("admin/notifikasi-perizinan", views.leave_notifications, name="leave-notifications"),
	path("admin/pengaturan-whatsapp", views.whatsapp_settings, name="whatsapp-settings"),
	path("admin/cetak-qr", views.qr_points, name="qr-points"),
	path("admin/cetak-qr/<int:pk>/pdf", views.qr_pdf, name="qr-pdf"),
	path("display/qr-sekolah", views.school_qr_display, name="school-qr-display"),
	path("api/v1/qr/dynamic", views.dynamic_qr, name="dynamic-qr"),
	path("service-worker.js", views.service_worker, name="service-worker"),
]