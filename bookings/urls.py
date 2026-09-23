from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("", views.my_programs, name="my_programs"),
    path("welcome/", views.welcome, name="welcome"),
    path("cohorts/<int:cohort_id>/calendar.ics", views.cohort_calendar, name="cohort_calendar"),
    path("workshops/<slug:slug>/calendar.ics", views.workshop_calendar, name="workshop_calendar"),
    path("sessions/<int:session_id>/", views.session_detail, name="session"),
    path("sessions/<int:session_id>/join/", views.join_session, name="join_session"),
    path("sessions/<int:session_id>/done/", views.toggle_done, name="toggle_done"),
    path("workshops/<slug:slug>/join/", views.join_workshop, name="join_workshop"),
]
