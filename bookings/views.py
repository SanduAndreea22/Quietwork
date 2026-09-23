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

from catalog.demo_content import DEMO_PROGRAM_SLUG
from catalog.models import Cohort, Program, Session, Workshop
from catalog.selectors import next_open_cohorts

from . import services, stripe_gateway, waitlist
from .calendar import calendar_response, session_events, workshop_event
from .demo import effective_now, is_demo_user
from .forms import ReflectionForm, ReserveForm, WaitlistForm
from .models import Enrollment, Reflection, SeatBase, SessionCompletion, StripeEvent, WorkshopBooking
from .progress import build_dashboard, build_session_page
from .thread_art import build_thread
from .welcome import build_welcome, find_seat

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


def _join_waitlist(request, back, **target):
    form = WaitlistForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please enter a valid email address.")
    elif not form.is_bot():
        waitlist.join(form.cleaned_data["email"], user=request.user, **target)
        messages.success(request, "You're on the list. We'll email you once, when a seat opens.")
    return redirect(back)


@require_POST
def join_program_waitlist(request, slug):
    program = get_object_or_404(Program, slug=slug, is_published=True)
    return _join_waitlist(request, program.get_absolute_url() + "#waitlist", program=program)


@require_POST
def join_workshop_waitlist(request, slug):
    workshop = get_object_or_404(Workshop, slug=slug, is_published=True)
    return _join_waitlist(request, "/#workshop", workshop=workshop)


@login_required
def my_programs(request):
    now = effective_now(request)
    context = build_dashboard(request.user, now)
    context["time_travel"] = now != context["now"] or _time_travelling(request)
    context["checkout_success"] = request.GET.get("checkout") == "success"
    return render(request, "bookings/my_programs.html", context)


@login_required
def welcome(request):
    """After Stripe Checkout. Reads the seat's state; the webhook is what confirms payment."""
    seat = find_seat(request.user, request.GET.get("session_id", ""))
    if seat is None and is_demo_user(request.user) and request.GET.get("preview"):
        # Portfolio demo: an unsaved seat in the next open group, as if Maria had just paid.
        cohort = next_open_cohorts().filter(program__slug=DEMO_PROGRAM_SLUG).select_related("program").first()
        if cohort:
            seat = Enrollment(user=request.user, cohort=cohort, plan=Enrollment.Plan.INSTALMENTS,
                              status=SeatBase.Status.ACTIVE)
    if seat is None:
        return redirect("bookings:my_programs")
    context = build_welcome(seat)
    context["demo_preview"] = is_demo_user(request.user)
    context["now_"] = timezone.now()
    return render(request, "bookings/welcome.html", context)


@login_required
def cohort_calendar(request, cohort_id):
    if is_demo_user(request.user):
        # The demo's after-payment preview shows a group Maria isn't in. Dates and
        # titles are public on the program page, and the file never holds the Zoom link.
        cohort = get_object_or_404(Cohort.objects.select_related("program"), pk=cohort_id)
    else:
        cohort = get_object_or_404(
            Enrollment.objects.active().select_related("cohort__program"), user=request.user, cohort_id=cohort_id
        ).cohort
    sessions = cohort.sessions.select_related("topic", "cohort__program").order_by("starts_at")
    return calendar_response(
        f"Quietwork · {cohort.program.title}", session_events(sessions), f"quietwork-{cohort.program.slug}.ics"
    )


@login_required
def workshop_calendar(request, slug):
    booking = get_object_or_404(
        WorkshopBooking.objects.active().select_related("workshop"), user=request.user, workshop__slug=slug
    )
    return calendar_response(
        f"Quietwork · {booking.workshop.title}", [workshop_event(booking.workshop)], f"quietwork-{slug}.ics"
    )


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
    reflection = Reflection.objects.filter(user=request.user, session=session).first()
    context["reflection_form"] = ReflectionForm(initial={"text": reflection.text if reflection else ""})
    context["reflection_saved_at"] = reflection.updated_at if reflection else None
    return render(request, "bookings/session.html", context)


@login_required
@require_POST
def save_reflection(request, session_id):
    session = _session_for_member(request.user, session_id)
    form = ReflectionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "That's a bit long: please keep it under 2000 characters.")
    elif form.cleaned_data["text"].strip():
        Reflection.objects.update_or_create(
            user=request.user, session=session, defaults={"text": form.cleaned_data["text"].strip()}
        )
        messages.success(request, "Saved. Only you can see this.")
    else:
        Reflection.objects.filter(user=request.user, session=session).delete()
    return redirect(session.get_absolute_url() + "#reflection")


def _thread_for(request, cohort_id):
    enrollment = get_object_or_404(
        Enrollment.objects.active().select_related("cohort__program"), user=request.user, cohort_id=cohort_id
    )
    cohort = enrollment.cohort
    sessions = list(cohort.sessions.select_related("topic").order_by("starts_at"))
    if not sessions:
        raise Http404
    done_ids = set(
        SessionCompletion.objects.filter(user=request.user, session__in=sessions).values_list("session_id", flat=True)
    )
    reflections = dict(
        Reflection.objects.filter(user=request.user, session__in=sessions).values_list("session_id", "text")
    )
    thread = build_thread(request.user, cohort, sessions, done_ids, reflections)
    thread["finished"] = sessions[-1].ends_at <= timezone.now()
    return cohort, thread


@login_required
def your_thread(request, cohort_id):
    cohort, thread = _thread_for(request, cohort_id)
    return render(request, "bookings/thread.html", {"cohort": cohort, "program": cohort.program, **thread})


@login_required
def your_thread_svg(request, cohort_id):
    cohort, thread = _thread_for(request, cohort_id)
    response = HttpResponse(thread["svg"], content_type="image/svg+xml; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="my-thread-{cohort.program.slug}.svg"'
    return response


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
