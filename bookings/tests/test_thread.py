from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse

from bookings.models import Enrollment, Reflection, SeatBase, SessionCompletion
from bookings.thread_art import build_thread

from .factories import make_cohort, make_user


class ReflectionTests(TestCase):
    def setUp(self):
        self.cohort = make_cohort(starts_in=timedelta(days=-20))
        self.user = make_user()
        Enrollment.objects.create(user=self.user, cohort=self.cohort, status=SeatBase.Status.ACTIVE)
        self.client.force_login(self.user)
        self.session = self.cohort.sessions.order_by("starts_at").first()
        self.url = reverse("bookings:save_reflection", args=[self.session.pk])

    def test_save_edit_and_clear(self):
        self.client.post(self.url, {"text": "  First try.  "})
        self.assertEqual(Reflection.objects.get().text, "First try.")
        self.client.post(self.url, {"text": "Second try."})
        self.assertEqual(Reflection.objects.get().text, "Second try.")
        page = self.client.get(self.session.get_absolute_url())
        self.assertContains(page, "Second try.")
        self.client.post(self.url, {"text": ""})
        self.assertFalse(Reflection.objects.exists())

    def test_too_long_is_refused(self):
        self.client.post(self.url, {"text": "x" * 2001})
        self.assertFalse(Reflection.objects.exists())

    def test_reflections_are_private(self):
        Reflection.objects.create(user=self.user, session=self.session, text="Only mine.")
        other = make_user("other@example.com")
        Enrollment.objects.create(user=other, cohort=self.cohort, status=SeatBase.Status.ACTIVE)
        self.client.force_login(other)
        self.assertNotContains(self.client.get(self.session.get_absolute_url()), "Only mine.")
        self.assertNotContains(self.client.get(reverse("bookings:thread", args=[self.cohort.pk])), "Only mine.")

    def test_non_members_cannot_write(self):
        self.client.force_login(make_user("x@example.com"))
        self.assertEqual(self.client.post(self.url, {"text": "Hi"}).status_code, 404)


class ThreadTests(TestCase):
    def setUp(self):
        self.cohort = make_cohort(starts_in=timedelta(days=-70))  # finished
        self.user = make_user(first_name="Ana")
        Enrollment.objects.create(user=self.user, cohort=self.cohort, status=SeatBase.Status.ACTIVE)
        self.sessions = list(self.cohort.sessions.order_by("starts_at"))
        for s in self.sessions[:6]:
            SessionCompletion.objects.create(user=self.user, session=s)
        Reflection.objects.create(user=self.user, session=self.sessions[1], text='Small & "honest" <b>note</b>')
        self.client.force_login(self.user)

    def test_thread_page_and_download(self):
        page = self.client.get(reverse("bookings:thread", args=[self.cohort.pk]))
        self.assertContains(page, "one thread.")
        self.assertContains(page, "6 of 8")
        svg = self.client.get(reverse("bookings:thread_svg", args=[self.cohort.pk]))
        self.assertEqual(svg["Content-Type"], "image/svg+xml; charset=utf-8")
        body = svg.content.decode()
        self.assertTrue(body.startswith("<svg"))
        self.assertIn("&lt;b&gt;note&lt;/b&gt;", body)  # user text is escaped
        self.assertNotIn("<b>", body)
        self.assertEqual(body.count("<circle"), 8)

    def test_thread_is_members_only(self):
        self.client.force_login(make_user("x@example.com"))
        self.assertEqual(self.client.get(reverse("bookings:thread", args=[self.cohort.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("bookings:thread_svg", args=[self.cohort.pk])).status_code, 404)

    def test_same_data_same_drawing_different_people_different_drawings(self):
        done = {s.pk for s in self.sessions[:6]}
        a1 = build_thread(self.user, self.cohort, self.sessions, done, {})["svg"]
        a2 = build_thread(self.user, self.cohort, self.sessions, done, {})["svg"]
        b = build_thread(make_user("b@example.com"), self.cohort, self.sessions, done, {})["svg"]
        strip = lambda svg: svg.split('class="thread-all" d="')[1].split('"')[0]
        self.assertEqual(strip(a1), strip(a2))
        self.assertNotEqual(strip(a1), strip(b))

    def test_finished_program_links_to_the_thread(self):
        page = self.client.get(reverse("bookings:my_programs"))
        self.assertContains(page, "See your thread")


@override_settings(DEMO_MODE=True)
class DemoThreadTests(TestCase):
    def test_demo_member_has_a_thread_with_quotes(self):
        self.client.post(reverse("demo:enter"))
        finished = Enrollment.objects.filter(user__is_demo=True, cohort__program__slug="small-habits-real-change").get()
        page = self.client.get(reverse("bookings:thread", args=[finished.cohort_id]))
        self.assertContains(page, "7 of 8")
        self.assertContains(page, "Coffee first, then the notebook.")
