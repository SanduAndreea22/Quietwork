from django.conf import settings

from .demo import SESSION_KEY, is_demo_user


def demo(request):
    if not settings.DEMO_MODE:
        return {"demo_mode": False}
    user = getattr(request, "user", None)
    return {
        "demo_mode": True,
        "is_demo_user": bool(user and user.is_authenticated and is_demo_user(user)),
        "demo_join_open": bool(request.session.get(SESSION_KEY)) if hasattr(request, "session") else False,
    }
