import threading
from datetime import timedelta

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from bookings.models import Enrollment, SeatBase
from bookings.services import BookingError, reserve_cohort_seat, reserve_workshop_seat

from .factories import make_cohort, make_user, make_workshop


class ReserveCohortSeatTests(TestCase):
    def test_holds_a_seat_until_checkout_expires(self):
        cohort = make_cohort(capacity=2)
        seat, released = reserve_cohort_seat(make_user(), cohort.pk, "full")
        self.assertEqual(seat.status, SeatBase.Status.PENDING)
        self.assertEqual(released, [])
        self.assertEqual(cohort.seats_left(), 1)

    def test_full_group_refuses_new_bookings(self):
        cohort = make_cohort(capacity=1)
        reserve_cohort_seat(make_user("a@example.com"), cohort.pk, "full")
        with self.assertRaisesMessage(BookingError, "full"):
            reserve_cohort_seat(make_user("b@example.com"), cohort.pk, "full")

    def test_expired_holds_free_the_seat(self):
        cohort = make_cohort(capacity=1)
        seat, _ = reserve_cohort_seat(make_user("a@example.com"), cohort.pk, "full")
        Enrollment.objects.filter(pk=seat.pk).update(hold_expires_at=timezone.now() - timedelta(seconds=1))
        reserve_cohort_seat(make_user("b@example.com"), cohort.pk, "full")  # does not raise

    def test_retrying_releases_the_previous_hold(self):
        cohort = make_cohort(capacity=1)
        user = make_user()
        first, _ = reserve_cohort_seat(user, cohort.pk, "full")
        first.stripe_checkout_session_id = "cs_old"
        first.save()
        second, released = reserve_cohort_seat(user, cohort.pk, "instalments")
        first.refresh_from_db()
        self.assertEqual(first.status, SeatBase.Status.EXPIRED)
        self.assertEqual(released, ["cs_old"])
        self.assertEqual(second.plan, "instalments")

    def test_member_cannot_book_the_same_group_twice(self):
        cohort = make_cohort()
        user = make_user()
        seat, _ = reserve_cohort_seat(user, cohort.pk, "full")
        Enrollment.objects.filter(pk=seat.pk).update(status=SeatBase.Status.ACTIVE)
        with self.assertRaisesMessage(BookingError, "already"):
            reserve_cohort_seat(user, cohort.pk, "full")

    def test_started_or_closed_groups_are_not_bookable(self):
        started = make_cohort(starts_in=timedelta(days=-1))
        with self.assertRaises(BookingError):
            reserve_cohort_seat(make_user(), started.pk, "full")
        closed = make_cohort(program=started.program, is_open=False)
        with self.assertRaises(BookingError):
            reserve_cohort_seat(make_user("c@example.com"), closed.pk, "full")

    def test_unknown_plan_is_rejected(self):
        with self.assertRaises(BookingError):
            reserve_cohort_seat(make_user(), make_cohort().pk, "free")


class ReserveWorkshopSeatTests(TestCase):
    def test_full_workshop_refuses_new_bookings(self):
        workshop = make_workshop(capacity=1)
        reserve_workshop_seat(make_user("a@example.com"), workshop.pk)
        with self.assertRaises(BookingError):
            reserve_workshop_seat(make_user("b@example.com"), workshop.pk)


class LastSeatRaceTests(TransactionTestCase):
    """Two buyers at the same moment: exactly one gets the last seat."""

    def test_only_one_buyer_gets_the_last_seat(self):
        cohort = make_cohort(capacity=1)
        users = [make_user(f"u{i}@example.com") for i in range(6)]
        barrier = threading.Barrier(len(users))
        results = []

        def attempt(user):
            barrier.wait()
            try:
                reserve_cohort_seat(user, cohort.pk, "full")
                results.append("ok")
            except BookingError:
                results.append("full")
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt, args=(u,)) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(Enrollment.objects.holding_seat().filter(cohort=cohort).count(), 1)
