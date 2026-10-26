from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError

from restaurant import services
from restaurant.models import CashPayment, Order, OrderItem, User
from restaurant.tests.base import RestaurantTestCase


class OrderCreationTests(RestaurantTestCase):
    def test_server_prices_and_snapshots_survive_menu_edits(self):
        order = self.customer_order()
        self.assertEqual(order.total, Decimal("361.00"))
        self.assertEqual(order.source, "online")
        self.assertEqual(order.user_id, self.customer.pk)
        line = OrderItem.objects.get(order=order)
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.unit_price, Decimal("180.50"))
        self.dish.name = "New menu name"
        self.dish.price = Decimal("900.00")
        self.dish.save()
        order.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(order.total, Decimal("361.00"))
        self.assertEqual(line.unit_price, Decimal("180.50"))
        self.assertEqual(line.name, "Paneer bowl")

    def test_stale_total_or_unavailable_dish_creates_no_order(self):
        with self.assertRaises(ValidationError):
            self.customer_order(expected_total=Decimal("0.01"))
        self.dish.is_available = False
        self.dish.save()
        with self.assertRaises(ValidationError):
            self.customer_order()
        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())

    def test_empty_and_invalid_quantities_create_no_order(self):
        invalid_items = [[], [{"dish_id": self.dish.pk, "quantity": 0}],
                         [{"dish_id": self.dish.pk, "quantity": -1}],
                         [{"dish_id": self.dish.pk, "quantity": 100}],
                         [{"dish_id": self.dish.pk, "quantity": "1.5"}]]
        for items in invalid_items:
            with self.subTest(items=items), self.assertRaises(ValidationError):
                self.customer_order(items=items)
        self.assertFalse(Order.objects.exists())

    def test_same_request_retry_confirms_once_after_menu_price_change(self):
        request_id = uuid4()
        first = self.customer_order(request_id=request_id)
        self.dish.price = Decimal("700.00")
        self.dish.is_available = False
        self.dish.save()
        again = self.customer_order(request_id=request_id)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)
        self.assertEqual(again.total, Decimal("361.00"))

    def test_changed_contents_cannot_reuse_request_id(self):
        request_id = uuid4()
        self.customer_order(request_id=request_id)
        with self.assertRaises(ValidationError):
            self.customer_order(request_id=request_id, notes="A different order")
        self.assertEqual(Order.objects.count(), 1)

    def test_billing_cannot_create_orders_and_worker_requires_active_table(self):
        with self.assertRaises(PermissionDenied):
            self.customer_order(actor=self.billing)
        with self.assertRaises((PermissionDenied, ValidationError)):
            self.customer_order(actor=self.worker)
        self.table.is_active = False
        self.table.save()
        with self.assertRaises(ValidationError):
            self.staff_order()
        self.assertFalse(Order.objects.exists())

    def test_worker_order_has_server_derived_owner_and_source(self):
        order = self.staff_order()
        self.assertEqual(order.source, "staff")
        self.assertEqual(order.user_id, self.worker.pk)
        self.assertEqual(order.created_by_id, self.worker.pk)
        self.assertEqual(order.table_id, self.table.pk)

    def test_dish_deletion_preserves_old_order_lines(self):
        order = self.customer_order()
        self.dish.delete()
        line = OrderItem.objects.get(order=order)
        self.assertIsNone(line.dish_id)
        self.assertEqual(line.name, "Paneer bowl")
        self.assertEqual(line.unit_price, Decimal("180.50"))
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("361.00"))

    def test_stale_actor_cannot_keep_permissions_after_demotion_or_deactivation(self):
        own = self.staff_order()
        User.objects.filter(pk=self.worker.pk).update(role="customer")
        with self.assertRaises(PermissionDenied):
            services.change_order_status(actor=self.worker, order_id=own.pk, status="accepted")
        User.objects.filter(pk=self.billing.pk).update(is_active=False)
        order = self.customer_order()
        with self.assertRaises(PermissionDenied):
            services.collect_cash(actor=self.billing, order_id=order.pk, request_id=uuid4())


