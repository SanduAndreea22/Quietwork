from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from bookings.models import Enrollment, SeatBase, WaitlistEntry
from bookings.waitlist import notify

from .factories import make_cohort, make_program, make_user, make_workshop


class WaitlistTests(TestCase):
    def test_form_appears_only_when_the_group_is_full(self):
        cohort = make_cohort(capacity=1)
        url = reverse("catalog:program", args=[cohort.program.slug])
        self.assertNotContains(self.client.get(url), 'id="waitlist"')
        Enrollment.objects.create(user=make_user(), cohort=cohort, status=SeatBase.Status.ACTIVE)
        self.assertContains(self.client.get(url), 'id="waitlist"')
        self.assertContains(self.client.get("/"), "join the waitlist")

    def test_form_appears_when_no_group_is_open(self):
        program = make_program()
        self.assertContains(self.client.get(reverse("catalog:program", args=[program.slug])), "Hear when it opens.")

    def test_joining_twice_keeps_one_entry(self):
        program = make_program()
        url = reverse("catalog:program_waitlist", args=[program.slug])
        self.client.post(url, {"email": "Ana@Example.com"})
        response = self.client.post(url, {"email": "ana@example.com"}, follow=True)
        self.assertContains(response, "on the list")
        self.assertEqual(WaitlistEntry.objects.get().email, "ana@example.com")

    def test_bots_filling_the_hidden_field_are_ignored(self):
        program = make_program()
        self.client.post(reverse("catalog:program_waitlist", args=[program.slug]),
                         {"email": "bot@example.com", "website": "http://spam.example"})
        self.assertFalse(WaitlistEntry.objects.exists())

    def test_workshop_waitlist(self):
        workshop = make_workshop(capacity=1)
        self.client.post(reverse("catalog:workshop_waitlist", args=[workshop.slug]), {"email": "a@example.com"})
        self.assertTrue(WaitlistEntry.objects.filter(workshop=workshop).exists())

    def test_notify_emails_each_person_once_and_skips_demo(self):
        program = make_program()
        WaitlistEntry.objects.create(program=program, email="a@example.com")
        demo = User.objects.create_user(email="demo-1@demo.quietwork.invalid", is_demo=True)
        WaitlistEntry.objects.create(program=program, email=demo.email, user=demo)
        self.assertEqual(notify(WaitlistEntry.objects.all()), 1)
        self.assertEqual(mail.outbox[0].to, ["a@example.com"])
        self.assertIn(program.get_absolute_url(), mail.outbox[0].body)
        self.assertEqual(notify(WaitlistEntry.objects.all()), 0)  # already told

    def test_admin_action(self):
        program = make_program()
        WaitlistEntry.objects.create(program=program, email="a@example.com")
        admin_user = User.objects.create_superuser("admin@example.com", "x-long-password-1")
        self.client.force_login(admin_user)
        response = self.client.post(
            reverse("admin:bookings_waitlistentry_changelist"),
            {"action": "email_seat_open", "_selected_action": list(WaitlistEntry.objects.values_list("pk", flat=True))},
            follow=True,
        )
        self.assertContains(response, "1 email(s) sent")
        self.assertIsNotNone(WaitlistEntry.objects.get().notified_at)
