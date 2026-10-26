from io import StringIO
import os
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from restaurant import services
from restaurant.forms import RequiredPasswordChangeForm, SignupForm, StaffUserForm
from restaurant.models import User
from restaurant.tests.base import RestaurantTestCase


class AccountTests(RestaurantTestCase):
    def test_public_signup_cannot_claim_staff_or_superuser_access(self):
        form = SignupForm(data={
            "name": "New guest", "email": "New.Guest@example.test",
            "password1": "Zebra!River!7294", "password2": "Zebra!River!7294",
            "role": "billing", "is_staff": "true", "is_superuser": "true",
            "must_change_password": "false",
        })
        self.assertTrue(form.is_valid(), form.errors.as_json())
        user = form.save()
        self.assertEqual(user.email, "new.guest@example.test")
        self.assertEqual(user.role, "customer")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("Zebra!River!7294"))
        self.assertNotEqual(user.password, "Zebra!River!7294")

    def test_signup_rejects_case_insensitive_existing_email(self):
        form = SignupForm(data={
            "name": "Another guest", "email": self.customer.email.upper(),
            "password1": "Zebra!River!7294", "password2": "Zebra!River!7294",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_only_billing_can_create_employee_accounts(self):
        for actor in [self.customer, self.worker]:
            with self.subTest(role=actor.role), self.assertRaises(PermissionDenied):
                services.create_staff_user(actor=actor, name="New worker", email="new-worker@example.test",
                                           role="worker", initial_password="Zebra!River!7294")
        self.assertFalse(User.objects.filter(email="new-worker@example.test").exists())

    def test_new_employee_uses_hashed_password_and_must_change_it(self):
        employee = services.create_staff_user(
            actor=self.billing, name="New worker", email="NEW-WORKER@example.test",
            role="worker", initial_password="Zebra!River!7294",
        )
        self.assertEqual(employee.email, "new-worker@example.test")
        self.assertEqual(employee.created_by_id, self.billing.pk)
        self.assertTrue(employee.must_change_password)
        self.assertTrue(employee.check_password("Zebra!River!7294"))
        self.assertNotEqual(employee.password, "Zebra!River!7294")
        self.assertFalse(employee.is_staff)
        self.assertFalse(employee.is_superuser)
        with self.assertRaises(PermissionDenied):
            services.create_order(actor=employee, items=[{"dish_id": self.dish.pk, "quantity": 1}],
                                  order_type="dine_in", table_id=self.table.pk, request_id=uuid4())

    def test_employee_role_and_password_validation_reject_invalid_input(self):
        with self.assertRaises(ValidationError):
            services.create_staff_user(actor=self.billing, name="Guest", email="wrong-role@example.test",
                                       role="customer", initial_password="Zebra!River!7294")
        with self.assertRaises(ValidationError):
            services.create_staff_user(actor=self.billing, name="Worker", email="weak@example.test",
                                       role="worker", initial_password="123")
        form = StaffUserForm(data={"name": "Worker", "email": "form@example.test", "role": "worker",
                                   "initial_password": "Zebra!River!7294", "confirm_password": "Different!7294"})
        self.assertFalse(form.is_valid())
        self.assertIn("confirm_password", form.errors)

    def test_password_change_requires_old_password_and_clears_initial_flag(self):
        employee = services.create_staff_user(
            actor=self.billing, name="New worker", email="new-worker@example.test",
            role="worker", initial_password="Zebra!River!7294",
        )
        invalid = RequiredPasswordChangeForm(employee, data={
            "old_password": "incorrect", "new_password1": "Cedar!Mountain!8375",
            "new_password2": "Cedar!Mountain!8375",
        })
        self.assertFalse(invalid.is_valid())
        employee.refresh_from_db()
        self.assertTrue(employee.must_change_password)
        valid = RequiredPasswordChangeForm(employee, data={
            "old_password": "Zebra!River!7294", "new_password1": "Cedar!Mountain!8375",
            "new_password2": "Cedar!Mountain!8375",
        })
        self.assertTrue(valid.is_valid(), valid.errors.as_json())
        valid.save()
        employee.refresh_from_db()
        self.assertFalse(employee.must_change_password)
        self.assertTrue(employee.check_password("Cedar!Mountain!8375"))
        self.assertFalse(employee.check_password("Zebra!River!7294"))

    def test_billing_bootstrap_requires_password_change_and_does_not_print_secret(self):
        output = StringIO()
        with patch.dict(os.environ, {"BOOTSTRAP_BILLING_PASSWORD": "Zebra!River!7294"}):
            call_command("bootstrap_billing", email="bootstrap@example.test", name="Initial manager", noinput=True, stdout=output)
        user = User.objects.get(email="bootstrap@example.test")
        self.assertEqual(user.role, "billing")
        self.assertTrue(user.must_change_password)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password("Zebra!River!7294"))
        self.assertNotIn("Zebra!River!7294", output.getvalue())

    def test_bootstrap_never_promotes_existing_customer_or_resets_billing_password(self):
        with patch.dict(os.environ, {"BOOTSTRAP_BILLING_PASSWORD": "Zebra!River!7294"}):
            with self.assertRaises(CommandError):
                call_command("bootstrap_billing", email=self.customer.email, name="Existing guest", noinput=True, stdout=StringIO())
            call_command("bootstrap_billing", email=self.billing.email, name="Existing cashier", noinput=True, stdout=StringIO())
        self.customer.refresh_from_db()
        self.billing.refresh_from_db()
        self.assertEqual(self.customer.role, "customer")
        self.assertTrue(self.billing.check_password("Test-only-billing-72!"))
