from django.urls import path

from . import demo_views

app_name = "demo"

urlpatterns = [
    path("enter/", demo_views.enter, name="enter"),
    path("time/", demo_views.toggle_time, name="time"),
    path("leave/", demo_views.leave, name="leave"),
]
