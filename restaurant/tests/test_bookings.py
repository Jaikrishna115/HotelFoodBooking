from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from restaurant import services
from restaurant.models import Booking
from restaurant.tests.base import RestaurantTestCase


class BookingTests(RestaurantTestCase):
    def booking(self, **overrides):
        values = {"actor": self.customer, "customer_name": "Asha", "guests": 2,
                  "date_time": timezone.now() + timedelta(days=1), "notes": "Window table"}
        values.update(overrides)
        return services.create_booking(**values)

    def test_valid_reservation_is_pending_and_owned_by_customer(self):
        booking = self.booking()
        self.assertEqual(booking.user_id, self.customer.pk)
        self.assertEqual(booking.status, "pending")
        self.assertEqual(booking.guests, 2)

    def test_time_and_party_size_limits_create_no_reservation(self):
        for changes in [
            {"date_time": timezone.now() - timedelta(minutes=1)},
            {"date_time": timezone.now() + timedelta(minutes=10)},
            {"date_time": timezone.now() + timedelta(days=91)},
            {"guests": 0}, {"guests": 13},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.booking(**changes)
        self.assertFalse(Booking.objects.exists())

    def test_customer_can_cancel_own_booking_but_not_confirm_or_change_another(self):
        booking = self.booking()
        with self.assertRaises(PermissionDenied):
            services.update_booking_status(actor=self.customer, booking_id=booking.pk, status="confirmed")
        with self.assertRaises(PermissionDenied):
            services.update_booking_status(actor=self.other_customer, booking_id=booking.pk, status="cancelled")
        services.update_booking_status(actor=self.customer, booking_id=booking.pk, status="cancelled")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "cancelled")

    def test_only_billing_can_approve_and_cancelled_booking_cannot_reopen(self):
        booking = self.booking()
        with self.assertRaises(PermissionDenied):
            services.update_booking_status(actor=self.worker, booking_id=booking.pk, status="confirmed")
        services.update_booking_status(actor=self.billing, booking_id=booking.pk, status="confirmed")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "confirmed")
        services.update_booking_status(actor=self.billing, booking_id=booking.pk, status="cancelled")
        with self.assertRaises(ValidationError):
            services.update_booking_status(actor=self.billing, booking_id=booking.pk, status="confirmed")
