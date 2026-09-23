from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from catalog.models import Cohort, Session, Workshop


class SeatQuerySet(models.QuerySet):
    def holding_seat(self, now=None):
        """Paid seats plus seats still held by an open Stripe Checkout."""
        now = now or timezone.now()
        return self.filter(
            Q(status=SeatBase.Status.ACTIVE)
            | Q(status=SeatBase.Status.PENDING, hold_expires_at__gt=now)
        ).exclude(user__is_demo=True)

    def active(self):
        return self.filter(status=SeatBase.Status.ACTIVE)


class SeatBase(models.Model):
    """Shared fields for anything that takes a limited seat and is paid via Stripe."""

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting payment"
        ACTIVE = "active", "Paid"
        EXPIRED = "expired", "Checkout expired"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True, db_index=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    amount_paid_cents = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    objects = SeatQuerySet.as_manager()

    class Meta:
        abstract = True

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE


class Enrollment(SeatBase):
    class Plan(models.TextChoices):
        FULL = "full", "Pay in full"
        INSTALMENTS = "instalments", "Monthly instalments"

    cohort = models.ForeignKey(Cohort, on_delete=models.PROTECT, related_name="enrollments")
    plan = models.CharField(max_length=12, choices=Plan.choices, default=Plan.FULL)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, db_index=True)
    instalments_paid = models.PositiveSmallIntegerField(default=0)
    payment_problem = models.BooleanField(
        default=False, help_text="Set when a monthly instalment fails. Cleared when one succeeds."
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "cohort"],
                condition=Q(status="active"),
                name="one_active_enrollment_per_cohort",
            ),
        ]

    def __str__(self):
        return f"{self.user} · {self.cohort}"

    @property
    def instalments_remaining(self):
        if self.plan != self.Plan.INSTALMENTS:
            return 0
        return max(self.cohort.program.instalment_count - self.instalments_paid, 0)


class WorkshopBooking(SeatBase):
    workshop = models.ForeignKey(Workshop, on_delete=models.PROTECT, related_name="bookings")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "workshop"],
                condition=Q(status="active"),
                name="one_active_booking_per_workshop",
            ),
        ]

    def __str__(self):
        return f"{self.user} · {self.workshop}"


class SessionCompletion(models.Model):
    """The member ticked a session off: they were there or watched the recording."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="completions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "session"], name="unique_session_completion"),
        ]


class StripeEvent(models.Model):
    """Processed webhook event ids, so a retried delivery is never applied twice."""

    event_id = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=100)
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} · {self.event_id}"


class WaitlistEntry(models.Model):
    """Someone who wants to hear when a seat opens: in a program's next group, or at a workshop."""

    program = models.ForeignKey(
        "catalog.Program", null=True, blank=True, on_delete=models.CASCADE, related_name="waitlist"
    )
    workshop = models.ForeignKey(Workshop, null=True, blank=True, on_delete=models.CASCADE, related_name="waitlist")
    email = models.EmailField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "waitlist"
        constraints = [
            models.CheckConstraint(
                condition=(Q(program__isnull=False) & Q(workshop__isnull=True))
                | (Q(program__isnull=True) & Q(workshop__isnull=False)),
                name="waitlist_for_program_or_workshop",
            ),
            models.UniqueConstraint(fields=["program", "email"], condition=Q(program__isnull=False), name="one_waitlist_entry_per_program"),
            models.UniqueConstraint(fields=["workshop", "email"], condition=Q(workshop__isnull=False), name="one_waitlist_entry_per_workshop"),
        ]

    def __str__(self):
        return f"{self.email} · {self.program or self.workshop}"


class Reflection(models.Model):
    """A member's private note on a session. Only they can see it."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="reflections")
    text = models.TextField(max_length=2000)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "session"], name="one_reflection_per_session"),
        ]

    def __str__(self):
        return f"{self.user} · {self.session}"
