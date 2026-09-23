import re
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Program(models.Model):
    """An eight-week live program. Each run of it is a Cohort."""

    title = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    tagline = models.CharField(max_length=200, help_text="One line for the programme card.")
    description = models.TextField()
    outcomes = models.TextField(
        blank=True, help_text='"What you will practise": one item per line.'
    )
    photo_caption = models.CharField(
        max_length=120, blank=True, help_text="Describes the photo, shown until a real one is added."
    )
    session_minutes = models.PositiveSmallIntegerField(default=75)
    price_full_cents = models.PositiveIntegerField(default=24000)
    instalment_cents = models.PositiveIntegerField(default=13000)
    instalment_count = models.PositiveSmallIntegerField(default=2)
    is_published = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("catalog:program", args=[self.slug])

    @property
    def outcome_list(self):
        return [line.strip() for line in self.outcomes.splitlines() if line.strip()]

    @property
    def instalments_total_cents(self):
        return self.instalment_cents * self.instalment_count

    @property
    def full_payment_saving_cents(self):
        return max(self.instalments_total_cents - self.price_full_cents, 0)

    def next_open_cohort(self):
        return (
            self.cohorts.filter(is_open=True, starts_at__gt=timezone.now())
            .order_by("starts_at")
            .first()
        )


class SessionTopic(models.Model):
    """The content of one week of a program, reused by every cohort."""

    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="topics")
    number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=160)
    summary = models.TextField(blank=True, help_text='"What we\'ll work on".')
    exercise = models.TextField(blank=True, help_text='"Before the session" exercise.')

    class Meta:
        ordering = ["program", "number"]
        constraints = [
            models.UniqueConstraint(fields=["program", "number"], name="unique_topic_number"),
        ]

    def __str__(self):
        return f"{self.program} · {self.number}. {self.title}"


class Cohort(models.Model):
    """One group running a program, with fixed dates and a seat limit."""

    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="cohorts")
    name = models.CharField(max_length=80, help_text='e.g. "November group".')
    starts_at = models.DateTimeField(help_text="Date and time of the first session.")
    capacity = models.PositiveSmallIntegerField(default=12)
    zoom_url = models.URLField(
        blank=True, help_text="Only shown to paid members, 15 minutes before each session."
    )
    is_open = models.BooleanField(default=True, help_text="Open for new bookings.")

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return f"{self.program} · {self.name}"

    @property
    def ends_at(self):
        last = self.sessions.order_by("-starts_at").first()
        return last.ends_at if last else self.starts_at

    def seats_taken(self):
        from bookings.models import Enrollment

        return Enrollment.objects.holding_seat().filter(cohort=self).count()

    def seats_left(self):
        return max(self.capacity - self.seats_taken(), 0)

    def is_bookable(self):
        return self.is_open and self.starts_at > timezone.now()

    def generate_sessions(self):
        """Create one weekly session per topic, starting at starts_at. Idempotent."""
        created = 0
        # Step in local wall-clock time, so a 19:00 group stays at 19:00 after
        # the clocks change (adding weeks to a UTC datetime would shift it).
        first = timezone.localtime(self.starts_at).replace(tzinfo=None)
        for topic in self.program.topics.all():
            _, was_created = Session.objects.get_or_create(
                cohort=self,
                topic=topic,
                defaults={
                    "starts_at": timezone.make_aware(first + timedelta(weeks=topic.number - 1)),
                    "duration_minutes": self.program.session_minutes,
                },
            )
            created += was_created
        return created


YOUTUBE_ID = re.compile(r"(?:youtu\.be/|youtube(?:-nocookie)?\.com/(?:watch\?v=|embed/|live/|shorts/))([\w-]{11})")


class Session(models.Model):
    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE, related_name="sessions")
    topic = models.ForeignKey(SessionTopic, on_delete=models.PROTECT, related_name="sessions")
    starts_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=75)
    recording_url = models.URLField(
        blank=True, help_text="Unlisted YouTube link, added after the session."
    )
    notes = models.TextField(blank=True, help_text="Elena's notes after the session.")

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.UniqueConstraint(fields=["cohort", "topic"], name="unique_session_topic"),
        ]

    def __str__(self):
        return f"{self.cohort} · Session {self.topic.number}"

    def get_absolute_url(self):
        return reverse("bookings:session", args=[self.pk])

    @property
    def number(self):
        return self.topic.number

    @property
    def title(self):
        return self.topic.title

    @property
    def ends_at(self):
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    @property
    def join_opens_at(self):
        return self.starts_at - timedelta(minutes=settings.JOIN_OPENS_MINUTES_BEFORE)

    def has_started(self, now=None):
        return (now or timezone.now()) >= self.starts_at

    def is_joinable(self, now=None):
        now = now or timezone.now()
        return self.join_opens_at <= now <= self.ends_at

    @property
    def youtube_id(self):
        match = YOUTUBE_ID.search(self.recording_url or "")
        return match.group(1) if match else ""


class Workshop(models.Model):
    """A single live evening, sold per seat."""

    title = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    description = models.TextField()
    starts_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=90)
    capacity = models.PositiveSmallIntegerField(default=20)
    price_cents = models.PositiveIntegerField(default=3500)
    zoom_url = models.URLField(blank=True)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return f"{self.title} · {self.starts_at:%d %b %Y}"

    @property
    def ends_at(self):
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    @property
    def join_opens_at(self):
        return self.starts_at - timedelta(minutes=settings.JOIN_OPENS_MINUTES_BEFORE)

    def is_joinable(self, now=None):
        now = now or timezone.now()
        return self.join_opens_at <= now <= self.ends_at

    def seats_taken(self):
        from bookings.models import WorkshopBooking

        return WorkshopBooking.objects.holding_seat().filter(workshop=self).count()

    def seats_left(self):
        return max(self.capacity - self.seats_taken(), 0)

    def is_bookable(self):
        return self.is_published and self.starts_at > timezone.now()
