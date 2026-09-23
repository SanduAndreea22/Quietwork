"""Demo content for the portfolio: Elena's three programs, their groups and the workshop.

Dates are relative to today, so the demo always has an open group, a group
that is half-way through, a finished one and an upcoming workshop. Every
function here is safe to run again.
"""

from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from catalog.models import Cohort, FAQItem, Program, SessionTopic, Workshop

PROGRAMS = [
    {
        "slug": "small-habits-real-change",
        "summaries": ['Why most new routines fade after a few days, and why that says nothing about you.', 'Shrinking a habit until it fits a tired Tuesday.', 'Tying the new habit to something you already do every day.', "What to do on the days it doesn't happen, without starting over.", 'Looking honestly at what gets in the way, one obstacle at a time.', 'When the first habit holds, choosing a second one carefully.', 'Keeping routines when holidays, illness or a new job change your week.', 'A plan for carrying on alone after the group ends.'],
        "title": "Small Habits, Real Change",
        "tagline": "Build routines that stay with you after the first enthusiastic week.",
        "description": "For people who start strong and lose the thread by week two. Eight weeks with a small group, building one small routine at a time and learning what to do on the days it doesn't happen.",
        "outcomes": "Pick one habit small enough to keep on a bad day\nTie it to something you already do\nNotice what gets in the way without blaming yourself\nPick it back up after a missed day",
        "photo_caption": "hands writing a list",
        "weekday": 1,  # Tuesday
        "topics": [
            "Why the first week is the easy part", "Making it smaller", "Where it fits in your day",
            "The days it doesn't happen", "What gets in the way", "Adding a second habit",
            "When life changes shape", "Keeping it going on your own",
        ],
    },
    {
        "slug": "boundaries-without-guilt",
        "summaries": ["Noticing the yes that comes out before you've had time to think.", 'Counting what each yes takes from your time, energy and mood.', 'Practising a short, clear no out loud, in pairs.', 'Buying time with "Let me check" so you can decide calmly.', None, "Staying steady when someone doesn't like your answer.", 'What to do with the guilt that shows up after a no.', 'Writing your own few rules for what you say yes to from here on.'],
        "title": "Boundaries Without Guilt",
        "tagline": "Learn to say no to what drains you, without the guilt that usually follows.",
        "description": "For people who say yes too often and pay for it later. Eight weeks with a small group, noticing what drains you, saying no clearly, and handling the guilt that shows up afterwards.",
        "outcomes": "Spot the moments you agree before you have thought it through\nSay no in one or two clear sentences\nHandle pushback without over-explaining\nSit with the guilt afterwards instead of taking it back",
        "photo_caption": "an open door, soft light",
        "weekday": 2,  # Wednesday
        "topics": [
            "The automatic yes", "What each yes costs you", "A no you can say out loud",
            'Buying time: "Let me check"', "No without the long explanation", "When people push back",
            "Sitting with the guilt", "Your own rules, from here on",
        ],
        "details": {
            5: (
                "Most of us explain a no because we feel we have to earn it. In this session we practise saying it in one sentence, then stopping, first in pairs, then with the whole group.\n\nBring one real request from this week. We'll use them as the examples.",
                "Write down one no you gave with a long explanation. Rewrite it as a single sentence and bring both versions.",
            ),
        },
    },
    {
        "slug": "quiet-confidence",
        "summaries": ["Why being quiet isn't the thing to fix.", 'Listing what you already do well, with evidence.', 'Speaking first, once, in a setting that feels safe enough.', 'Saying what you think without the apology in front of it.', 'Taking up a little more room in meetings and conversations.', 'Disagreeing calmly and staying in the conversation.', 'Making a decision without checking it with everyone first.', 'How to keep practising after the eight weeks.'],
        "title": "Quiet Confidence",
        "tagline": "Trust yourself more, without having to be the loudest person in the room.",
        "description": "For people who know more than they say. Eight weeks with a small group, practising speaking up in ways that still feel like you.",
        "outcomes": "Say what you think in meetings, in your own words\nStop rehearsing conversations for days\nTake a compliment without brushing it off\nMake a decision and let it stand",
        "photo_caption": "a person walking alone, morning",
        "weekday": 3,  # Thursday
        "topics": [
            "Quiet is not the problem", "What you already do well", "Speaking first, once",
            "Saying it without the apology", "Taking up a little more space", "Disagreeing calmly",
            "Deciding without asking everyone", "Carrying it on",
        ],
    },
]


def _next_weekday(from_date, weekday, min_days_ahead):
    day = from_date + timedelta(days=min_days_ahead)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day


def _at_19(day):
    return timezone.make_aware(datetime.combine(day, time(19, 0)))