class AssignmentAndStatusTests(RestaurantTestCase):
    def test_unassigned_online_order_cannot_be_updated_by_any_worker(self):
        order = self.customer_order()
        for actor in [self.customer, self.worker, self.other_worker, self.billing]:
            with self.subTest(role=actor.role), self.assertRaises(PermissionDenied):
                services.change_order_status(actor=actor, order_id=order.pk, status="accepted")
        order.refresh_from_db()
        self.assertEqual(order.status, "placed")

    def test_only_billing_assigns_and_only_to_workers(self):
        order = self.customer_order()
        for actor in [self.customer, self.worker]:
            with self.subTest(role=actor.role), self.assertRaises(PermissionDenied):
                services.assign_order(actor=actor, order_id=order.pk, worker_id=self.worker.pk)
        for target in [self.customer, self.billing]:
            with self.subTest(target=target.role), self.assertRaises(ValidationError):
                services.assign_order(actor=self.billing, order_id=order.pk, worker_id=target.pk)
        services.assign_order(actor=self.billing, order_id=order.pk, worker_id=self.worker.pk)
        order.refresh_from_db()
        self.assertEqual(order.assigned_worker_id, self.worker.pk)

    def test_reassignment_revokes_previous_worker_immediately(self):
        order = self.customer_order()
        services.assign_order(actor=self.billing, order_id=order.pk, worker_id=self.worker.pk)
        services.change_order_status(actor=self.worker, order_id=order.pk, status="accepted")
        services.assign_order(actor=self.billing, order_id=order.pk, worker_id=self.other_worker.pk)
        with self.assertRaises(PermissionDenied):
            services.change_order_status(actor=self.worker, order_id=order.pk, status="preparing")
        services.change_order_status(actor=self.other_worker, order_id=order.pk, status="preparing")
        order.refresh_from_db()
        self.assertEqual(order.status, "preparing")

    def test_staff_order_stays_with_creator_and_cannot_be_assigned(self):
        order = self.staff_order()
        with self.assertRaises(ValidationError):
            services.assign_order(actor=self.billing, order_id=order.pk, worker_id=self.other_worker.pk)
        with self.assertRaises(PermissionDenied):
            services.change_order_status(actor=self.other_worker, order_id=order.pk, status="accepted")
        services.change_order_status(actor=self.worker, order_id=order.pk, status="accepted")
        order.refresh_from_db()
        self.assertEqual(order.status, "accepted")

    def test_lifecycle_cannot_skip_steps_or_complete_before_payment(self):
        order = self.staff_order()
        with self.assertRaises(ValidationError):
            services.change_order_status(actor=self.worker, order_id=order.pk, status="ready")
        for status in ["accepted", "preparing", "ready"]:
            services.change_order_status(actor=self.worker, order_id=order.pk, status=status)
        with self.assertRaises(ValidationError):
            services.change_order_status(actor=self.worker, order_id=order.pk, status="completed")
        services.collect_cash(actor=self.billing, order_id=order.pk, request_id=uuid4())
        services.change_order_status(actor=self.worker, order_id=order.pk, status="completed")
        order.refresh_from_db()
        self.assertEqual(order.status, "completed")
        with self.assertRaises(ValidationError):
            services.change_order_status(actor=self.worker, order_id=order.pk, status="cancelled")

    def test_completed_or_cancelled_online_orders_cannot_be_reassigned(self):
        for status in ["completed", "cancelled"]:
            order = self.customer_order()
            Order.objects.filter(pk=order.pk).update(status=status)
            with self.subTest(status=status), self.assertRaises(ValidationError):
                services.assign_order(actor=self.billing, order_id=order.pk, worker_id=self.worker.pk)


class CashCollectionTests(RestaurantTestCase):
    def test_only_billing_collects_cash_and_amount_is_the_saved_total(self):
        order = self.staff_order()
        for actor in [self.customer, self.worker]:
            with self.subTest(role=actor.role), self.assertRaises(PermissionDenied):
                services.collect_cash(actor=actor, order_id=order.pk, request_id=uuid4())
        self.assertFalse(CashPayment.objects.exists())
        self.dish.price = Decimal("999.00")
        self.dish.save()
        services.collect_cash(actor=self.billing, order_id=order.pk, request_id=uuid4())
        payment = CashPayment.objects.get(order=order)
        order.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("361.00"))
        self.assertEqual(payment.collected_by_id, self.billing.pk)
        self.assertEqual(order.payment_status, "paid")

    def test_repeated_cash_collection_does_not_double_book_payment(self):
        order = self.staff_order()
        request_id = uuid4()
        services.collect_cash(actor=self.billing, order_id=order.pk, request_id=request_id)
        original = CashPayment.objects.get(order=order)
        services.collect_cash(actor=self.billing, order_id=order.pk, request_id=request_id)
        services.collect_cash(actor=self.billing, order_id=order.pk, request_id=uuid4())
        self.assertEqual(CashPayment.objects.count(), 1)
        payment = CashPayment.objects.get(order=order)
        self.assertEqual(payment.pk, original.pk)
        self.assertEqual(payment.amount, original.amount)

    def test_cancelled_order_cannot_collect_cash(self):
        order = self.staff_order()
        services.change_order_status(actor=self.worker, order_id=order.pk, status="cancelled")
        with self.assertRaises(ValidationError):
            services.collect_cash(actor=self.billing, order_id=order.pk, request_id=uuid4())
        self.assertFalse(CashPayment.objects.exists())

    def test_one_cash_request_cannot_pay_two_orders(self):
        first, second = self.staff_order(), self.staff_order()
        request_id = uuid4()
        services.collect_cash(actor=self.billing, order_id=first.pk, request_id=request_id)
        with self.assertRaises(ValidationError):
            services.collect_cash(actor=self.billing, order_id=second.pk, request_id=request_id)
        second.refresh_from_db()
        self.assertEqual(second.payment_status, "unpaid")
        self.assertEqual(CashPayment.objects.count(), 1)

    def test_paid_cancellation_flags_refund_without_deleting_payment(self):
        order = self.staff_order()
        services.collect_cash(actor=self.billing, order_id=order.pk, request_id=uuid4())
        services.change_order_status(actor=self.worker, order_id=order.pk, status="cancelled")
        order.refresh_from_db()
        self.assertTrue(order.needs_refund)
        self.assertEqual(order.payment_status, "paid")
        self.assertEqual(CashPayment.objects.get(order=order).amount, Decimal("361.00"))
