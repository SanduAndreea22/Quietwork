import json
from unittest import mock

import stripe
from django.test import TestCase, override_settings
from django.urls import reverse

from bookings.models import Enrollment, SeatBase, StripeEvent, WorkshopBooking
from bookings.services import reserve_cohort_seat, reserve_workshop_seat

from .factories import make_cohort, make_user, make_workshop


@override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
class WebhookTests(TestCase):
    def post(self, event, verify=True):
        body = json.dumps(event)
        with mock.patch("bookings.stripe_gateway.stripe.Webhook.construct_event") as construct:
            if not verify:
                construct.side_effect = stripe.SignatureVerificationError("bad", "sig")
            return self.client.post(
                reverse("stripe_webhook"), body, content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=x"
            )

    def event(self, event_id, type_, obj):
        return {"id": event_id, "type": type_, "data": {"object": obj}}

    def setUp(self):
        self.cohort = make_cohort()
        self.user = make_user()

    def test_rejects_bad_signature(self):
        response = self.post(self.event("evt_1", "checkout.session.completed", {}), verify=False)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(StripeEvent.objects.exists())

    def test_full_payment_activates_enrollment_once(self):
        seat, _ = reserve_cohort_seat(self.user, self.cohort.pk, "full")
        checkout = {
            "id": "cs_1", "mode": "payment", "payment_status": "paid", "amount_total": 24000,
            "customer": "cus_1", "metadata": {"kind": "enrollment", "seat_id": str(seat.pk)},
        }
        self.assertEqual(self.post(self.event("evt_1", "checkout.session.completed", checkout)).status_code, 200)
        self.assertEqual(self.post(self.event("evt_1", "checkout.session.completed", checkout)).status_code, 200)
        seat.refresh_from_db()
        self.assertEqual(seat.status, SeatBase.Status.ACTIVE)
        self.assertEqual(seat.amount_paid_cents, 24000)
        self.assertEqual(StripeEvent.objects.count(), 1)

    def test_unpaid_checkout_does_not_activate(self):
        seat, _ = reserve_cohort_seat(self.user, self.cohort.pk, "full")
        checkout = {"id": "cs_1", "mode": "payment", "payment_status": "unpaid",
                    "metadata": {"kind": "enrollment", "seat_id": str(seat.pk)}}
        self.post(self.event("evt_1", "checkout.session.completed", checkout))
        seat.refresh_from_db()
        self.assertEqual(seat.status, SeatBase.Status.PENDING)

    def test_expired_checkout_releases_the_seat(self):
        seat, _ = reserve_cohort_seat(self.user, self.cohort.pk, "full")
        self.post(self.event("evt_1", "checkout.session.expired",
                             {"id": "cs_1", "metadata": {"kind": "enrollment", "seat_id": str(seat.pk)}}))
        seat.refresh_from_db()
        self.assertEqual(seat.status, SeatBase.Status.EXPIRED)
        self.assertEqual(self.cohort.seats_left(), self.cohort.capacity)

    def test_instalments_stop_after_the_last_payment(self):
        seat, _ = reserve_cohort_seat(self.user, self.cohort.pk, "instalments")
        meta = {"kind": "enrollment", "seat_id": str(seat.pk)}
        checkout = {"id": "cs_1", "mode": "subscription", "payment_status": "paid", "subscription": "sub_1",
                    "customer": "cus_1", "metadata": meta}

        def invoice(n):
            return {"id": f"in_{n}", "amount_paid": 13000,
                    "parent": {"subscription_details": {"subscription": "sub_1", "metadata": meta}}}

        with mock.patch("bookings.stripe_gateway.stop_subscription_after_current_period") as stop:
            # Stripe does not guarantee order: the first invoice may arrive before the checkout event.
            self.post(self.event("evt_inv1", "invoice.paid", invoice(1)))
            self.post(self.event("evt_cs", "checkout.session.completed", checkout))
            stop.assert_not_called()
            self.post(self.event("evt_inv2", "invoice.paid", invoice(2)))
            stop.assert_called_once_with("sub_1")

        seat.refresh_from_db()
        self.assertEqual(seat.status, SeatBase.Status.ACTIVE)
        self.assertEqual(seat.instalments_paid, 2)
        self.assertEqual(seat.amount_paid_cents, 26000)
        self.assertEqual(seat.stripe_subscription_id, "sub_1")

    def test_failed_cancel_is_retried_by_stripe(self):
        seat, _ = reserve_cohort_seat(self.user, self.cohort.pk, "instalments")
        Enrollment.objects.filter(pk=seat.pk).update(
            status=SeatBase.Status.ACTIVE, stripe_subscription_id="sub_1", instalments_paid=1
        )
        inv = {"id": "in_2", "amount_paid": 13000, "subscription": "sub_1"}
        with mock.patch("bookings.stripe_gateway.stop_subscription_after_current_period",
                        side_effect=stripe.APIConnectionError("down")):
            with self.assertRaises(stripe.APIConnectionError):
                self.post(self.event("evt_inv2", "invoice.paid", inv))
        seat.refresh_from_db()
        self.assertEqual(seat.instalments_paid, 1)  # rolled back
        self.assertFalse(StripeEvent.objects.filter(event_id="evt_inv2").exists())

    def test_failed_instalment_is_flagged(self):
        seat, _ = reserve_cohort_seat(self.user, self.cohort.pk, "instalments")
        Enrollment.objects.filter(pk=seat.pk).update(status=SeatBase.Status.ACTIVE, stripe_subscription_id="sub_1")
        self.post(self.event("evt_f", "invoice.payment_failed", {"id": "in_x", "subscription": "sub_1"}))
        seat.refresh_from_db()
        self.assertTrue(seat.payment_problem)

    def test_second_payment_for_same_group_is_kept_for_refund(self):
        first, _ = reserve_cohort_seat(self.user, self.cohort.pk, "full")
        Enrollment.objects.filter(pk=first.pk).update(status=SeatBase.Status.ACTIVE)
        dup = Enrollment.objects.create(user=self.user, cohort=self.cohort, status=SeatBase.Status.EXPIRED)
        checkout = {"id": "cs_2", "mode": "payment", "payment_status": "paid", "amount_total": 24000,
                    "metadata": {"kind": "enrollment", "seat_id": str(dup.pk)}}
        self.assertEqual(self.post(self.event("evt_2", "checkout.session.completed", checkout)).status_code, 200)
        dup.refresh_from_db()
        self.assertEqual(dup.status, SeatBase.Status.CANCELLED)
        self.assertEqual(dup.amount_paid_cents, 24000)

    def test_workshop_payment_activates_booking(self):
        workshop = make_workshop()
        seat, _ = reserve_workshop_seat(self.user, workshop.pk)
        checkout = {"id": "cs_w", "mode": "payment", "payment_status": "paid", "amount_total": 3500,
                    "metadata": {"kind": "workshop", "seat_id": str(seat.pk)}}
        self.post(self.event("evt_w", "checkout.session.completed", checkout))
        seat.refresh_from_db()
        self.assertEqual(seat.status, WorkshopBooking.Status.ACTIVE)


@override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
class DuplicateSubscriptionTests(WebhookTests):
    def test_duplicate_instalment_subscription_is_cancelled_at_once(self):
        first, _ = reserve_cohort_seat(self.user, self.cohort.pk, "full")
        Enrollment.objects.filter(pk=first.pk).update(status=SeatBase.Status.ACTIVE)
        dup = Enrollment.objects.create(
            user=self.user, cohort=self.cohort, plan="instalments", status=SeatBase.Status.EXPIRED
        )
        meta = {"kind": "enrollment", "seat_id": str(dup.pk)}
        checkout = {"id": "cs_d", "mode": "subscription", "payment_status": "paid",
                    "subscription": "sub_dup", "metadata": meta}
        with mock.patch("bookings.stripe_gateway.cancel_subscription_now") as cancel_now:
            self.post(self.event("evt_d", "checkout.session.completed", checkout))
        cancel_now.assert_called_once_with("sub_dup")
        dup.refresh_from_db()
        self.assertEqual(dup.status, SeatBase.Status.CANCELLED)
