"""Portfolio demo: a throwaway member account, and a clock that can jump
to "10 minutes before the next session" so visitors see the Zoom button open.

Demo accounts never pay, never take a real seat (see SeatQuerySet.holding_seat)
and are deleted after a few hours.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from catalog.demo_content import (
    DEMO_PROGRAM_SLUG,
    FINISHED_PROGRAM_SLUG,
    ensure_demo_content,
    finished_cohorts,
    running_cohorts,
)
from catalog.models import Session, Workshop

from .models import Enrollment, SeatBase, SessionCompletion, WorkshopBooking

SESSION_KEY = "demo_join_open"
MINUTES_BEFORE = 10


def is_demo_user(user):
    return bool(getattr(user, "is_demo", False))


def delete_stale_demo_accounts(now=None):
    now = now or timezone.now()
    User.objects.filter(is_demo=True, date_joined__lt=now - timedelta(hours=settings.DEMO_ACCOUNT_HOURS)).delete()
    # Hard cap, in case something clicks the button in a loop.
    extra = User.objects.filter(is_demo=True).order_by("-date_joined")[settings.DEMO_MAX_ACCOUNTS:]
    User.objects.filter(pk__in=list(extra.values_list("pk", flat=True))).delete()


@transaction.atomic
def create_demo_member():
    """A fresh 'Maria' half-way through Boundaries, with a finished program and a workshop."""
    ensure_demo_content()
    delete_stale_demo_accounts()
    now = timezone.now()

    user = User.objects.create_user(
        email=f"demo-{secrets.token_hex(8)}@demo.quietwork.invalid", first_name="Maria", is_demo=True
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])

    running = running_cohorts(now).filter(program__slug=DEMO_PROGRAM_SLUG).order_by("-starts_at").first()
    if running:
        Enrollment.objects.create(
            user=user, cohort=running, plan=Enrollment.Plan.INSTALMENTS, status=SeatBase.Status.ACTIVE,
            instalments_paid=1, amount_paid_cents=running.program.instalment_cents, paid_at=running.starts_at,
        )
        _complete(user, running.sessions.filter(starts_at__lt=now))

    finished = finished_cohorts(now).filter(program__slug=FINISHED_PROGRAM_SLUG).order_by("-starts_at").first()
    if finished:
        Enrollment.objects.create(
            user=user, cohort=finished, plan=Enrollment.Plan.FULL, status=SeatBase.Status.ACTIVE,
            amount_paid_cents=finished.program.price_full_cents, paid_at=finished.starts_at,
        )
        _complete(user, finished.sessions.all())

    workshop = Workshop.objects.filter(is_published=True, starts_at__gt=now).order_by("starts_at").first()
    if workshop:
        WorkshopBooking.objects.create(
            user=user, workshop=workshop, status=SeatBase.Status.ACTIVE,
            amount_paid_cents=workshop.price_cents, paid_at=now,
        )
    return user


def _complete(user, sessions):
    SessionCompletion.objects.bulk_create([SessionCompletion(user=user, session=s) for s in sessions])


def next_session_for(user, now):
    return (
        Session.objects.filter(
            cohort__enrollments__user=user, cohort__enrollments__status=SeatBase.Status.ACTIVE,
            starts_at__gt=now,
        )
        .order_by("starts_at")
        .first()
    )


def effective_now(request):
    """The real time, unless a demo visitor asked to jump to 10 minutes before their next session."""
    now = timezone.now()
    if not (settings.DEMO_MODE and is_demo_user(request.user) and request.session.get(SESSION_KEY)):
        return now
    upcoming = next_session_for(request.user, now)
    return upcoming.starts_at - timedelta(minutes=MINUTES_BEFORE) if upcoming else now
