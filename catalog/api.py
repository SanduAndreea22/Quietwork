from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import selectors
from .models import Program
from .templatetags.quietwork import seats_left


class CohortSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    starts_at = serializers.DateTimeField()
    capacity = serializers.IntegerField()
    seats_left = serializers.SerializerMethodField()

    def get_seats_left(self, cohort):
        return seats_left(cohort)


class ProgramSerializer(serializers.ModelSerializer):
    next_cohort = CohortSummarySerializer(allow_null=True)

    class Meta:
        model = Program
        fields = [
            "title", "slug", "tagline", "session_minutes",
            "price_full_cents", "instalment_cents", "instalment_count", "next_cohort",
        ]


class ProgramList(generics.ListAPIView):
    """Published programs with their next open group."""

    permission_classes = [AllowAny]
    serializer_class = ProgramSerializer
    pagination_class = None

    def get_queryset(self):
        return selectors.published_programs_with_next_cohort()


def _availability(obj):
    return {
        "capacity": obj.capacity,
        "seats_left": seats_left(obj),
        "is_bookable": obj.is_bookable() and seats_left(obj) > 0,
    }


class CohortAvailability(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        cohort = get_object_or_404(selectors.cohorts_with_seats().filter(program__is_published=True), pk=pk)
        return Response(_availability(cohort))


class WorkshopAvailability(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        workshop = get_object_or_404(selectors.workshops_with_seats().filter(is_published=True), slug=slug)
        return Response(_availability(workshop))
