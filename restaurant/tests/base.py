from decimal import Decimal
from uuid import uuid4

from django.test import TestCase

from restaurant.models import Category, Dish, RestaurantTable, User
from restaurant import services


class RestaurantTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user(
            email="customer@example.test", password="Test-only-customer-72!",
            first_name="Asha", role="customer",
        )
        cls.other_customer = User.objects.create_user(
            email="other@example.test", password="Test-only-other-72!", role="customer",
        )
        cls.worker = User.objects.create_user(
            email="worker@example.test", password="Test-only-worker-72!",
            first_name="Ravi", role="worker",
        )
        cls.other_worker = User.objects.create_user(
            email="other-worker@example.test", password="Test-only-worker-two-72!",
            first_name="Meera", role="worker",
        )
        cls.billing = User.objects.create_user(
            email="billing@example.test", password="Test-only-billing-72!", role="billing",
        )
        cls.category = Category.objects.create(name="Mains", slug="mains")
        cls.dish = Dish.objects.create(
            category=cls.category, name="Paneer bowl", description="Rice and paneer",
            price=Decimal("180.50"), is_available=True, is_veg=True,
        )
        cls.table = RestaurantTable.objects.create(number=3, seats=4, is_active=True)

    def customer_order(self, **overrides):
        values = {
            "actor": self.customer,
            "items": [{"dish_id": self.dish.pk, "quantity": 2}],
            "order_type": "takeaway",
            "customer_name": "Asha",
            "request_id": uuid4(),
            "expected_total": Decimal("361.00"),
        }
        values.update(overrides)
        return services.create_order(**values)

    def staff_order(self, **overrides):
        values = {
            "actor": self.worker,
            "items": [{"dish_id": self.dish.pk, "quantity": 2}],
            "order_type": "dine_in",
            "table_id": self.table.pk,
            "customer_name": "Table 3 guest",
            "request_id": uuid4(),
            "expected_total": Decimal("361.00"),
        }
        values.update(overrides)
        return services.create_order(**values)
