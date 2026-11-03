from django.http import HttpResponseForbidden


class AdminRoleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/django-admin/") and request.user.is_authenticated:
            if request.user.role != "admin" and not request.user.is_superuser:
                return HttpResponseForbidden("Akses panel administrator ditolak.")
        return self.get_response(request)