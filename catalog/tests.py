from datetime import datetime

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bookings.tests.factories import make_program, make_user
from catalog.models import Cohort


class SessionScheduleTests(TestCase):
    @override_settings(TIME_ZONE="Europe/Berlin")
    def test_weekly_sessions_keep_local_time_across_clock_change(self):
        program = make_program()
        start = timezone.make_aware(datetime(2026, 10, 14, 19, 0))  # CEST; clocks go back on 25 Oct
        Cohort.objects.create(program=program, name="October", starts_at=start)
        cohort = Cohort.objects.get()  # reloaded from the DB: starts_at is in UTC, as in the admin
        cohort.generate_sessions()
        times = {timezone.localtime(s.starts_at).strftime("%H:%M") for s in cohort.sessions.all()}
        self.assertEqual(times, {"19:00"})


class AccountTests(TestCase):
    def test_sign_in_ignores_email_case(self):
        make_user("maria@example.com")
        response = self.client.post(
            reverse("accounts:login"), {"username": "Maria@Example.COM", "password": "a-long-test-password"}
        )
        self.assertEqual(response.status_code, 302)

    def test_signup_logs_in_and_rejects_duplicate_email(self):
        data = {"first_name": "Ana", "email": "Ana@Example.com",
                "password1": "a-long-test-password", "password2": "a-long-test-password"}
        self.assertEqual(self.client.post(reverse("accounts:signup"), data).status_code, 302)
        self.client.logout()
        response = self.client.post(reverse("accounts:signup"), data)
        self.assertContains(response, "already an account")

    def test_signup_next_must_be_on_this_site(self):
        data = {"first_name": "Ana", "email": "ana@example.com", "next": "https://evil.example/",
                "password1": "a-long-test-password", "password2": "a-long-test-password"}
        response = self.client.post(reverse("accounts:signup"), data)
        self.assertEqual(response["Location"], reverse("bookings:my_programs"))


class ReserveInputTests(TestCase):
    def test_garbage_cohort_id_is_a_friendly_error_not_a_500(self):
        program = make_program()
        self.client.force_login(make_user())
        response = self.client.post(reverse("catalog:reserve_program", args=[program.slug]), {"cohort": "abc", "plan": "full"})
        self.assertEqual(response.status_code, 302)
