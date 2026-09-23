from datetime import timedelta

from django.utils import timezone

from accounts.models import User
from catalog.models import Cohort, Program, SessionTopic, Workshop


def make_user(email="member@example.com", **extra):
    return User.objects.create_user(email=email, password="a-long-test-password", **extra)


def make_program(slug="boundaries", topics=8, **extra):
    program = Program.objects.create(
        title="Boundaries Without Guilt", slug=slug, tagline="t", description="d", **extra
    )
    for n in range(1, topics + 1):
        SessionTopic.objects.create(program=program, number=n, title=f"Topic {n}")
    return program


def make_cohort(program=None, starts_in=timedelta(days=14), capacity=12, **extra):
    program = program or make_program()
    cohort = Cohort.objects.create(
        program=program, name="Test group", starts_at=timezone.now() + starts_in,
        capacity=capacity, zoom_url="https://zoom.us/j/123", **extra,
    )
    cohort.generate_sessions()
    return cohort


def make_workshop(starts_in=timedelta(days=7), capacity=20, **extra):
    return Workshop.objects.create(
        title="Live", slug=extra.pop("slug", "live"), description="d",
        starts_at=timezone.now() + starts_in, capacity=capacity,
        zoom_url="https://zoom.us/j/456", **extra,
    )
