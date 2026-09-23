"""Portfolio-demo endpoints: enter as Maria, jump the clock, leave."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.http import Http404
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .demo import SESSION_KEY, create_demo_member, is_demo_user


def _demo_only(view):
    def wrapped(request, *args, **kwargs):
        if not settings.DEMO_MODE:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapped


def _back(request, default):
    target = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return default


@require_POST
@_demo_only
def enter(request):
    if request.user.is_authenticated and not is_demo_user(request.user):
        messages.info(request, "You're signed in with a real account. Sign out first to explore the demo.")
        return redirect("bookings:my_programs")
    if not is_demo_user(request.user):
        user = create_demo_member()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("bookings:my_programs")


@require_POST
@_demo_only
def toggle_time(request):
    if not is_demo_user(request.user):
        raise Http404
    request.session[SESSION_KEY] = request.POST.get("open") == "1"
    return redirect(_back(request, "bookings:my_programs"))


@require_POST
@_demo_only
def leave(request):
    user = request.user if is_demo_user(request.user) else None
    logout(request)
    if user is not None:
        user.delete()
    return redirect("catalog:home")
