from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("core.urls")),
    path("", include("attendance.urls")),
    path("", include("kamad_dashboard.urls")),
    path("home/", RedirectView.as_view(pattern_name="role-home", permanent=False)),
]