# Starting FAQ, shown on every program. Elena edits these in the admin.
FAQ = [
    ("What if I miss a session?",
     "Every session is recorded. The recording appears in your account the next day, with Elena's notes and the week's exercise, so you can catch up before the next one."),
    ("Do I need to have my camera on?",
     "It's welcome, not required. Plenty of people listen for the first week or two and join in when they're ready."),
    ("How big is the group?",
     "Up to twelve people, the same group for all eight weeks. Small on purpose, so there is time for everyone."),
    ("What do I need?",
     "A laptop or phone with Zoom, a quiet corner for 75 minutes, and something to write in."),
    ("Is this therapy?",
     "No. These are practice groups, not therapy. If you are going through something heavy, please talk to a professional first."),
]

DEMO_PROGRAM_SLUG = "boundaries-without-guilt"
FINISHED_PROGRAM_SLUG = "small-habits-real-change"
ZOOM_PLACEHOLDER = "https://zoom.us/j/0000000000"

# Sample notes for the group that is half-way through (fictional teacher).
SAMPLE_NOTES = {
    1: "We noticed how fast the yes comes: most of us agree before the other person has finished the sentence. This week, just notice it. No need to change anything yet.",
    2: "Your lists of drains were longer than most of you expected. Keep yours somewhere you will see it.\n\nThe phrase to keep: \"Every yes is a no to something else.\"",
    3: "Short is kinder than it feels. Two of you said a no out loud for the first time, and the room stayed calm.",
    4: "\"Let me check and come back to you\" buys you the time to decide. Try it once this week, even for something small.",
}


def running_cohorts(now=None):
    """Groups that have started and still have a session to come."""
    now = now or timezone.now()
    return (
        Cohort.objects.filter(starts_at__lte=now)
        .annotate(last_start=Max("sessions__starts_at"))
        .filter(last_start__gt=now)
    )


def finished_cohorts(now=None):
    now = now or timezone.now()
    return (
        Cohort.objects.annotate(last_start=Max("sessions__starts_at"))
        .filter(last_start__lt=now - timedelta(days=1))
    )


def _create_cohort(program, start_day, is_open):
    cohort = Cohort.objects.create(
        program=program, name=f"{start_day:%B} group", starts_at=_at_19(start_day),
        zoom_url=ZOOM_PLACEHOLDER, is_open=is_open,
    )
    cohort.generate_sessions()
    return cohort


@transaction.atomic
def ensure_demo_content(refresh=False):
    """Create what's missing. With refresh=True, also overwrite the program texts
    (seed_demo does that; entering the demo never does, so admin edits survive)."""
    now = timezone.now()
    today = timezone.localdate()
    save = Program.objects.update_or_create if refresh else Program.objects.get_or_create
    save_topic = SessionTopic.objects.update_or_create if refresh else SessionTopic.objects.get_or_create
    for order, data in enumerate(PROGRAMS):
        program, _ = save(
            slug=data["slug"],
            defaults={
                "title": data["title"], "tagline": data["tagline"], "description": data["description"],
                "outcomes": data["outcomes"], "photo_caption": data["photo_caption"], "order": order,
            },
        )
        details = data.get("details", {})
        summaries = data.get("summaries", [])
        for number, title in enumerate(data["topics"], start=1):
            summary, exercise = details.get(number, (summaries[number - 1] or "", ""))
            save_topic(
                program=program, number=number,
                defaults={"title": title, "summary": summary, "exercise": exercise},
            )

        if not program.cohorts.filter(starts_at__gt=now, is_open=True).exists():
            _create_cohort(program, _next_weekday(today, data["weekday"], 21), is_open=True)

        # A group half-way through, so the member area has something to show.
        if not running_cohorts(now).filter(program=program).exists():
            cohort = _create_cohort(program, _next_weekday(today - timedelta(weeks=4), data["weekday"], 0), is_open=False)
            if program.slug == DEMO_PROGRAM_SLUG:
                for session in cohort.sessions.select_related("topic"):
                    if session.topic.number in SAMPLE_NOTES and session.starts_at < now:
                        session.notes = SAMPLE_NOTES[session.topic.number]
                        session.save(update_fields=["notes"])

        if program.slug == FINISHED_PROGRAM_SLUG and not finished_cohorts(now).filter(program=program).exists():
            _create_cohort(program, _next_weekday(today - timedelta(weeks=14), data["weekday"], 0), is_open=False)

    if not FAQItem.objects.exists():
        FAQItem.objects.bulk_create(
            [FAQItem(question=q, answer=a, order=i) for i, (q, a) in enumerate(FAQ)]
        )

    if not Workshop.objects.filter(starts_at__gt=now, is_published=True).exists():
        day = _next_weekday(today, 3, 8)
        Workshop.objects.create(
            title="Boundaries Without Guilt — Live",
            slug=f"boundaries-live-{day:%Y-%m-%d}",
            description="Ninety minutes with Elena and a small group. You practise real conversations, ask your own questions and leave with a plan for the week ahead. A good first step if you are not sure about eight weeks yet.",
            starts_at=timezone.make_aware(datetime.combine(day, time(18, 30))),
            zoom_url=ZOOM_PLACEHOLDER,
        )
