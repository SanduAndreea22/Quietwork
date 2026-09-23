from django.contrib import admin

from django.contrib import messages

from . import waitlist
from .models import Enrollment, SessionCompletion, StripeEvent, WaitlistEntry, WorkshopBooking

STRIPE_FIELDS = ("stripe_checkout_session_id", "stripe_customer_id", "amount_paid_cents", "paid_at", "created_at")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("user", "cohort", "plan", "status", "instalments_paid", "payment_problem", "paid_at")
    list_filter = ("status", "plan", "payment_problem", "cohort__program", "cohort")
    search_fields = ("user__email", "user__first_name", "stripe_subscription_id", "stripe_checkout_session_id")
    list_select_related = ("user", "cohort__program")
    readonly_fields = STRIPE_FIELDS + ("stripe_subscription_id", "instalments_paid", "hold_expires_at")
    raw_id_fields = ("user",)


@admin.register(WorkshopBooking)
class WorkshopBookingAdmin(admin.ModelAdmin):
    list_display = ("user", "workshop", "status", "paid_at")
    list_filter = ("status", "workshop")
    search_fields = ("user__email", "stripe_checkout_session_id")
    list_select_related = ("user", "workshop")
    readonly_fields = STRIPE_FIELDS + ("hold_expires_at",)
    raw_id_fields = ("user",)


@admin.register(SessionCompletion)
class SessionCompletionAdmin(admin.ModelAdmin):
    list_display = ("user", "session", "created_at")
    list_select_related = ("user", "session__cohort__program", "session__topic")
    raw_id_fields = ("user", "session")


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "type", "received_at")
    search_fields = ("event_id",)
    readonly_fields = ("event_id", "type", "received_at")


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ("email", "program", "workshop", "created_at", "notified_at")
    list_filter = ("program", "workshop", ("notified_at", admin.EmptyFieldListFilter))
    search_fields = ("email",)
    list_select_related = ("program", "workshop")
    readonly_fields = ("created_at", "notified_at")
    raw_id_fields = ("user",)
    actions = ["email_seat_open"]

    @admin.action(description="Email them: a seat is open (once per person)")
    def email_seat_open(self, request, queryset):
        sent = waitlist.notify(queryset)
        self.message_user(request, f"{sent} email(s) sent. People already told were skipped.", messages.SUCCESS)
