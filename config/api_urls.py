from django.urls import path

from bookings import api as bookings_api
from catalog import api as catalog_api

urlpatterns = [
    path("programs/", catalog_api.ProgramList.as_view(), name="api_programs"),
    path("cohorts/<int:pk>/availability/", catalog_api.CohortAvailability.as_view(), name="api_cohort_availability"),
    path("workshops/<slug:slug>/availability/", catalog_api.WorkshopAvailability.as_view(), name="api_workshop_availability"),
    path("me/next/", bookings_api.NextUp.as_view(), name="api_next_up"),
    path("sessions/<int:pk>/completion/", bookings_api.SessionCompletionView.as_view(), name="api_session_completion"),
]
