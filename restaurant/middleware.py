from django.shortcuts import redirect
from django.urls import reverse


class PasswordChangeRequiredMiddleware:
    """A provisional employee password grants access only to password change/logout."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.must_change_password:
            permitted = {reverse("password_change"), reverse("logout"), reverse("login")}
            if request.path not in permitted and not request.path.startswith("/static/"):
                return redirect("password_change")
        return self.get_response(request)
