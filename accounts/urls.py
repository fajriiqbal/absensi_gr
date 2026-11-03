from django.urls import path

from . import views

urlpatterns = [
	path("login/", views.login_view, name="login"),
	path("api/v1/auth/login", views.login_api, name="api-login"),
	path("logout/", views.logout_view, name="logout"),
	path("guru/pwa-setup/", views.pwa_setup, name="pwa-setup"),
	path("role-home/", views.role_home, name="role-home"),
]