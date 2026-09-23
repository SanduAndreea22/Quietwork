"""View models for the member area: My programs and the Session page."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Prefetch
from django.urls import reverse
from django.utils import timezone

from catalog.models import Session
from catalog.selectors import next_open_cohorts

from .models import Enrollment, SeatBase, SessionCompletion, WorkshopBooking


@dataclass
class ThreadNode:
    session: Session
    done: bool
    is_next: bool


@dataclass
class ProgramProgress:
    enrollment: Enrollment
    nodes: list = field(default_factory=list)
    next_session: Session | None = None

    @property
    def cohort(self):
        return self.enrollment.cohort

    @property
    def program(self):
        return self.enrollment.cohort.program

    @property
    def total(self):
        return len(self.nodes)

    @property
    def done_count(self):
        return sum(node.done for node in self.nodes)

    @property
    def finished(self):
        return self.next_session is None and self.total > 0

    @property
    def done_percent(self):
        return round(100 * self.done_count / self.total) if self.total else 0

    @property
    def thread_fill(self):
        """How far the blue thread runs along the horizontal line (0 to 1)."""
        if self.total < 2 or not self.done_count:
            return "0"
        last_done = max(i for i, node in enumerate(self.nodes) if node.done)
        return f"{last_done / (self.total - 1):.3f}"

    @property
    def open_url(self):
        """The session a member most likely wants: the next one, else the last."""
        target = self.next_session or (self.nodes[-1].session if self.nodes else None)
        return target.get_absolute_url() if target else ""


@dataclass
class NextUp:
    kind: str  # "session" | "workshop"
    starts_at: datetime
    opens_at: datetime
    title: str
    subtitle: str
    duration_minutes: int
    join_url: str
    page_url: str
    joinable: bool


def countdown(target, now=None):
    now = now or timezone.now()
    seconds = max(int((target - now).total_seconds()), 0)
    days, rest = divmod(seconds, 86400)
    return {"days": days, "hours": rest // 3600, "minutes": (rest % 3600) // 60}


def _completed_ids(user, sessions):
    return set(
        SessionCompletion.objects.filter(user=user, session__in=sessions).values_list(
            "session_id", flat=True
        )
    )


def _progress_for(enrollments, user, now):
    all_sessions = [s for e in enrollments for s in e.cohort.session_list]
    done_ids = _completed_ids(user, all_sessions)
    result = []
    for enrollment in enrollments:
        sessions = sorted(enrollment.cohort.session_list, key=lambda s: s.starts_at)
        upcoming = next((s for s in sessions if s.ends_at > now), None)
        progress = ProgramProgress(enrollment=enrollment, next_session=upcoming)
        progress.nodes = [
            ThreadNode(session=s, done=s.pk in done_ids, is_next=upcoming is not None and s.pk == upcoming.pk)
            for s in sessions
        ]
        result.append(progress)
    return result


def build_dashboard(user, now=None):
    now = now or timezone.now()
    enrollments = list(
        Enrollment.objects.active()
        .filter(user=user)
        .select_related("cohort__program")
        .prefetch_related(
            Prefetch(
                "cohort__sessions",
                queryset=Session.objects.select_related("topic").order_by("starts_at"),
                to_attr="session_list",
            )
        )
        .order_by("cohort__starts_at")
    )
    programs = _progress_for(enrollments, user, now)
    current = [p for p in programs if not p.finished]
    finished = [p for p in programs if p.finished]

    workshops = list(
        WorkshopBooking.objects.active()
        .filter(user=user, workshop__starts_at__gt=now - timedelta(hours=3))
        .select_related("workshop")
        .order_by("workshop__starts_at")
    )
    workshops = [b for b in workshops if b.workshop.ends_at > now]

    candidates = []
    for p in current:
        s = p.next_session
        candidates.append(
            NextUp(
                kind="session",
                starts_at=s.starts_at,
                opens_at=s.join_opens_at,
                title=f"Session {s.number}: {s.title}",
                subtitle=p.program.title,
                duration_minutes=s.duration_minutes,
                join_url=reverse("bookings:join_session", args=[s.pk]),
                page_url=s.get_absolute_url(),
                joinable=s.is_joinable(now),
            )
        )
    for b in workshops:
        w = b.workshop
        candidates.append(
            NextUp(
                kind="workshop",
                starts_at=w.starts_at,
                opens_at=w.join_opens_at,
                title=w.title,
                subtitle="Live workshop",
                duration_minutes=w.duration_minutes,
                join_url=reverse("bookings:join_workshop", args=[w.slug]),
                page_url="",
                joinable=w.is_joinable(now),
            )
        )
    next_up = min(candidates, key=lambda c: c.starts_at, default=None)

    pending = (
        Enrollment.objects.filter(
            user=user, status=SeatBase.Status.PENDING, hold_expires_at__gt=now
        ).select_related("cohort__program")
    )

    enrolled_program_ids = {e.cohort.program_id for e in enrollments}
    suggestion_cohort = (
        next_open_cohorts(now)
        .filter(program__is_published=True)
        .exclude(program_id__in=enrolled_program_ids)
        .select_related("program")
        .first()
    )

    return {
        "now": now,
        "next_up": next_up,
        "next_up_countdown": countdown(next_up.starts_at, now) if next_up else None,
        "current_programs": current,
        "finished_programs": finished,
        "workshop_bookings": workshops,
        "pending_enrollments": list(pending),
        "suggestion": suggestion_cohort,
        "has_anything": bool(programs or workshops),
        "join_opens_minutes": settings.JOIN_OPENS_MINUTES_BEFORE,
    }


def build_session_page(user, session, now=None):
    now = now or timezone.now()
    sessions = list(
        session.cohort.sessions.select_related("topic").order_by("starts_at")
    )
    done_ids = _completed_ids(user, sessions)
    upcoming = next((s for s in sessions if s.ends_at > now), None)
    index = next(i for i, s in enumerate(sessions) if s.pk == session.pk)
    previous = sessions[index - 1] if index > 0 else None
    following = sessions[index + 1] if index + 1 < len(sessions) else None
    is_upcoming = session.ends_at > now

    nodes = [
        ThreadNode(session=s, done=s.pk in done_ids, is_next=upcoming is not None and s.pk == upcoming.pk)
        for s in sessions
    ]
    return {
        "now": now,
        "session": session,
        "cohort": session.cohort,
        "program": session.cohort.program,
        "nodes": nodes,
        "done_count": len(done_ids),
        "total": len(sessions),
        "is_upcoming": is_upcoming,
        "is_today": timezone.localdate(session.starts_at) == timezone.localdate(now),
        "joinable": session.is_joinable(now),
        "countdown": countdown(session.starts_at, now) if is_upcoming else None,
        "is_done": session.pk in done_ids,
        "can_mark_done": session.has_started(now),
        # For an upcoming session, show last session's recording and notes;
        # for a past one, show its own.
        "recap": previous if is_upcoming else session,
        "recap_done": (previous.pk in done_ids) if (is_upcoming and previous) else session.pk in done_ids,
        "previous": previous,
        "following": following,
    }
