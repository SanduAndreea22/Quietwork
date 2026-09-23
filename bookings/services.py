"""Seat reservation and payment state changes.

Every change to seat counts runs inside a transaction that first locks the
Cohort/Workshop row with select_for_update(), so two buyers can never take
the last seat at the same time.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from catalog.models import Cohort, Workshop

from .models import Enrollment, SeatBase, WorkshopBooking

logger = logging.getLogger(__name__)


class BookingError(Exception):
    """A booking that can't go ahead, with a message safe to show the member."""


def _hold_until():
    return timezone.now() + timedelta(minutes=settings.SEAT_HOLD_MINUTES)


def _release_pending(queryset):
    """Starting a new checkout releases any seat this member was still holding.

    Returns the Stripe checkout ids of the released holds, so the caller can
    close them and they can't be paid later.
    """
    pending = queryset.filter(status=SeatBase.Status.PENDING)
    ids = [i for i in pending.values_list("stripe_checkout_session_id", flat=True) if i]
    pending.update(status=SeatBase.Status.EXPIRED)
    return ids


def reserve_cohort_seat(user, cohort_id, plan):
    """Hold a seat for checkout. Returns (enrollment, released_checkout_ids)."""
    if plan not in Enrollment.Plan.values:
        raise BookingError("Please choose how you'd like to pay.")

    with transaction.atomic():
        cohort = Cohort.objects.select_for_update().select_related("program").get(pk=cohort_id)
        if not cohort.is_bookable() or not cohort.program.is_published:
            raise BookingError("This group is no longer taking bookings.")

        mine = Enrollment.objects.filter(user=user, cohort=cohort)
        if mine.active().exists():
            raise BookingError("You already have a seat in this group.")
        released = _release_pending(mine)

        if Enrollment.objects.holding_seat().filter(cohort=cohort).count() >= cohort.capacity:
            raise BookingError("Sorry, this group is full.")

        seat = Enrollment.objects.create(
            user=user, cohort=cohort, plan=plan, hold_expires_at=_hold_until()
        )
        return seat, released


def reserve_workshop_seat(user, workshop_id):
    """Hold a workshop seat for checkout. Returns (booking, released_checkout_ids)."""
    with transaction.atomic():
        workshop = Workshop.objects.select_for_update().get(pk=workshop_id)
        if not workshop.is_bookable():
            raise BookingError("This workshop is no longer taking bookings.")

        mine = WorkshopBooking.objects.filter(user=user, workshop=workshop)
        if mine.active().exists():
            raise BookingError("You already have a seat at this workshop.")
        released = _release_pending(mine)

        if WorkshopBooking.objects.holding_seat().filter(workshop=workshop).count() >= workshop.capacity:
            raise BookingError("Sorry, this workshop is full.")

        seat = WorkshopBooking.objects.create(
            user=user, workshop=workshop, hold_expires_at=_hold_until()
        )
        return seat, released


def release_seat(seat):
    """Give back a seat whose checkout was abandoned or failed to start."""
    type(seat).objects.filter(pk=seat.pk, status=SeatBase.Status.PENDING).update(
        status=SeatBase.Status.EXPIRED
    )


def _lock(model, seat_id):
    return model.objects.select_for_update().filter(pk=seat_id).first()


def _activate(seat, duplicate_filter):
    """Mark a paid seat active. Returns False if it was a duplicate payment."""
    if seat.status == SeatBase.Status.ACTIVE:
        return True
    if duplicate_filter.exclude(pk=seat.pk).active().exists():
        # Paid twice for the same group (e.g. two checkout tabs). Keep the
        # record for a refund instead of breaking the unique constraint.
        seat.status = SeatBase.Status.CANCELLED
        logger.error("Duplicate payment for %s (id=%s): refund needed.", type(seat).__name__, seat.pk)
        return False
    if seat.status == SeatBase.Status.EXPIRED:
        logger.warning("Payment arrived for expired hold %s id=%s; seat granted.", type(seat).__name__, seat.pk)
    seat.status = SeatBase.Status.ACTIVE
    seat.paid_at = seat.paid_at or timezone.now()
    return True


