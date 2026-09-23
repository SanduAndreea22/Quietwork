from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Session

from .models import Enrollment, SessionCompletion
from .progress import build_dashboard


class NextUp(APIView):
    """The member's next live session or workshop. The Zoom link is never included."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        item = build_dashboard(request.user)["next_up"]
        if item is None:
            return Response({"next_up": None})
        return Response({
            "next_up": {
                "kind": item.kind,
                "title": item.title,
                "subtitle": item.subtitle,
                "starts_at": item.starts_at,
                "duration_minutes": item.duration_minutes,
                "joinable": item.joinable,
                "join_url": request.build_absolute_uri(item.join_url),
            }
        })


class SessionCompletionView(APIView):
    """PUT marks a session as done, DELETE un-marks it."""

    permission_classes = [IsAuthenticated]

    def _session(self, request, pk):
        session = get_object_or_404(Session.objects.select_related("cohort"), pk=pk)
        if not Enrollment.objects.active().filter(user=request.user, cohort=session.cohort).exists():
            raise Http404
        return session

    def put(self, request, pk):
        session = self._session(request, pk)
        if not session.has_started():
            return Response({"detail": "This session hasn't started yet."}, status=status.HTTP_400_BAD_REQUEST)
        SessionCompletion.objects.get_or_create(user=request.user, session=session)
        return Response({"done": True})

    def delete(self, request, pk):
        session = self._session(request, pk)
        SessionCompletion.objects.filter(user=request.user, session=session).delete()
        return Response({"done": False})
