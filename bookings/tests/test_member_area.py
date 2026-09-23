from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Enrollment, SeatBase, SessionCompletion, WorkshopBooking

from .factories import make_cohort, make_user, make_workshop


class MemberAreaTests(TestCase):
    def setUp(self):
        self.cohort = make_cohort(starts_in=timedelta(days=-21))  # sessions 1-3 are in the past
        self.user = make_user()
        self.client.force_login(self.user)
        self.sessions = list(self.cohort.sessions.order_by("starts_at"))

    def enrol(self, status=SeatBase.Status.ACTIVE):
        return Enrollment.objects.create(user=self.user, cohort=self.cohort, status=status)

    def test_session_page_is_members_only(self):
        url = reverse("bookings:session", args=[self.sessions[0].pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.enrol(status=SeatBase.Status.PENDING)
        self.assertEqual(self.client.get(url).status_code, 404)
        Enrollment.objects.update(status=SeatBase.Status.ACTIVE)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_zoom_link_never_appears_in_the_page(self):
        self.enrol()
        response = self.client.get(reverse("bookings:session", args=[self.sessions[3].pk]))
        self.assertNotContains(response, "zoom.us")
        self.assertNotContains(self.client.get(reverse("bookings:my_programs")), "zoom.us")

    def test_join_redirects_to_zoom_only_in_the_window(self):
        self.enrol()
        upcoming = self.sessions[4]
        url = reverse("bookings:join_session", args=[upcoming.pk])
        response = self.client.get(url)
        self.assertNotEqual(response["Location"], "https://zoom.us/j/123")

        with mock.patch("django.utils.timezone.now", return_value=upcoming.starts_at - timedelta(minutes=10)):
            response = self.client.get(url)
        self.assertEqual(response["Location"], "https://zoom.us/j/123")

        with mock.patch("django.utils.timezone.now", return_value=upcoming.starts_at - timedelta(minutes=16)):
            response = self.client.get(url)
        self.assertNotEqual(response["Location"], "https://zoom.us/j/123")

    def test_join_is_refused_to_non_members(self):
        upcoming = self.sessions[4]
        with mock.patch("django.utils.timezone.now", return_value=upcoming.starts_at):
            response = self.client.get(reverse("bookings:join_session", args=[upcoming.pk]))
        self.assertEqual(response.status_code, 404)

    def test_workshop_join_requires_a_paid_booking(self):
        workshop = make_workshop()
        url = reverse("bookings:join_workshop", args=[workshop.slug])
        with mock.patch("django.utils.timezone.now", return_value=workshop.starts_at):
            self.assertEqual(self.client.get(url).status_code, 404)
            WorkshopBooking.objects.create(user=self.user, workshop=workshop, status=SeatBase.Status.ACTIVE)
            self.assertEqual(self.client.get(url)["Location"], "https://zoom.us/j/456")

    def test_marking_done_only_after_the_session_started(self):
        self.enrol()
        past, future = self.sessions[0], self.sessions[5]
        self.client.post(reverse("bookings:toggle_done", args=[future.pk]), {"done": "1"})
        self.assertFalse(SessionCompletion.objects.filter(session=future).exists())
        self.client.post(reverse("bookings:toggle_done", args=[past.pk]), {"done": "1"})
        self.assertTrue(SessionCompletion.objects.filter(session=past).exists())
        self.client.post(reverse("bookings:toggle_done", args=[past.pk]), {"done": "0"})
        self.assertFalse(SessionCompletion.objects.filter(session=past).exists())

    def test_done_redirect_ignores_external_urls(self):
        self.enrol()
        response = self.client.post(
            reverse("bookings:toggle_done", args=[self.sessions[0].pk]), {"done": "1", "back": "https://evil.example/"}
        )
        self.assertEqual(response["Location"], self.sessions[0].get_absolute_url())

    def test_dashboard_shows_progress_and_next_session(self):
        self.enrol()
        SessionCompletion.objects.create(user=self.user, session=self.sessions[0])
        response = self.client.get(reverse("bookings:my_programs"))
        self.assertContains(response, "1 of 8 sessions done")
        self.assertContains(response, f"Session 4: {self.sessions[3].title}")

    def test_api_completion_and_next_up(self):
        self.enrol()
        url = reverse("api_session_completion", args=[self.sessions[0].pk])
        self.assertEqual(self.client.put(url).json(), {"done": True})
        self.assertEqual(self.client.put(reverse("api_session_completion", args=[self.sessions[6].pk])).status_code, 400)
        data = self.client.get(reverse("api_next_up")).json()["next_up"]
        self.assertEqual(data["kind"], "session")
        self.assertNotIn("zoom.us", str(data))


class PublicPagesTests(TestCase):
    def test_home_and_program_pages_render(self):
        cohort = make_cohort(capacity=3)
        make_workshop()
        response = self.client.get(reverse("catalog:home"))
        self.assertContains(response, "Boundaries Without Guilt")
        self.assertContains(response, "3 of 3 seats left")
        response = self.client.get(reverse("catalog:program", args=[cohort.program.slug]))
        self.assertContains(response, "Topic 8")
        self.assertContains(response, "Create an account to book")

    def test_sold_out_group(self):
        cohort = make_cohort(capacity=1)
        Enrollment.objects.create(user=make_user(), cohort=cohort, status=SeatBase.Status.ACTIVE)
        self.assertContains(self.client.get(reverse("catalog:home")), "Sold out")

    def test_reserve_requires_login_and_post(self):
        cohort = make_cohort()
        url = reverse("catalog:reserve_program", args=[cohort.program.slug])
        self.assertEqual(self.client.post(url, {"cohort": cohort.pk, "plan": "full"}).status_code, 302)
        self.assertFalse(Enrollment.objects.exists())
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_reserve_starts_stripe_checkout(self):
        cohort = make_cohort()
        self.client.force_login(make_user())
        fake = mock.Mock(id="cs_new", url="https://checkout.stripe.com/c/pay/cs_new")
        with mock.patch("bookings.stripe_gateway.create_enrollment_checkout", return_value=fake):
            response = self.client.post(
                reverse("catalog:reserve_program", args=[cohort.program.slug]), {"cohort": cohort.pk, "plan": "full"}
            )
        self.assertEqual(response["Location"], fake.url)
        self.assertEqual(Enrollment.objects.get().stripe_checkout_session_id, "cs_new")

    def test_checkout_failure_releases_the_seat(self):
        cohort = make_cohort()
        self.client.force_login(make_user())
        response = self.client.post(
            reverse("catalog:reserve_program", args=[cohort.program.slug]), {"cohort": cohort.pk, "plan": "full"}
        )  # STRIPE_SECRET_KEY is empty in tests
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Enrollment.objects.get().status, SeatBase.Status.EXPIRED)
        self.assertEqual(cohort.seats_left(), cohort.capacity)
