from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from restaurant import services
from restaurant.models import CashPayment, Order, User
from restaurant.tests.base import RestaurantTestCase


class HTTPAccessTests(RestaurantTestCase):
    def test_anonymous_private_pages_require_signin(self):
        for name in ["orders", "worker", "billing", "settings", "users", "user_create", "checkout", "bookings"]:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("login")))

    def test_customer_and_worker_cannot_open_or_post_settings(self):
        for actor in [self.customer, self.worker]:
            self.client.force_login(actor)
            for name in ["billing", "settings", "users", "user_create", "menu_manage", "dish_create", "tables"]:
                with self.subTest(role=actor.role, page=name):
                    self.assertEqual(self.client.get(reverse(name)).status_code, 403)
                    self.assertEqual(self.client.post(reverse(name), {"role": "billing"}).status_code, 403)
            self.client.logout()

    def test_billing_cannot_use_worker_or_checkout_routes(self):
        self.client.force_login(self.billing)
        self.assertEqual(self.client.get(reverse("worker")).status_code, 403)
        self.assertEqual(self.client.get(reverse("checkout")).status_code, 403)
        self.assertEqual(self.client.post(reverse("cart_add", args=[self.dish.pk]), {"quantity": 1}).status_code, 403)
        self.assertFalse(Order.objects.exists())

    def test_order_detail_and_update_feed_only_show_authorized_orders(self):
        own = self.customer_order()
        other = self.customer_order(actor=self.other_customer)
        staff = self.staff_order()
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("order_detail", args=[own.pk])).status_code, 200)
        for order in [other, staff]:
            self.assertEqual(self.client.get(reverse("order_detail", args=[order.pk])).status_code, 404)
        response = self.client.get(reverse("order_updates"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_reassignment_revokes_old_worker_read_and_write_access(self):
        order = self.customer_order()
        services.assign_order(actor=self.billing, order_id=order.pk, worker_id=self.worker.pk)
        self.client.force_login(self.worker)
        first = self.client.get(reverse("order_updates")).json()
        self.assertEqual(first["count"], 1)
        self.assertEqual(self.client.get(reverse("order_detail", args=[order.pk])).status_code, 200)
        services.assign_order(actor=self.billing, order_id=order.pk, worker_id=self.other_worker.pk)
        self.assertEqual(self.client.get(reverse("order_detail", args=[order.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("order_status", args=[order.pk]), {"status": "accepted"}).status_code, 404)
        after = self.client.get(reverse("order_updates")).json()
        self.assertEqual(after["count"], 0)
        self.assertNotEqual(first["revision"], after["revision"])
        order.refresh_from_db()
        self.assertEqual(order.status, "placed")

    def test_billing_order_context_has_payment_and_assignment_but_no_status_controls(self):
        order = self.customer_order()
        self.client.force_login(self.billing)
        response = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["allowed_statuses"], [])
        self.assertTrue(response.context["can_assign"])
        self.assertTrue(response.context["can_collect"])
        self.assertEqual(self.client.post(reverse("order_status", args=[order.pk]), {"status": "cancelled"}).status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, "placed")

    def test_worker_cannot_post_cash_collection_or_assignment(self):
        order = self.staff_order()
        self.client.force_login(self.worker)
        self.assertEqual(self.client.post(reverse("order_collect", args=[order.pk]), {"request_id": str(uuid4())}).status_code, 403)
        self.assertEqual(self.client.post(reverse("order_assign", args=[order.pk]), {"worker_id": self.other_worker.pk}).status_code, 403)
        self.assertFalse(CashPayment.objects.exists())

    def test_cash_post_ignores_browser_amount_and_duplicate_submit(self):
        order = self.staff_order()
        self.client.force_login(self.billing)
        payload = {"request_id": str(uuid4()), "amount": "0.01", "payment_status": "unpaid", "collected_by": self.customer.pk}
        url = reverse("order_collect", args=[order.pk])
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        payment = CashPayment.objects.get(order=order)
        self.assertEqual(payment.amount, Decimal("361.00"))
        self.assertEqual(payment.collected_by_id, self.billing.pk)
        self.assertEqual(CashPayment.objects.count(), 1)

    def test_mutating_actions_require_post_and_csrf_token(self):
        order = self.customer_order()
        self.client.force_login(self.billing)
        for name in ["order_assign", "order_collect"]:
            self.assertEqual(self.client.get(reverse(name, args=[order.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.force_login(self.billing)
        response = strict_client.post(reverse("order_collect", args=[order.pk]), {"request_id": str(uuid4())})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CashPayment.objects.exists())

    def test_signup_post_cannot_create_billing_or_superuser(self):
        response = self.client.post(reverse("signup"), {
            "name": "New guest", "email": "public-signup@example.test",
            "password1": "Zebra!River!7294", "password2": "Zebra!River!7294",
            "role": "billing", "is_staff": "1", "is_superuser": "1",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="public-signup@example.test")
        self.assertEqual(user.role, "customer")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(self.client.get(reverse("settings")).status_code, 403)

    def test_initial_password_blocks_get_and_post_until_changed(self):
        employee = services.create_staff_user(actor=self.billing, name="New cashier", email="new-cashier@example.test",
                                               role="billing", initial_password="Zebra!River!7294")
        self.client.force_login(employee)
        order = self.staff_order()
        for response in [
            self.client.get(reverse("billing")),
            self.client.get(reverse("home")),
            self.client.post(reverse("order_collect", args=[order.pk]), {"request_id": str(uuid4())}),
        ]:
            self.assertRedirects(response, reverse("password_change"), fetch_redirect_response=False)
        self.assertFalse(CashPayment.objects.exists())
        response = self.client.post(reverse("password_change"), {
            "old_password": "Zebra!River!7294", "new_password1": "Cedar!Mountain!8375",
            "new_password2": "Cedar!Mountain!8375",
        })
        self.assertRedirects(response, reverse("billing"), fetch_redirect_response=False)
        employee.refresh_from_db()
        self.assertFalse(employee.must_change_password)
        self.assertEqual(self.client.get(reverse("billing")).status_code, 200)

    def test_login_ignores_external_next_redirect_and_throttles_failed_attempts(self):
        response = self.client.post(reverse("login"), {
            "username": self.customer.email, "password": "Test-only-customer-72!",
            "next": "https://outside.example.test/steal-session",
        })
        self.assertRedirects(response, reverse("menu"), fetch_redirect_response=False)
        self.client.logout()
        for _ in range(5):
            self.assertEqual(self.client.post(reverse("login"), {"username": self.customer.email, "password": "wrong"}).status_code, 400)
        blocked = self.client.post(reverse("login"), {"username": self.customer.email, "password": "Test-only-customer-72!"})
        self.assertEqual(blocked.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_own_future_booking_cancel_route_hides_other_customers_booking(self):
        booking = services.create_booking(actor=self.customer, customer_name="Asha", date_time=timezone.now()+timedelta(days=1), guests=2)
        self.client.force_login(self.other_customer)
        response = self.client.post(reverse("booking_update", args=[booking.pk]), {"status": "cancelled"})
        self.assertIn(response.status_code, [403, 404])
        booking.refresh_from_db()
        self.assertEqual(booking.status, "pending")
        self.client.force_login(self.customer)
        self.assertEqual(self.client.post(reverse("booking_update", args=[booking.pk]), {"status": "cancelled"}).status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "cancelled")


class HTTPCheckoutTests(RestaurantTestCase):
    def checkout_payload(self):
        session = self.client.session
        draft = session["checkout_draft"]
        return {"customer_name": "Asha", "order_type": "takeaway", "address": "", "notes": "",
                "request_id": draft["request_id"]}

    def test_checkout_ignores_client_price_owner_paid_and_source_fields(self):
        self.client.force_login(self.customer)
        self.client.post(reverse("cart_add", args=[self.dish.pk]), {"quantity": 2})
        self.assertEqual(self.client.get(reverse("checkout")).status_code, 200)
        payload = {**self.checkout_payload(), "total": "0.01", "expected_total": "0.01",
                   "user_id": self.billing.pk, "source": "staff", "payment_status": "paid"}
        response = self.client.post(reverse("checkout"), payload)
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.total, Decimal("361.00"))
        self.assertEqual(order.user_id, self.customer.pk)
        self.assertEqual(order.source, "online")
        self.assertEqual(order.payment_status, "unpaid")
        self.assertEqual(self.client.post(reverse("checkout"), payload).status_code, 302)
        self.assertEqual(Order.objects.count(), 1)

    def test_repeated_checkout_confirms_original_after_menu_change(self):
        self.client.force_login(self.customer)
        self.client.post(reverse("cart_add", args=[self.dish.pk]), {"quantity": 2})
        self.client.get(reverse("checkout"))
        payload = self.checkout_payload()
        first = self.client.post(reverse("checkout"), payload)
        self.dish.price = Decimal("800.00")
        self.dish.is_available = False
        self.dish.save()
        second = self.client.post(reverse("checkout"), payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(first.url, second.url)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Order.objects.get().total, Decimal("361.00"))

    def test_price_change_before_submit_requires_review_without_creating_order(self):
        self.client.force_login(self.customer)
        self.client.post(reverse("cart_add", args=[self.dish.pk]), {"quantity": 2})
        self.client.get(reverse("checkout"))
        payload = self.checkout_payload()
        self.dish.price = Decimal("800.00")
        self.dish.save()
        response = self.client.post(reverse("checkout"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertFalse(Order.objects.exists())