def complete_checkout(checkout, cancel_subscription_now=None):
    """Handle a paid Checkout Session (payment or subscription mode).

    cancel_subscription_now(sub_id) stops a duplicate subscription straight away.
    """
    meta = checkout.get("metadata") or {}
    kind, seat_id = meta.get("kind"), meta.get("seat_id")
    customer = checkout.get("customer") or ""

    if kind == "enrollment":
        seat = _lock(Enrollment, seat_id)
        if seat is None:
            logger.error("Checkout %s refers to missing enrollment %s", checkout.get("id"), seat_id)
            return
        activated = _activate(seat, Enrollment.objects.filter(user=seat.user, cohort=seat.cohort))
        seat.stripe_checkout_session_id = checkout.get("id") or seat.stripe_checkout_session_id
        seat.stripe_customer_id = customer or seat.stripe_customer_id
        if checkout.get("mode") == "subscription":
            seat.stripe_subscription_id = checkout.get("subscription") or seat.stripe_subscription_id
            if not activated and seat.stripe_subscription_id and cancel_subscription_now:
                cancel_subscription_now(seat.stripe_subscription_id)
        elif not seat.amount_paid_cents:
            seat.amount_paid_cents = checkout.get("amount_total") or 0
        seat.save()
    elif kind == "workshop":
        seat = _lock(WorkshopBooking, seat_id)
        if seat is None:
            logger.error("Checkout %s refers to missing workshop booking %s", checkout.get("id"), seat_id)
            return
        _activate(seat, WorkshopBooking.objects.filter(user=seat.user, workshop=seat.workshop))
        seat.stripe_checkout_session_id = checkout.get("id") or seat.stripe_checkout_session_id
        seat.stripe_customer_id = customer or seat.stripe_customer_id
        if not seat.amount_paid_cents:
            seat.amount_paid_cents = checkout.get("amount_total") or 0
        seat.save()
    else:
        logger.warning("Checkout %s has unknown metadata %r", checkout.get("id"), meta)


def expire_checkout(checkout):
    meta = checkout.get("metadata") or {}
    model = {"enrollment": Enrollment, "workshop": WorkshopBooking}.get(meta.get("kind"))
    if model:
        model.objects.filter(pk=meta.get("seat_id"), status=SeatBase.Status.PENDING).update(
            status=SeatBase.Status.EXPIRED
        )


def _invoice_subscription(invoice):
    """Subscription id and metadata, across old and new Stripe API shapes."""
    details = ((invoice.get("parent") or {}).get("subscription_details")) or invoice.get(
        "subscription_details"
    ) or {}
    sub = details.get("subscription") or invoice.get("subscription") or ""
    if isinstance(sub, dict):
        sub = sub.get("id", "")
    return sub, details.get("metadata") or {}


def _enrollment_for_invoice(invoice):
    sub_id, meta = _invoice_subscription(invoice)
    seat = None
    if sub_id:
        seat = Enrollment.objects.select_for_update().filter(stripe_subscription_id=sub_id).first()
    if seat is None and meta.get("kind") == "enrollment":
        seat = _lock(Enrollment, meta.get("seat_id"))
    return seat, sub_id


def record_instalment_paid(invoice, cancel_subscription, cancel_subscription_now=None):
    """Count a paid instalment; stop the subscription once all are paid.

    The cancel callbacks run inside the transaction, so if Stripe refuses,
    the webhook fails and Stripe retries the whole event.
    """
    seat, sub_id = _enrollment_for_invoice(invoice)
    if seat is None:
        logger.info("invoice.paid for unknown subscription %s", sub_id)
        return
    activated = _activate(seat, Enrollment.objects.filter(user=seat.user, cohort=seat.cohort))
    seat.stripe_subscription_id = sub_id or seat.stripe_subscription_id
    seat.instalments_paid += 1
    seat.amount_paid_cents += invoice.get("amount_paid") or 0
    seat.payment_problem = False
    seat.save()

    if not seat.stripe_subscription_id:
        return
    if not activated and cancel_subscription_now:
        cancel_subscription_now(seat.stripe_subscription_id)
    elif seat.instalments_paid >= seat.cohort.program.instalment_count:
        cancel_subscription(seat.stripe_subscription_id)


def record_instalment_failed(invoice):
    seat, _ = _enrollment_for_invoice(invoice)
    if seat is not None:
        seat.payment_problem = True
        seat.save(update_fields=["payment_problem"])
