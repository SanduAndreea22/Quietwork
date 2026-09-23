"""The only module that talks to Stripe."""

import time

import stripe
from django.conf import settings
from django.urls import reverse

from .models import Enrollment


class PaymentsNotConfigured(Exception):
    pass


def _client():
    if not settings.STRIPE_SECRET_KEY:
        raise PaymentsNotConfigured("STRIPE_SECRET_KEY is not set.")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def _url(name, *args):
    return settings.SITE_URL + reverse(name, args=args)


def _expires_at():
    return int(time.time()) + settings.CHECKOUT_TTL_MINUTES * 60


def create_enrollment_checkout(enrollment):
    s = _client()
    program = enrollment.cohort.program
    metadata = {"kind": "enrollment", "seat_id": str(enrollment.pk)}
    name = f"{program.title} · {enrollment.cohort.name}"
    params = {
        "customer_email": enrollment.user.email,
        "client_reference_id": str(enrollment.user.pk),
        "metadata": metadata,
        "expires_at": _expires_at(),
        "success_url": _url("bookings:welcome") + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": _url("catalog:program", program.slug) + "?checkout=cancelled",
    }
    if enrollment.plan == Enrollment.Plan.INSTALMENTS:
        params.update(
            mode="subscription",
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": settings.STRIPE_CURRENCY,
                    "unit_amount": program.instalment_cents,
                    "recurring": {"interval": "month"},
                    "product_data": {"name": f"{name} (monthly instalment)"},
                },
            }],
            subscription_data={"metadata": metadata},
        )
    else:
        params.update(
            mode="payment",
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": settings.STRIPE_CURRENCY,
                    "unit_amount": program.price_full_cents,
                    "product_data": {"name": name},
                },
            }],
            payment_intent_data={"metadata": metadata},
        )
    return s.checkout.Session.create(**params)


def create_workshop_checkout(booking):
    s = _client()
    workshop = booking.workshop
    metadata = {"kind": "workshop", "seat_id": str(booking.pk)}
    return s.checkout.Session.create(
        mode="payment",
        customer_email=booking.user.email,
        client_reference_id=str(booking.user.pk),
        metadata=metadata,
        payment_intent_data={"metadata": metadata},
        expires_at=_expires_at(),
        line_items=[{
            "quantity": 1,
            "price_data": {
                "currency": settings.STRIPE_CURRENCY,
                "unit_amount": workshop.price_cents,
                "product_data": {"name": f"{workshop.title} · {workshop.starts_at:%d %B %Y}"},
            },
        }],
        success_url=_url("bookings:welcome") + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=_url("catalog:home") + "?checkout=cancelled#workshop",
    )


def expire_checkout_session(session_id):
    """Best effort: close an abandoned checkout so it can't be paid later."""
    if not session_id:
        return
    try:
        _client().checkout.Session.expire(session_id)
    except (stripe.StripeError, PaymentsNotConfigured):
        pass


def stop_subscription_after_current_period(subscription_id):
    _client().Subscription.modify(subscription_id, cancel_at_period_end=True)


def cancel_subscription_now(subscription_id):
    """Stop a duplicate subscription at once. The payment already taken is refunded by hand."""
    s = _client()
    try:
        s.Subscription.cancel(subscription_id)
    except stripe.InvalidRequestError:
        # Cancelling twice is an error in Stripe; a retried webhook must not fail on it.
        if s.Subscription.retrieve(subscription_id).status != "canceled":
            raise


def construct_event(payload, signature):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise PaymentsNotConfigured("STRIPE_WEBHOOK_SECRET is not set.")
    return stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
