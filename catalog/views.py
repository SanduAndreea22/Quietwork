from django.shortcuts import get_object_or_404, render

from bookings.models import Enrollment

from . import selectors
from django.db.models import Q

from .models import FAQItem, Program


def home(request):
    return render(
        request,
        "catalog/home.html",
        {
            "programs": selectors.published_programs_with_next_cohort(),
            "workshop": selectors.next_workshop(),
        },
    )


def program_detail(request, slug):
    program = get_object_or_404(Program, slug=slug, is_published=True)
    cohort = selectors.cohort_for_program_page(program)
    already_in = False
    if cohort and request.user.is_authenticated:
        already_in = Enrollment.objects.active().filter(user=request.user, cohort=cohort).exists()
    return render(
        request,
        "catalog/program.html",
        {
            "program": program,
            "cohort": cohort,
            "sessions": sorted(cohort.session_list, key=lambda s: s.starts_at) if cohort else [],
            "already_in": already_in,
            "topic_count": program.topics.count(),
            "faq_items": FAQItem.objects.filter(Q(program=program) | Q(program__isnull=True), is_published=True),
            "cancelled": request.GET.get("checkout") == "cancelled",
        },
    )
