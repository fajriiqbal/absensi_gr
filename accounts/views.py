from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST


class NIPLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True
    extra_context = {"page_title": "Masuk ke Presensi"}

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session.cycle_key()
        return response


login_view = NIPLoginView.as_view()


@require_POST
def login_api(request):
    nip = request.POST.get("nip", "").strip()
    password = request.POST.get("password", "")
    if not nip or not password:
        return JsonResponse({"status": "error", "message": "NIP dan kata sandi wajib diisi."}, status=400)
    user = authenticate(request, username=nip, password=password)
    if user is None:
        return JsonResponse({"status": "error", "message": "NIP atau kata sandi tidak cocok."}, status=401)
    login(request, user)
    return JsonResponse({"status": "ok", "user": {"nip": user.nip, "nama": user.nama_lengkap, "role": user.role}})


@login_required
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def pwa_setup(request):
    return render(request, "accounts/pwa_setup.html")


@login_required
def role_home(request):
    if request.user.role == "admin" or request.user.is_superuser:
        return redirect("admin-dashboard")
    if request.user.role == "kamad":
        return redirect("kamad-dashboard")
    return redirect("guru-scan")