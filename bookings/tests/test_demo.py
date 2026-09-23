from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from bookings.demo import SESSION_KEY, delete_stale_demo_accounts
from bookings.models import Enrollment, SeatBase, WorkshopBooking
from catalog.models import Workshop

from .factories import make_cohort, make_user, make_workshop


@override_settings(DEMO_MODE=True)
class DemoEntryTests(TestCase):
    def test_home_offers_the_demo_to_visitors(self):
        self.assertContains(self.client.get("/"), "Explore as a member")

    def test_enter_creates_a_private_demo_member_with_sample_data(self):
        response = self.client.post(reverse("demo:enter"))
        self.assertRedirects(response, reverse("bookings:my_programs"))
        user = User.objects.get(is_demo=True)
        self.assertFalse(user.has_usable_password())
        page = self.client.get(reverse("bookings:my_programs"))
        self.assertContains(page, "Welcome back, Maria.")
        self.assertContains(page, "Boundaries Without Guilt")
        self.assertContains(page, "Rewatch")  # a finished program
        self.assertContains(page, "Your live workshop")

    def test_each_visitor_gets_their_own_account(self):
        self.client.post(reverse("demo:enter"))
        self.client.post(reverse("demo:enter"))  # same visitor: reused
        self.client_class().post(reverse("demo:enter"))  # another visitor
        self.assertEqual(User.objects.filter(is_demo=True).count(), 2)

    def test_demo_members_never_take_a_real_seat(self):
        self.client.post(reverse("demo:enter"))
        workshop = Workshop.objects.get()
        self.assertTrue(WorkshopBooking.objects.filter(workshop=workshop, user__is_demo=True).exists())
        self.assertEqual(workshop.seats_left(), workshop.capacity)
        self.assertContains(self.client.get("/"), f"{workshop.capacity} of {workshop.capacity} seats left")

    def test_real_members_are_not_turned_into_demo_accounts(self):
        self.client.force_login(make_user())
        self.client.post(reverse("demo:enter"))
        self.assertFalse(User.objects.filter(is_demo=True).exists())

    def test_leaving_deletes_the_demo_account(self):
        self.client.post(reverse("demo:enter"))
        self.client.post(reverse("demo:leave"))
        self.assertFalse(User.objects.filter(is_demo=True).exists())

    def test_old_demo_accounts_are_cleaned_up(self):
        old = User.objects.create_user(email="demo-old@demo.quietwork.invalid", is_demo=True)
        User.objects.filter(pk=old.pk).update(date_joined=timezone.now() - timedelta(hours=7))
        fresh = User.objects.create_user(email="demo-new@demo.quietwork.invalid", is_demo=True)
        delete_stale_demo_accounts()
        self.assertEqual(list(User.objects.filter(is_demo=True)), [fresh])


@override_settings(DEMO_MODE=True)
class DemoMemberTests(TestCase):
    def setUp(self):
        self.cohort = make_cohort(starts_in=timedelta(days=-20))  # next session is tomorrow
        self.user = User.objects.create_user(email="demo-x@demo.quietwork.invalid", first_name="Maria", is_demo=True)
        Enrollment.objects.create(user=self.user, cohort=self.cohort, status=SeatBase.Status.ACTIVE)
        self.client.force_login(self.user)
        self.next_session = self.cohort.sessions.filter(starts_at__gt=timezone.now()).order_by("starts_at").first()

    def test_demo_cannot_start_a_payment(self):
        workshop = make_workshop()
        response = self.client.post(reverse("catalog:reserve_workshop", args=[workshop.slug]), follow=True)
        self.assertContains(response, "no payment is taken")
        self.assertFalse(WorkshopBooking.objects.exists())

    def test_time_switch_opens_the_join_button_and_explains_zoom(self):
        join = reverse("bookings:join_session", args=[self.next_session.pk])
        self.assertEqual(self.client.get(join).status_code, 302)  # not open yet

        self.client.post(reverse("demo:time"), {"open": "1", "next": "/my/"})
        self.assertTrue(self.client.session[SESSION_KEY])
        page = self.client.get(reverse("bookings:my_programs"))
        self.assertContains(page, "10")  # countdown shows minutes left
        self.assertContains(page, f'href="{join}"')
        response = self.client.get(join)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "this is where Zoom opens")
        self.assertNotContains(response, "zoom.us")

    def test_time_switch_is_only_for_demo_accounts(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.post(reverse("demo:time"), {"open": "1"}).status_code, 404)


@override_settings(DEMO_MODE=False)
class DemoOffTests(TestCase):
    def test_demo_is_hidden_and_closed(self):
        self.assertNotContains(self.client.get("/"), "Explore as a member")
        self.assertEqual(self.client.post(reverse("demo:enter")).status_code, 404)
