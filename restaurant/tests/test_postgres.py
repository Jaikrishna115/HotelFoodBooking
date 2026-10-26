"""Real lock regressions; skipped by the explicitly isolated SQLite settings."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from uuid import uuid4

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from restaurant import services
from restaurant.models import CashPayment, Category, Dish, User


@skipUnless(connection.vendor == "postgresql", "Requires the isolated PostgreSQL test database")
class PostgreSQLTransactionTests(TransactionTestCase):
    def setUp(self):
        self.customer = User.objects.create_user(email="pg-customer@example.test", password="Test-only-customer-72!")
        self.billing = User.objects.create_user(email="pg-billing@example.test", password="Test-only-billing-72!", role="billing")
        self.billing_two = User.objects.create_user(email="pg-billing-two@example.test", password="Test-only-billing-two-72!", role="billing")
        self.worker = User.objects.create_user(email="pg-worker@example.test", password="Test-only-worker-72!", role="worker")
        category = Category.objects.create(name="Mains", slug="mains")
        self.dish = Dish.objects.create(category=category, name="Bowl", price=Decimal("125.50"))
        self.order = services.create_order(
            actor=self.customer, items=[{"dish_id": self.dish.pk, "quantity": 1}],
            order_type="takeaway", request_id=uuid4(), expected_total=Decimal("125.50"),
        )

    def test_nullable_order_relations_do_not_break_postgresql_row_locks(self):
        self.assertIsNone(self.order.table_id)
        self.assertIsNone(self.order.assigned_worker_id)
        services.collect_cash(actor=self.billing, order_id=self.order.pk, request_id=uuid4())
        services.assign_order(actor=self.billing, order_id=self.order.pk, worker_id=self.worker.pk)
        services.change_order_status(actor=self.worker, order_id=self.order.pk, status="accepted")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "accepted")
        self.assertEqual(self.order.payment_status, "paid")

    def test_simultaneous_billing_requests_create_one_cash_payment(self):
        ready = Barrier(2)
        order_id = self.order.pk

        def collect(actor_id):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '5s'")
                    cursor.execute("SET statement_timeout TO '8s'")
                actor = User.objects.get(pk=actor_id)
                ready.wait(timeout=5)
                return services.collect_cash(actor=actor, order_id=order_id, request_id=uuid4()).pk
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(collect, self.billing.pk)
            second = pool.submit(collect, self.billing_two.pk)
            results = [first.result(timeout=15), second.result(timeout=15)]
        self.assertEqual(results[0], results[1])
        self.assertEqual(CashPayment.objects.filter(order_id=order_id).count(), 1)
        self.assertEqual(CashPayment.objects.get(order_id=order_id).amount, Decimal("125.50"))
