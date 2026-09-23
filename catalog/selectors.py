"""Read-side queries for the public pages, with seat counts done in SQL."""

from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.utils import timezone

from .models import Cohort, Program, Workshop


def _held(prefix, now):
    """Seats that count against capacity. Portfolio-demo accounts never do."""
    held = Q(**{f"{prefix}__status": "active"}) | Q(
        **{f"{prefix}__status": "pending", f"{prefix}__hold_expires_at__gt": now}
    )
    return held & Q(**{f"{prefix}__user__is_demo": False})


def cohorts_with_seats(now=None):
    now = now or timezone.now()
    return Cohort.objects.annotate(
        seats_held=Count("enrollments", filter=_held("enrollments", now))
    )


def workshops_with_seats(now=None):
    now = now or timezone.now()
    return Workshop.objects.annotate(seats_held=Count("bookings", filter=_held("bookings", now)))


def next_open_cohorts(now=None):
    now = now or timezone.now()
    return cohorts_with_seats(now).filter(is_open=True, starts_at__gt=now).order_by("starts_at")


def published_programs_with_next_cohort(now=None):
    """Programs for the home page, each with .next_cohort (or None) attached."""
    now = now or timezone.now()
    first_open = (
        Cohort.objects.filter(program=OuterRef("pk"), is_open=True, starts_at__gt=now)
        .order_by("starts_at")
        .values("pk")[:1]
    )
    programs = list(
        Program.objects.filter(is_published=True).annotate(next_cohort_id=Subquery(first_open))
    )
    cohort_ids = [p.next_cohort_id for p in programs if p.next_cohort_id]
    cohorts = {c.pk: c for c in cohorts_with_seats(now).filter(pk__in=cohort_ids)}
    for program in programs:
        program.next_cohort = cohorts.get(program.next_cohort_id)
    return programs


def next_workshop(now=None):
    now = now or timezone.now()
    return (
        workshops_with_seats(now)
        .filter(is_published=True, starts_at__gt=now)
        .order_by("starts_at")
        .first()
    )


def cohort_for_program_page(program, now=None):
    now = now or timezone.now()
    return (
        next_open_cohorts(now)
        .filter(program=program)
        .prefetch_related(Prefetch("sessions", to_attr="session_list"), "sessions__topic")
        .first()
    )
