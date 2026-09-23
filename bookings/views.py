import json
import logging

import stripe
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from catalog.models import Cohort, Program, Session, Workshop

from . import services, stripe_gateway
from .demo import effective_now, is_demo_user
from .forms import ReserveForm
from .models import Enrollment, SessionCompletion, StripeEvent, WorkshopBooking
from .progress import build_dashboard, build_session_page

logger = logging.getLogger(__name__)


DEMO_NO_PAYMENT = (
    "This is a demo account, so no payment is taken. "
    "Exit the demo and create an account to try the Stripe checkout in test mode."
)


def _start_checkout(request, seat, released, create_checkout, back_url):
    for checkout_id in released:
        stripe_gateway.expire_checkout_session(checkout_id)
    try:
        checkout = create_checkout(seat)
    except (stripe.StripeError, stripe_gateway.PaymentsNotConfigured):
        logger.exception("Could not start checkout for %s id=%s", type(seat).__name__, seat.pk)
        services.release_seat(seat)
        messages.error(request, "Payments are not available right now. Please try again in a few minutes.")
        return redirect(back_url)
    seat.stripe_checkout_session_id = checkout.id
    seat.save(update_fields=["stripe_checkout_session_id"])
    return redirect(checkout.url, permanent=False)


@login_required
@require_POST
def reserve_program(request, slug):
    program = get_object_or_404(Program, slug=slug, is_published=True)
    if is_demo_user(request.user):
        messages.info(request, DEMO_NO_PAYMENT)
        return redirect(program)
    form = ReserveForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please choose how you'd like to pay.")
        return redirect(program)
    cohort = get_object_or_404(Cohort, pk=form.cleaned_data["cohort"], program=program)
    try:
        seat, released = services.reserve_cohort_seat(request.user, cohort.pk, form.cleaned_data["plan"])
    except services.BookingError as exc:
        messages.error(request, str(exc))
        return redirect(program)
    return _start_checkout(
        request, seat, released, stripe_gateway.create_enrollment_checkout, program.get_absolute_url()
    )


@login_required
@require_POST
def reserve_workshop(request, slug):
    workshop = get_object_or_404(Workshop, slug=slug, is_published=True)
    if is_demo_user(request.user):
        messages.info(request, DEMO_NO_PAYMENT)
        return redirect("/#workshop")
    try:
        seat, released = services.reserve_workshop_seat(request.user, workshop.pk)
    except services.BookingError as exc:
        messages.error(request, str(exc))
        return redirect("/#workshop")
    return _start_checkout(request, seat, released, stripe_gateway.create_workshop_checkout, "/#workshop")


@login_required
def my_programs(request):
    now = effective_now(request)
    context = build_dashboard(request.user, now)
    context["time_travel"] = now != context["now"] or _time_travelling(request)
    context["checkout_success"] = request.GET.get("checkout") == "success"
    return render(request, "bookings/my_programs.html", context)


def _time_travelling(request):
    from .demo import SESSION_KEY

    return is_demo_user(request.user) and bool(request.session.get(SESSION_KEY))


def _session_for_member(user, session_id):
    session = get_object_or_404(Session.objects.select_related("cohort__program", "topic"), pk=session_id)
    if not Enrollment.objects.active().filter(user=user, cohort=session.cohort).exists():
        raise Http404
    return session


@login_required
def session_detail(request, session_id):
    session = _session_for_member(request.user, session_id)
    context = build_session_page(request.user, session, effective_now(request))
    context["time_travel"] = _time_travelling(request)
    context["just_done"] = request.session.pop("just_done", None)
    return render(request, "bookings/session.html", context)


@login_required
def join_session(request, session_id):
    """Redirect to Zoom, but only for paid members and only in the join window."""
    session = _session_for_member(request.user, session_id)
    if session.is_joinable(effective_now(request)) and session.cohort.zoom_url:
        if is_demo_user(request.user):
            return render(request, "bookings/demo_join.html", {"title": f"Session {session.number}: {session.title}", "back": session.get_absolute_url()})
        return redirect(session.cohort.zoom_url)
    messages.info(request, f"The Zoom link opens at {timezone.localtime(session.join_opens_at):%H:%M}.")
    return redirect(session)


@login_required
def join_workshop(request, slug):
    workshop = get_object_or_404(Workshop, slug=slug)
    if not WorkshopBooking.objects.active().filter(user=request.user, workshop=workshop).exists():
        raise Http404
    if workshop.is_joinable() and workshop.zoom_url:
        if is_demo_user(request.user):
            return render(request, "bookings/demo_join.html", {"title": workshop.title, "back": reverse("bookings:my_programs")})
        return redirect(workshop.zoom_url)
    messages.info(request, f"The Zoom link opens at {timezone.localtime(workshop.join_opens_at):%H:%M}.")
    return redirect("bookings:my_programs")


@login_required
@require_POST
def toggle_done(request, session_id):
    session = _session_for_member(request.user, session_id)
    if not session.has_started():
        messages.info(request, "You can tick a session off once it has started.")
    elif request.POST.get("done") == "1":
        SessionCompletion.objects.get_or_create(user=request.user, session=session)
        request.session["just_done"] = session.pk  # the thread animates to it once
    else:
        SessionCompletion.objects.filter(user=request.user, session=session).delete()
    back = request.POST.get("back", "")
    if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        return redirect(back)
    return redirect(session)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    try:
        stripe_gateway.construct_event(payload, request.headers.get("Stripe-Signature", ""))
    except stripe_gateway.PaymentsNotConfigured:
        logger.error("Stripe webhook received but STRIPE_WEBHOOK_SECRET is not set.")
        return HttpResponse(status=503)
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponseBadRequest("Invalid signature")

    # Signature verified: work with plain dicts from here on.
    event = json.loads(payload)
    obj = event["data"]["object"]

    with transaction.atomic():
        try:
            with transaction.atomic():
                StripeEvent.objects.create(event_id=event["id"], type=event["type"])
        except IntegrityError:
            # Already processed this event id: Stripe retried a delivery.
            return HttpResponse(status=200)
        # Any error here rolls back the event record too, so Stripe retries it.
        _dispatch(event["type"], obj)
    return HttpResponse(status=200)


def _dispatch(event_type, obj):
    if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        if obj.get("payment_status") in ("paid", "no_payment_required"):
            services.complete_checkout(obj, stripe_gateway.cancel_subscription_now)
    elif event_type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
        services.expire_checkout(obj)
    elif event_type == "invoice.paid":
        services.record_instalment_paid(
            obj, stripe_gateway.stop_subscription_after_current_period, stripe_gateway.cancel_subscription_now
        )
    elif event_type == "invoice.payment_failed":
        services.record_instalment_failed(obj)
