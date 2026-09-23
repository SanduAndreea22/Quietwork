from django.contrib import admin, messages

from .models import Cohort, FAQItem, Program, Session, SessionTopic, Workshop
from .selectors import cohorts_with_seats, workshops_with_seats
from .templatetags.quietwork import seats_left


class SessionTopicInline(admin.TabularInline):
    model = SessionTopic
    extra = 0
    fields = ("number", "title", "summary", "exercise")


class FAQInline(admin.TabularInline):
    model = FAQItem
    extra = 0
    fields = ("question", "answer", "order", "is_published")


@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = ("question", "program", "order", "is_published")
    list_editable = ("order", "is_published")
    list_filter = ("program", "is_published")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("title", "is_published", "session_minutes", "price_full_cents", "instalment_cents", "order")
    list_editable = ("is_published", "order")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [SessionTopicInline, FAQInline]


class SessionInline(admin.TabularInline):
    model = Session
    extra = 0
    fields = ("topic", "starts_at", "duration_minutes", "recording_url", "notes")
    autocomplete_fields = ("topic",)
    ordering = ("starts_at",)


@admin.register(SessionTopic)
class SessionTopicAdmin(admin.ModelAdmin):
    search_fields = ("title", "program__title")
    list_display = ("program", "number", "title")
    list_filter = ("program",)


@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = ("__str__", "starts_at", "capacity", "seats_left_display", "is_open")
    list_filter = ("program", "is_open")
    list_select_related = ("program",)
    inlines = [SessionInline]
    actions = ["generate_sessions"]

    def get_queryset(self, request):
        return cohorts_with_seats().select_related("program")

    @admin.display(description="Seats left")
    def seats_left_display(self, obj):
        return seats_left(obj)

    @admin.action(description="Create the weekly sessions from the program's topics")
    def generate_sessions(self, request, queryset):
        created = sum(cohort.generate_sessions() for cohort in queryset.select_related("program"))
        self.message_user(request, f"{created} session(s) created.", messages.SUCCESS)


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "starts_at", "has_recording")
    list_filter = ("cohort__program", "cohort")
    list_select_related = ("cohort__program", "topic")
    fields = ("cohort", "topic", "starts_at", "duration_minutes", "recording_url", "notes")

    @admin.display(boolean=True, description="Recording")
    def has_recording(self, obj):
        return bool(obj.recording_url)


@admin.register(Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display = ("title", "starts_at", "capacity", "seats_left_display", "price_cents", "is_published")
    prepopulated_fields = {"slug": ("title",)}

    def get_queryset(self, request):
        return workshops_with_seats()

    @admin.display(description="Seats left")
    def seats_left_display(self, obj):
        return seats_left(obj)
