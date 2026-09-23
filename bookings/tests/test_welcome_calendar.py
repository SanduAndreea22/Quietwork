from datetime import timedelta, timezone as dt_timezone
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bookings import stripe_gateway
from bookings.calendar import _fold
from bookings.models import Enrollment, SeatBase, WorkshopBooking

from .factories import make_cohort, make_user, make_workshop


class CalendarTests(TestCase):
    def setUp(self):
        self.cohort = make_cohort()
        self.user = make_user()
        self.client.force_login(self.user)

    def test_member_gets_all_sessions_without_the_zoom_link(self):
        Enrollment.objects.create(user=self.user, cohort=self.cohort, status=SeatBase.Status.ACTIVE)
        response = self.client.get(reverse("bookings:cohort_calendar", args=[self.cohort.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        body = response.content.decode()
        self.assertEqual(body.count("BEGIN:VEVENT"), 8)
        self.assertIn("TRIGGER:-PT15M", body)
        self.assertNotIn("zoom.us", body)
        self.assertTrue(body.startswith("BEGIN:VCALENDAR\r\n"))
        first = self.cohort.sessions.order_by("starts_at").first()
        self.assertIn(first.starts_at.astimezone(dt_timezone.utc).strftime("DTSTART:%Y%m%dT%H%M%SZ"), body)

    def test_calendar_is_members_only(self):
        self.assertEqual(self.client.get(reverse("bookings:cohort_calendar", args=[self.cohort.pk])).status_code, 404)
        Enrollment.objects.create(user=self.user, cohort=self.cohort, status=SeatBase.Status.PENDING)
        self.assertEqual(self.client.get(reverse("bookings:cohort_calendar", args=[self.cohort.pk])).status_code, 404)

    def test_workshop_calendar(self):
        workshop = make_workshop()
        url = reverse("bookings:workshop_calendar", args=[workshop.slug])
        self.assertEqual(self.client.get(url).status_code, 404)
        WorkshopBooking.objects.create(user=self.user, workshop=workshop, status=SeatBase.Status.ACTIVE)
        self.assertEqual(self.client.get(url).content.decode().count("BEGIN:VEVENT"), 1)

    def test_long_lines_are_folded(self):
        folded = _fold("DESCRIPTION:" + "é" * 80)
        for line in folded.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        self.assertEqual(folded.replace("\r\n ", ""), "DESCRIPTION:" + "é" * 80)


class WelcomeTests(TestCase):
    def setUp(self):
        self.cohort = make_cohort(capacity=12)
        self.user = make_user(first_name="Ana")
        self.client.force_login(self.user)

    def seat(self, status, checkout="cs_1", **extra):
        return Enrollment.objects.create(
            user=self.user, cohort=self.cohort, status=status, stripe_checkout_session_id=checkout,
            paid_at=timezone.now() if status == SeatBase.Status.ACTIVE else None, **extra,
        )

    @override_settings(STRIPE_SECRET_KEY="sk_test_x", SITE_URL="https://quietwork.test")
    def test_stripe_returns_to_the_welcome_page(self):
        seat = self.seat(SeatBase.Status.PENDING, checkout="")
        with mock.patch("bookings.stripe_gateway.stripe.checkout.Session.create") as create:
            stripe_gateway.create_enrollment_checkout(seat)
        self.assertEqual(
            create.call_args.kwargs["success_url"],
            "https://quietwork.test/my/welcome/?session_id={CHECKOUT_SESSION_ID}",
        )

    def test_confirmed_seat_shows_position_and_calendar(self):
        for i in range(8):
            Enrollment.objects.create(user=make_user(f"o{i}@example.com"), cohort=self.cohort,
                                      status=SeatBase.Status.ACTIVE, paid_at=timezone.now() - timedelta(hours=1))
        self.seat(SeatBase.Status.ACTIVE)
        response = self.client.get(reverse("bookings:welcome") + "?session_id=cs_1")
        self.assertContains(response, "Your seat is saved")
        self.assertContains(response, "You're 9 of 12.")
        self.assertContains(response, "Welcome to Boundaries Without Guilt")
        self.assertContains(response, reverse("bookings:cohort_calendar", args=[self.cohort.pk]))
        self.assertContains(response, "Topic 1")

    def test_pending_seat_waits_and_refreshes(self):
        self.seat(SeatBase.Status.PENDING, hold_expires_at=timezone.now() + timedelta(minutes=30))
        response = self.client.get(reverse("bookings:welcome") + "?session_id=cs_1")
        self.assertContains(response, "Confirming your payment")
        self.assertContains(response, 'http-equiv="refresh"')

    def test_page_never_activates_a_seat(self):
        seat = self.seat(SeatBase.Status.PENDING, hold_expires_at=timezone.now() + timedelta(minutes=30))
        self.client.get(reverse("bookings:welcome") + "?session_id=cs_1")
        seat.refresh_from_db()
        self.assertEqual(seat.status, SeatBase.Status.PENDING)

    def test_duplicate_payment_is_explained(self):
        self.seat(SeatBase.Status.CANCELLED)
        self.assertContains(self.client.get(reverse("bookings:welcome") + "?session_id=cs_1"), "already have this seat")

    def test_someone_elses_checkout_id_shows_nothing(self):
        Enrollment.objects.create(user=make_user("x@example.com"), cohort=self.cohort,
                                  status=SeatBase.Status.ACTIVE, stripe_checkout_session_id="cs_other")
        response = self.client.get(reverse("bookings:welcome") + "?session_id=cs_other")
        self.assertRedirects(response, reverse("bookings:my_programs"))

    def test_workshop_welcome(self):
        workshop = make_workshop()
        WorkshopBooking.objects.create(user=self.user, workshop=workshop, status=SeatBase.Status.ACTIVE,
                                       stripe_checkout_session_id="cs_w", paid_at=timezone.now())
        response = self.client.get(reverse("bookings:welcome") + "?session_id=cs_w")
        self.assertContains(response, "See you at the workshop")
        self.assertContains(response, "You're 1 of 20.")


@override_settings(DEMO_MODE=True)
class DemoWelcomePreviewTests(TestCase):
    def test_demo_member_can_preview_the_after_payment_screen(self):
        self.client.post(reverse("demo:enter"))
        response = self.client.get(reverse("bookings:welcome") + "?preview=1")
        self.assertContains(response, "Demo preview")
        self.assertContains(response, "Your seat is saved")
        self.assertNotContains(response, "demo.quietwork.invalid")
        self.assertNotContains(response, "Please")  # no error message
        # The preview is for the next open group, and its calendar downloads.
        cohort = response.context["cohort"]
        self.assertGreater(cohort.starts_at, timezone.now())
        ics = self.client.get(reverse("bookings:cohort_calendar", args=[cohort.pk]))
        self.assertEqual(ics.status_code, 200)
        self.assertNotIn("zoom.us", ics.content.decode())
        self.assertFalse(Enrollment.objects.filter(cohort=cohort).exists())  # nothing saved

    def test_preview_is_demo_only(self):
        self.client.force_login(make_user())
        self.assertRedirects(self.client.get(reverse("bookings:welcome") + "?preview=1"), reverse("bookings:my_programs"))
