"""The page people land on after paying: their seat, the group, the first session.

It only reads state. A seat becomes paid through the signed Stripe webhook,
never because someone opened this URL.
"""

from dataclasses import dataclass

from .models import Enrollment, SeatBase, WorkshopBooking


@dataclass
class SeatDot:
    taken: bool
    mine: bool


def seat_dots(capacity, others, my_position):
    """One dot per seat: mine, the other paid seats, then the free ones."""
    dots, filled = [], 0
    for i in range(1, capacity + 1):
        if i == my_position:
            dots.append(SeatDot(taken=True, mine=True))
        elif filled < others:
            dots.append(SeatDot(taken=True, mine=False))
            filled += 1
        else:
            dots.append(SeatDot(taken=False, mine=False))
    return dots


def _position(queryset, seat):
    """Where this member's seat falls among the paid seats (1-based)."""
    ids = list(
        queryset.active().exclude(user__is_demo=True).order_by("paid_at", "pk").values_list("pk", flat=True)
    )
    if seat.pk in ids:
        return ids.index(seat.pk) + 1, len(ids)
    # Demo previews don't hold a real seat: show them as the next one.
    return len(ids) + 1, len(ids) + 1


def find_seat(user, checkout_id):
    """The member's own Enrollment or WorkshopBooking for a Checkout Session."""
    if not checkout_id:
        return None
    for model in (Enrollment, WorkshopBooking):
        seat = model.objects.filter(user=user, stripe_checkout_session_id=checkout_id).first()
        if seat:
            return seat
    return None


def build_welcome(seat):
    is_program = isinstance(seat, Enrollment)
    context = {
        "seat": seat,
        "is_program": is_program,
        "confirmed": seat.status == SeatBase.Status.ACTIVE,
        "still_pending": seat.status == SeatBase.Status.PENDING,
    }
    if is_program:
        cohort = seat.cohort
        sessions = list(cohort.sessions.select_related("topic").order_by("starts_at"))
        position, taken = _position(Enrollment.objects.filter(cohort=cohort), seat)
        context.update(
            program=cohort.program,
            cohort=cohort,
            sessions=sessions,
            first_session=sessions[0] if sessions else None,
            capacity=cohort.capacity,
        )
    else:
        workshop = seat.workshop
        position, taken = _position(WorkshopBooking.objects.filter(workshop=workshop), seat)
        context.update(workshop=workshop, capacity=workshop.capacity)
    position = min(position, context["capacity"])
    context.update(
        position=position,
        taken=min(taken, context["capacity"]),
        dots=seat_dots(context["capacity"], min(taken, context["capacity"]) - 1, position),
    )
    return context
