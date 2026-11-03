from django.urls import path

from . import views

urlpatterns = [
	path("kamad/dashboard", views.dashboard, name="kamad-dashboard"),
	path("kamad/rekap-perizinan/", views.leave_report, name="leave-report"),
	path("api/v1/kamad/live-feed", views.live_feed, name="kamad-live-feed"),
	path("api/v1/kamad/izin/<int:pk>/approval", views.approve_leave, name="approve-leave"),
]