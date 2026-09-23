"""Waitlist: join from a sold-out page; Elena emails everyone from the admin when a seat opens."""

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import WaitlistEntry


def join(email, *, program=None, workshop=None, user=None):
    """Add an email to the list. Joining twice is fine. Returns the entry."""
    target = {"program": program} if program else {"workshop": workshop}
    try:
        with transaction.atomic():
            entry, _ = WaitlistEntry.objects.get_or_create(
                email=email, **target, defaults={"user": user if user and user.is_authenticated else None}
            )
    except IntegrityError:  # two submits at once
        entry = WaitlistEntry.objects.get(email=email, **target)
    return entry


def notify(entries):
    """Email each person that a seat is open. Skips demo accounts and people already told."""
    sent = 0
    for entry in entries.select_related("program", "workshop", "user").filter(notified_at__isnull=True):
        if (entry.user_id and entry.user.is_demo) or entry.email.endswith(".invalid"):
            continue
        if entry.program:
            name, link = entry.program.title, settings.SITE_URL + entry.program.get_absolute_url()
        else:
            name, link = entry.workshop.title, settings.SITE_URL + "/#workshop"
        send_mail(
            subject=f"A seat is open: {name}",
            message=(
                f"Hi,\n\nYou asked to hear when a seat opens in {name}. There is one now:\n\n{link}\n\n"
                "Seats go to whoever books first, so if you'd like it, have a look soon.\n\n"
                "Elena · Quietwork\n\n"
                "You're getting this one email because you joined the waitlist. There won't be others."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[entry.email],
        )
        entry.notified_at = timezone.now()
        entry.save(update_fields=["notified_at"])
        sent += 1
    return sent
