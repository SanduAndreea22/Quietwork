"""iCalendar (.ics) files, so a member's own calendar does the reminding.

The Zoom link is never written into the file: each event points to the
session page, where the server checks access and opens the link on time.
"""

from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

PRODID = "-//Andreea Tech//Quietwork//EN"


def _escape(text):
    return (
        str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    )


def _fold(line):
    """Lines longer than 75 octets continue on the next line after a space (RFC 5545)."""
    data = line.encode("utf-8")
    if len(data) <= 75:
        return line
    parts, chunk = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        if len(chunk) + len(encoded) > (75 if not parts else 74):
            parts.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += encoded
    parts.append(chunk.decode("utf-8"))
    return "\r\n ".join(parts)


def _stamp(dt):
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def event(uid, starts_at, ends_at, summary, description, url):
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_stamp(timezone.now())}",
        f"DTSTART:{_stamp(starts_at)}",
        f"DTEND:{_stamp(ends_at)}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(description)}",
        f"URL:{url}",
        "LOCATION:Online · Zoom (link in your Quietwork account)",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape(summary)}",
        f"TRIGGER:-PT{settings.JOIN_OPENS_MINUTES_BEFORE}M",
        "END:VALARM",
        "END:VEVENT",
    ]


def calendar_response(name, events, filename):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_escape(name)}"]
    for ev in events:
        lines.extend(ev)
    lines.append("END:VCALENDAR")
    body = "\r\n".join(_fold(line) for line in lines) + "\r\n"
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def session_events(sessions):
    for s in sessions:
        page = settings.SITE_URL + s.get_absolute_url()
        yield event(
            uid=f"session-{s.pk}@quietwork",
            starts_at=s.starts_at,
            ends_at=s.ends_at,
            summary=f"Quietwork · Session {s.number}: {s.title}",
            description=(
                f"{s.cohort.program.title}, {s.cohort.name}.\n"
                f"Join from your session page: {page}\n"
                f"The Zoom button opens {settings.JOIN_OPENS_MINUTES_BEFORE} minutes before the start."
            ),
            url=page,
        )


def workshop_event(workshop):
    page = settings.SITE_URL + "/my/"
    return event(
        uid=f"workshop-{workshop.pk}@quietwork",
        starts_at=workshop.starts_at,
        ends_at=workshop.starts_at + timedelta(minutes=workshop.duration_minutes),
        summary=f"Quietwork · {workshop.title}",
        description=(
            f"Join from My programs: {page}\n"
            f"The Zoom button opens {settings.JOIN_OPENS_MINUTES_BEFORE} minutes before the start."
        ),
        url=page,
    )
