from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import SignupForm


def _safe_next(request):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return ""


def signup(request):
    if request.user.is_authenticated:
        return redirect("bookings:my_programs")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect(_safe_next(request) or "bookings:my_programs")
    return render(request, "accounts/signup.html", {"form": form, "next": _safe_next(request)})
