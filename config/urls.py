from django.contrib import admin
from django.urls import include, path

from bookings.views import stripe_webhook

admin.site.site_header = "Quietwork admin"
admin.site.site_title = "Quietwork"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("my/", include("bookings.urls")),
    path("demo/", include("bookings.demo_urls")),
    path("api/", include("config.api_urls")),
    path("stripe/webhook/", stripe_webhook, name="stripe_webhook"),
    path("", include("catalog.urls")),
]
