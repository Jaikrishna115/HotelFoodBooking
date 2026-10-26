"""HTTP/template contracts, using real forms and database writes rather than mocks."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from restaurant.models import Booking, Category, Dish, Order, RestaurantSettings, RestaurantTable, User
from restaurant.tests.base import RestaurantTestCase


class PageIntegrationTests(RestaurantTestCase):
    def page(self, name, template=None, *, kwargs=None, query=None):
        response = self.client.get(reverse(name, kwargs=kwargs), query or {})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, f"restaurant/{template or name}.html")
        self.assertContains(response, 'id="main-content"')
        self.assertIn("no-store", response.headers["Cache-Control"])
        return response

    def assert_fields(self, response, *names):
        for name in names:
            self.assertContains(response, f'name="{name}"')

    def add_dish(self, quantity=2):
        response = self.client.post(reverse("cart_add", args=[self.dish.pk]), {"quantity": quantity})
        self.assertRedirects(response, reverse("menu"), fetch_redirect_response=False)

    def dish_data(self, **overrides):
        data = {
            "name": "Lemon rice", "description": "Freshly cooked rice",
            "category": self.category.pk, "price": "125.25", "image_url": "",
            "is_veg": "on", "is_available": "on", "is_featured": "on", "prep_minutes": 15,
        }
        data.update(overrides)
        return data

    def test_public_pages_and_menu_filters_render_available_dishes(self):
        self.dish.is_featured = True
        self.dish.save(update_fields=["is_featured"])
        Dish.objects.create(category=self.category, name="Unavailable soup", price="70.00", is_available=False)
        other_category = Category.objects.create(name="Desserts", slug="desserts")
        Dish.objects.create(category=other_category, name="Egg pudding", price="90.00", is_veg=False)
        home = self.page("home")
        self.assertContains(home, self.dish.name)
        self.assertNotContains(home, "Unavailable soup")
        menu = self.page("menu", query={"q": "paneer", "category": "mains", "veg": "1"})
        self.assertContains(menu, "180.50")
        self.assertContains(menu, reverse("cart_add", args=[self.dish.pk]))
        self.assertNotContains(menu, "Egg pudding")
        self.assertNotContains(menu, "Unavailable soup")
        self.assertEqual(list(menu.context["dishes"]), [self.dish])
        self.page("cart")
        self.assert_fields(self.page("login"), "username", "password")
        self.assert_fields(self.page("signup"), "name", "email", "password1", "password2")

    def test_customer_cart_checkout_and_saved_order_render_exact_totals(self):
        self.client.force_login(self.customer)
        self.add_dish()
        menu = self.page("menu")
        self.assertContains(menu, "361.00")
        self.assertContains(menu, reverse("cart_update", args=[self.dish.pk]))
        cart = self.page("cart")
        self.assertContains(cart, self.dish.name)
        self.assertContains(cart, "361.00")
        self.assertContains(cart, reverse("checkout"))
        self.assertEqual(cart.context["total"], Decimal("361.00"))
        checkout = self.page("checkout")
        self.assert_fields(checkout, "customer_name", "order_type", "table", "address", "notes", "request_id")
        self.assertContains(checkout, "361.00")
        draft = self.client.session["checkout_draft"]
        self.assertContains(checkout, draft["request_id"])
        response = self.client.post(reverse("checkout"), {
            "customer_name": "Asha", "order_type": "takeaway", "request_id": draft["request_id"],
            "notes": "Less chilli, please", "address": "",
        })
        order = Order.objects.get(created_by=self.customer)
        self.assertRedirects(response, reverse("order_detail", args=[order.pk]))
        detail = self.page("order_detail", kwargs={"pk": order.pk})
        self.assertContains(detail, self.dish.name)
        self.assertContains(detail, "361.00")
        self.assertContains(detail, "Less chilli, please")
        self.assertNotContains(detail, reverse("order_collect", args=[order.pk]))
        self.assertNotContains(detail, reverse("order_status", args=[order.pk]))
        listing = self.page("orders")
        self.assertContains(listing, order.reference)
        self.assertContains(listing, reverse("order_detail", args=[order.pk]))
        self.assertEqual(self.client.session["cart"], {})

    def test_cart_quantity_edits_and_invalid_checkout_errors_render(self):
        self.client.force_login(self.customer)
        self.add_dish()
        response = self.client.post(reverse("cart_update", args=[self.dish.pk]), {"quantity": 3}, follow=True)
        self.assertContains(response, "541.50")
        checkout = self.page("checkout")
        response = self.client.post(reverse("checkout"), {
            "customer_name": "Asha", "order_type": "delivery", "address": "",
            "request_id": checkout.context["request_id"],
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter the delivery address.")
        self.assertFalse(Order.objects.exists())
        removed = self.client.post(reverse("cart_update", args=[self.dish.pk]), {"quantity": 0}, follow=True)
        self.assertContains(removed, "Your next favourite is waiting.")
        self.assertEqual(self.client.session["cart"], {})

    def test_worker_table_selection_checkout_and_own_work_pages(self):
        self.client.force_login(self.worker)
        worker = self.page("worker")
        self.assertContains(worker, f'{reverse("menu")}?table={self.table.pk}')
        self.page("menu", query={"table": self.table.pk})
        self.add_dish(1)
        checkout = self.page("checkout")
        self.assertEqual(checkout.context["form"].initial["table"], self.table.pk)
        self.assertContains(checkout, 'value="dine_in"')
        self.assertNotContains(checkout, 'value="delivery"')
        response = self.client.post(reverse("checkout"), {
            "customer_name": "Window table guest", "order_type": "dine_in", "table": self.table.pk,
            "request_id": checkout.context["request_id"], "notes": "Serve together",
        })
        order = Order.objects.get(created_by=self.worker)
        self.assertRedirects(response, reverse("order_detail", args=[order.pk]))
        self.assertEqual(order.source, Order.Source.STAFF)
        self.assertEqual(order.table_id, self.table.pk)
        for name in ["worker", "orders"]:
            listing = self.page(name)
            self.assertContains(listing, "Table 3")
            self.assertContains(listing, order.reference)
        detail = self.page("order_detail", kwargs={"pk": order.pk})
        self.assertContains(detail, reverse("order_status", args=[order.pk]))
        self.assertNotContains(detail, reverse("order_assign", args=[order.pk]))
        self.assertNotContains(detail, reverse("order_collect", args=[order.pk]))

    def test_billing_counter_assignment_collection_and_receipt_render(self):
        online = self.customer_order()
        staff = self.staff_order()
        self.client.force_login(self.billing)
        counter = self.page("billing")
        self.assertEqual(counter.context["summary"], {
            "active_count": 2, "unassigned_count": 1,
            "unpaid_total": Decimal("722.00"), "today_paid_total": Decimal("0.00"),
        })
        self.assertContains(counter, '<div class="stat-value">2</div>', html=True)
        self.assertContains(counter, '<div class="stat-value">₹722</div>', html=True)
        self.assertContains(counter, online.reference)
        self.assertContains(counter, staff.reference)
        detail = self.page("order_detail", kwargs={"pk": online.pk})
        self.assertContains(detail, reverse("order_assign", args=[online.pk]))
        self.assertContains(detail, self.worker.display_name)
        self.assertContains(detail, reverse("order_collect", args=[online.pk]))
        self.assertNotContains(detail, reverse("order_status", args=[online.pk]))
        response = self.client.post(reverse("order_assign", args=[online.pk]), {"worker_id": self.worker.pk}, follow=True)
        self.assertContains(response, "Reassign worker")
        self.assertEqual(response.context["order"].assigned_worker_id, self.worker.pk)
        response = self.client.post(reverse("order_collect", args=[online.pk]), {"request_id": detail.context["payment_request_id"]}, follow=True)
        self.assertContains(response, "Payment receipt")
        self.assertContains(response, "Total paid ₹361.00")
        self.assertContains(response, self.billing.display_name)
        self.assertNotContains(response, "Mark cash collected")
        self.assertNotContains(response, reverse("order_status", args=[online.pk]))
        counter = self.page("billing")
        self.assertEqual(counter.context["summary"]["today_paid_total"], Decimal("361.00"))
        self.assertEqual(counter.context["summary"]["unpaid_total"], Decimal("361.00"))
        self.assertEqual(counter.context["summary"]["unassigned_count"], 0)

    def test_every_billing_settings_page_and_form_has_its_contract(self):
        self.client.force_login(self.billing)
        pages = [
            ("settings", "settings", ("name", "tagline", "accepting_orders")),
            ("users", "users", ("user_id", "role", "is_active")),
            ("user_create", "user_create", ("name", "email", "role", "initial_password", "confirm_password")),
            ("menu_manage", "menu_manage", ("name", "slug", "sort_order")),
            ("dish_create", "dish_form", ("name", "category", "price", "is_available", "prep_minutes")),
            ("tables", "tables", ("number", "seats", "is_active")),
        ]
        for name, template, fields in pages:
            with self.subTest(page=name):
                page = self.page(name, template)
                self.assert_fields(page, *fields)
                for route in ["settings", "users", "menu_manage", "tables"]:
                    self.assertContains(page, f'href="{reverse(route)}"')
        self.assertContains(self.page("users"), self.worker.email)
        self.assertNotContains(self.page("users"), self.customer.email)
        edit = self.page("dish_edit", "dish_form", kwargs={"pk": self.dish.pk})
        self.assertContains(edit, 'value="Paneer bowl"')
        self.assert_fields(edit, "action")
        table = self.page("tables", query={"edit": self.table.pk})
        self.assertContains(table, "Edit table 3")
        self.assertContains(table, f'name="table_id" value="{self.table.pk}"')

    def test_customer_and_worker_navigation_hide_billing_and_direct_routes_forbidden(self):
        protected = ["settings", "users", "user_create", "menu_manage", "dish_create", "tables", "billing"]
        for actor in [self.customer, self.worker]:
            self.client.force_login(actor)
            with self.subTest(role=actor.role):
                menu = self.page("menu")
                for route in protected:
                    self.assertNotContains(menu, f'href="{reverse(route)}"')
                    denied = self.client.get(reverse(route))
                    self.assertEqual(denied.status_code, 403, route)
                    self.assertTemplateUsed(denied, "403.html")
                    self.assertNotContains(denied, 'name="initial_password"', status_code=403)
                self.assertEqual(self.client.get(reverse("dish_edit", args=[self.dish.pk])).status_code, 403)

    def test_settings_form_validates_saves_and_updates_public_brand(self):
        self.client.force_login(self.billing)
        invalid = self.client.post(reverse("settings"), {"name": "", "email": "invalid"})
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "This field is required.")
        self.assertContains(invalid, "Enter a valid email address.")
        data = {
            "name": "Garden Table", "tagline": "Meals made together", "phone": "0123456789",
            "email": "hello@example.test", "address": "12 Garden Lane", "opening_hours": "Daily 12 to 9",
            "accepting_orders": "on",
        }
        response = self.client.post(reverse("settings"), data, follow=True)
        self.assertRedirects(response, reverse("settings"))
        self.assertContains(response, 'value="Garden Table"')
        self.assertEqual(RestaurantSettings.current().email, "hello@example.test")
        self.client.logout()
        home = self.page("home")
        self.assertContains(home, "Garden Table")
        self.assertContains(home, "Meals made together")
        self.assertContains(home, "12 Garden Lane")

    def test_menu_category_and_dish_crud_preserve_existing_order_snapshots(self):
        order = self.customer_order()
        self.client.force_login(self.billing)
        response = self.client.post(reverse("menu_manage"), {"name": "Small plates", "slug": "", "sort_order": ""}, follow=True)
        self.assertContains(response, "Small plates")
        category = Category.objects.get(name="Small plates")
        self.assertEqual(category.slug, "small-plates")
        duplicate = self.client.post(reverse("menu_manage"), {"name": "Different name", "slug": category.slug})
        self.assertEqual(duplicate.status_code, 200)
        self.assertContains(duplicate, "This category URL name is already in use.")
        invalid = self.client.post(reverse("dish_create"), self.dish_data(price="-1"))
        self.assertEqual(invalid.status_code, 200)
        self.assertTrue(invalid.context["form"].errors["price"])
        response = self.client.post(reverse("dish_create"), self.dish_data(category=category.pk), follow=True)
        self.assertRedirects(response, reverse("menu_manage"))
        created = Dish.objects.get(name="Lemon rice")
        self.assertContains(response, "125.25")
        self.assertContains(response, reverse("dish_edit", args=[created.pk]))
        data = self.dish_data(name="Updated paneer", price="200.00")
        data.pop("is_available")
        response = self.client.post(reverse("dish_edit", args=[self.dish.pk]), data, follow=True)
        self.assertContains(response, "Updated paneer")
        self.dish.refresh_from_db()
        self.assertFalse(self.dish.is_available)
        self.assertEqual(self.dish.price, Decimal("200.00"))
        self.assertNotContains(self.page("menu"), "Updated paneer")
        response = self.client.post(reverse("dish_edit", args=[self.dish.pk]), {"action": "delete"}, follow=True)
        self.assertRedirects(response, reverse("menu_manage"))
        self.assertFalse(Dish.objects.filter(pk=self.dish.pk).exists())
        line = order.items.get()
        self.assertIsNone(line.dish_id)
        self.assertEqual((line.name, line.unit_price), ("Paneer bowl", Decimal("180.50")))
        detail = self.page("order_detail", kwargs={"pk": order.pk})
        self.assertContains(detail, "Paneer bowl")
        self.assertContains(detail, "361.00")

    def test_table_create_edit_validation_and_worker_selection(self):
        self.client.force_login(self.billing)
        response = self.client.post(reverse("tables"), {"number": 7, "seats": 6, "is_active": "on"}, follow=True)
        self.assertContains(response, "Table 7")
        table = RestaurantTable.objects.get(number=7)
        self.assertContains(response, f'{reverse("tables")}?edit={table.pk}')
        invalid = self.client.post(reverse("tables"), {"number": 7, "seats": 0, "is_active": "on"})
        self.assertEqual(invalid.status_code, 200)
        self.assertTrue(invalid.context["form"].errors["number"])
        self.assertTrue(invalid.context["form"].errors["seats"])
        response = self.client.post(reverse("tables"), {"table_id": table.pk, "number": 8, "seats": 2}, follow=True)
        self.assertContains(response, "Table 8")
        table.refresh_from_db()
        self.assertEqual(table.number, 8)
        self.assertFalse(table.is_active)
        self.client.force_login(self.worker)
        page = self.page("worker")
        self.assertContains(page, f'{reverse("menu")}?table={self.table.pk}')
        self.assertNotContains(page, f'{reverse("menu")}?table={table.pk}')
        self.add_dish()
        checkout = self.page("checkout")
        self.assertNotIn(table, checkout.context["form"].fields["table"].queryset)

    def test_invalid_table_edit_identifiers_return_client_errors(self):
        self.client.force_login(self.billing)
        for identifier in ["not-a-number", "-1", "99999999", "²"]:
            with self.subTest(identifier=identifier, method="GET"):
                response = self.client.get(reverse("tables"), {"edit": identifier})
                self.assertIn(response.status_code, [400, 404])
            with self.subTest(identifier=identifier, method="POST"):
                response = self.client.post(reverse("tables"), {"table_id": identifier, "number": 9, "seats": 4})
                self.assertIn(response.status_code, [400, 404])
        self.assertEqual(RestaurantTable.objects.count(), 1)

    def test_employee_create_update_and_initial_password_workflow(self):
        self.client.force_login(self.billing)
        data = {
            "name": "New teammate", "email": "new-worker@example.test", "role": "worker",
            "initial_password": "New-temporary-worker-923!", "confirm_password": "wrong",
        }
        invalid = self.client.post(reverse("user_create"), data)
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "The passwords do not match.")
        self.assertFalse(User.objects.filter(email=data["email"]).exists())
        data["confirm_password"] = data["initial_password"]
        created = self.client.post(reverse("user_create"), data, follow=True)
        self.assertRedirects(created, reverse("users"))
        self.assertContains(created, data["email"])
        employee = User.objects.get(email=data["email"])
        self.assertTrue(employee.must_change_password)
        self.assertEqual(employee.created_by_id, self.billing.pk)
        self.assertFalse(employee.is_staff)
        self.client.logout()
        signed_in = self.client.post(reverse("login"), {"username": employee.email, "password": data["initial_password"]}, follow=True)
        self.assertRedirects(signed_in, reverse("password_change"))
        self.assertContains(signed_in, "Make it your password")
        self.assert_fields(signed_in, "old_password", "new_password1", "new_password2")
        self.assertRedirects(self.client.get(reverse("worker")), reverse("password_change"), fetch_redirect_response=False)
        changed = self.client.post(reverse("password_change"), {
            "old_password": data["initial_password"], "new_password1": "Personal-new-secret-672!",
            "new_password2": "Personal-new-secret-672!",
        }, follow=True)
        self.assertRedirects(changed, reverse("worker"))
        employee.refresh_from_db()
        self.assertFalse(employee.must_change_password)
        self.assertTrue(employee.check_password("Personal-new-secret-672!"))
        self.client.force_login(self.billing)
        updated = self.client.post(reverse("users"), {"user_id": employee.pk, "role": "billing", "is_active": "on"}, follow=True)
        self.assertContains(updated, employee.email)
        employee.refresh_from_db()
        self.assertEqual(employee.role, "billing")
        self.client.post(reverse("users"), {"user_id": employee.pk, "role": "billing"})
        employee.refresh_from_db()
        self.assertFalse(employee.is_active)

    def test_customer_and_worker_booking_forms_and_billing_confirmation(self):
        for actor in [self.customer, self.worker]:
            with self.subTest(role=actor.role):
                self.client.force_login(actor)
                self.page("bookings")
                form = self.page("book_table")
                self.assert_fields(form, "customer_name", "date_time", "guests", "notes")
                data = {
                    "customer_name": actor.display_name,
                    "date_time": timezone.localtime(timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
                    "guests": 13, "notes": f"Reservation by {actor.role}",
                }
                invalid = self.client.post(reverse("book_table"), data)
                self.assertEqual(invalid.status_code, 200)
                self.assertTrue(invalid.context["form"].errors["guests"])
                data["guests"] = 3
                created = self.client.post(reverse("book_table"), data, follow=True)
                self.assertRedirects(created, reverse("bookings"))
                self.assertContains(created, data["notes"])
                self.assertContains(created, "Cancel request")
                booking = Booking.objects.get(user=actor)
                self.assertContains(created, reverse("booking_update", args=[booking.pk]))
                self.assertNotContains(created, '<select name="status"')
        customer_booking = Booking.objects.get(user=self.customer)
        self.client.force_login(self.billing)
        management = self.page("bookings")
        self.assertContains(management, "Reservation by customer")
        self.assertContains(management, "Reservation by worker")
        self.assertContains(management, 'value="confirmed"')
        self.assertNotContains(management, f'href="{reverse("book_table")}"')
        approved = self.client.post(reverse("booking_update", args=[customer_booking.pk]), {"status": "confirmed"}, follow=True)
        self.assertContains(approved, "Confirmed")
        self.client.force_login(self.customer)
        listing = self.page("bookings")
        self.assertContains(listing, "Confirmed")
        self.assertNotContains(listing, "Reservation by worker")
        cancelled = self.client.post(reverse("booking_update", args=[customer_booking.pk]), {"status": "cancelled"}, follow=True)
        self.assertContains(cancelled, "Cancelled")
        self.assertNotContains(cancelled, "Cancel request")

    def test_account_page_and_password_validation_for_all_roles(self):
        for actor in [self.customer, self.worker, self.billing]:
            self.client.force_login(actor)
            with self.subTest(role=actor.role):
                account = self.page("password_change")
                self.assertContains(account, actor.email)
                self.assertContains(account, actor.get_role_display())
                self.assert_fields(account, "old_password", "new_password1", "new_password2")
                self.assertContains(account, reverse("logout"))
                rejected = self.client.post(reverse("password_change"), {
                    "old_password": "incorrect-current-password", "new_password1": "A-personal-secret-836!",
                    "new_password2": "A-personal-secret-836!",
                })
                self.assertEqual(rejected.status_code, 200)
                self.assertTrue(rejected.context["form"].errors["old_password"])

