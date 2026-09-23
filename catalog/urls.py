from django.urls import path

from bookings.views import reserve_program, reserve_workshop

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.home, name="home"),
    path("programs/<slug:slug>/", views.program_detail, name="program"),
    path("programs/<slug:slug>/reserve/", reserve_program, name="reserve_program"),
    path("workshops/<slug:slug>/reserve/", reserve_workshop, name="reserve_workshop"),
]
