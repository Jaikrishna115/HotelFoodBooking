"""Authoritative business rules shared by HTTP views and management tests.

Every business mutation runs in a transaction. Row locks are effective on the
production PostgreSQL database; SQLite is only suitable for local smoke tests.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import (Booking, CashPayment, Dish, Order, OrderItem, OrderStatusEvent,
                     RestaurantSettings, RestaurantTable, User)


TRANSITIONS = {
    "placed": ("accepted", "cancelled"),
    "accepted": ("preparing", "cancelled"),
    "preparing": ("ready", "cancelled"),
    "ready": ("completed", "cancelled"),
    "completed": (), "cancelled": (),
}


def _actor(actor, roles=None, lock=True):
    if not getattr(actor, "is_authenticated", False):
        raise PermissionDenied("Please sign in.")
    query = User.objects.select_for_update() if lock else User.objects
    current = query.filter(pk=actor.pk, is_active=True).first()
    if not current or (roles is not None and current.role not in roles):
        raise PermissionDenied("Your role cannot perform this action.")
    if current.must_change_password:
        raise PermissionDenied("Change your initial password before continuing.")
    return current


def _text(value, field, maximum, required=False):
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text.")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise ValidationError(f"Enter a valid {field.lower()} (up to {maximum} characters).")
    return value


def _uuid(value, field="request ID"):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError(f"A valid {field} is required.") from None


def _money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > Decimal("9999999999.99"):
            raise ValueError
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Enter a valid total.") from None


def visible_orders(actor):
    """Query authorization is checked again for every mutating operation."""
    if not getattr(actor, "is_authenticated", False) or not actor.is_active:
        return Order.objects.none()
    base = Order.objects.select_related("table", "user", "created_by", "assigned_worker")
    if actor.role == User.Role.BILLING:
        return base
    if actor.role == User.Role.WORKER:
        return base.filter(Q(source=Order.Source.STAFF, user=actor, created_by=actor) | Q(source=Order.Source.ONLINE, assigned_worker=actor))
    return base.filter(user=actor, source=Order.Source.ONLINE)


def can_update_status(actor, order):
    return bool(actor.is_authenticated and actor.is_active and actor.role == User.Role.WORKER and (
        (order.source == Order.Source.STAFF and order.user_id == actor.pk and order.created_by_id == actor.pk)
        or (order.source == Order.Source.ONLINE and order.assigned_worker_id == actor.pk)
    ))


def allowed_statuses(actor, order):
    if not can_update_status(actor, order):
        return []
    labels = dict(Order.Status.choices)
    return [(value, labels[value]) for value in TRANSITIONS[order.status]
            if value != Order.Status.COMPLETED or order.payment_status == Order.PaymentStatus.PAID]


@transaction.atomic
def create_order(*, actor, items, order_type, request_id, customer_name="", table_id=None,
                 address="", notes="", expected_total=None):
    actor = _actor(actor, {User.Role.CUSTOMER, User.Role.WORKER})
    request_id = _uuid(request_id)
    if order_type not in Order.Type.values:
        raise ValidationError("Choose a valid order type.")
    customer_name = _text(customer_name or actor.display_name, "Customer name", 120, True)
    address = _text(address, "Address", 500)
    notes = _text(notes, "Notes", 1000)
    if order_type == Order.Type.DELIVERY and not address:
        raise ValidationError("A delivery address is required.")
    if table_id not in (None, ""):
        try:
            table_id = int(table_id)
            if table_id < 1:
                raise ValueError
        except (ValueError, TypeError):
            raise ValidationError("Choose a valid table.") from None
    else:
        table_id = None
    if actor.role == User.Role.WORKER and (order_type != Order.Type.DINE_IN or not table_id):
        raise PermissionDenied("Workers can create dine-in table orders only.")
    if table_id and order_type != Order.Type.DINE_IN:
        raise ValidationError("A table is only used for dine-in orders.")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValidationError("Choose between 1 and 50 dishes.")
    quantities = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("Invalid cart item.")
        dish_id, quantity = item.get("dish_id"), item.get("quantity")
        if type(dish_id) is not int or dish_id < 1 or type(quantity) is not int or not 1 <= quantity <= 99:
            raise ValidationError("Each dish needs a quantity between 1 and 99.")
        quantities[dish_id] = quantities.get(dish_id, 0) + quantity
        if quantities[dish_id] > 99:
            raise ValidationError("A dish cannot exceed 99 portions.")
    expected = _money(expected_total) if expected_total is not None else None
    canonical = {"items": sorted(quantities.items()), "order_type": order_type,
                 "customer_name": customer_name, "table_id": table_id,
                 "address": address, "notes": notes,
                 "expected_total": str(expected) if expected is not None else None}
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    existing = Order.objects.filter(created_by=actor, request_id=request_id).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise ValidationError("This checkout request was already used with different details. Start a new checkout.")
        return existing
    settings = RestaurantSettings.current()
    if not settings.accepting_orders:
        raise ValidationError("The restaurant is currently not accepting orders.")
    table = None
    if table_id:
        table = RestaurantTable.objects.select_for_update().filter(pk=table_id, is_active=True).first()
        if not table:
            raise ValidationError("That table is not available for ordering.")
    dishes = {dish.pk: dish for dish in Dish.objects.select_for_update(of=("self",)).filter(pk__in=quantities)}
    if len(dishes) != len(quantities) or any(not dish.is_available for dish in dishes.values()):
        raise ValidationError("A dish is no longer available. Review your cart.")
    total = sum((dishes[key].price * quantity for key, quantity in quantities.items()), Decimal("0.00"))
    if total <= 0 or total > Decimal("9999999999.99"):
        raise ValidationError("This order total is outside the supported range.")
    if expected is not None and total != expected:
        raise ValidationError("Menu prices changed. Review the updated total before placing your order.")
    order = Order.objects.create(user=actor, created_by=actor, created_by_name=actor.display_name[:254],
        source=Order.Source.STAFF if actor.role == User.Role.WORKER else Order.Source.ONLINE,
        table=table, customer_name=customer_name, order_type=order_type, address=address,
        notes=notes, total=total, request_id=request_id, request_fingerprint=fingerprint)
    OrderItem.objects.bulk_create([OrderItem(order=order, dish=dishes[key], name=dishes[key].name,
        unit_price=dishes[key].price, quantity=quantity) for key, quantity in sorted(quantities.items())])
    OrderStatusEvent.objects.create(order=order, actor=actor, from_status="", to_status=order.status)
    return order


@transaction.atomic
def assign_order(*, actor, order_id, worker_id):
    actor = _actor(actor, {User.Role.BILLING})
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.source != Order.Source.ONLINE or not order.is_active:
        raise ValidationError("Only active customer orders can be assigned.")
    worker = User.objects.filter(pk=worker_id, role=User.Role.WORKER, is_active=True).first()
    if not worker:
        raise ValidationError("Choose an active worker.")
    order.assigned_worker = worker
    order.assigned_at = timezone.now()
    order.save(update_fields=["assigned_worker", "assigned_at", "updated_at"])
    return order


@transaction.atomic
def change_order_status(*, actor, order_id, status):
    actor = _actor(actor, {User.Role.WORKER})
    order = Order.objects.select_for_update().get(pk=order_id)
    if not can_update_status(actor, order):
        raise PermissionDenied("Only the responsible worker can update this order.")
    if status == order.status:
        return order
    if status not in TRANSITIONS[order.status]:
        raise ValidationError("That status change is not allowed.")
    if status == Order.Status.COMPLETED and order.payment_status != Order.PaymentStatus.PAID:
        raise ValidationError("The billing counter must collect payment before completion.")
    previous = order.status
    order.status = status
    if status == Order.Status.CANCELLED and order.payment_status == Order.PaymentStatus.PAID:
        order.needs_refund = True
    order.save(update_fields=["status", "needs_refund", "updated_at"])
    OrderStatusEvent.objects.create(order=order, actor=actor, from_status=previous, to_status=status)
    return order


@transaction.atomic
def collect_cash(*, actor, order_id, request_id):
    actor = _actor(actor, {User.Role.BILLING})
    request_id = _uuid(request_id)
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.status == Order.Status.CANCELLED:
        raise ValidationError("Cash cannot be collected for a cancelled order.")
    if order.payment_method != "cash":
        raise ValidationError("This order is not a cash order.")
    existing = CashPayment.objects.filter(order=order).first()
    if existing:
        return existing
    if CashPayment.objects.filter(request_id=request_id).exists():
        raise ValidationError("This cash collection request was already used for another order.")
    if order.payment_status == Order.PaymentStatus.PAID:
        raise ValidationError("This order is already paid.")
    try:
        payment = CashPayment.objects.create(order=order, collected_by=actor, amount=order.total, request_id=request_id)
    except IntegrityError:
        raise ValidationError("This cash collection request was already used. Refresh the order before trying again.") from None
    order.payment_status = Order.PaymentStatus.PAID
    order.paid_at = timezone.now()
    order.save(update_fields=["payment_status", "paid_at", "updated_at"])
    return payment


@transaction.atomic
def create_booking(*, actor, customer_name, date_time, guests, notes=""):
    actor = _actor(actor, {User.Role.CUSTOMER, User.Role.WORKER})
    customer_name = _text(customer_name, "Customer name", 120, True)
    notes = _text(notes, "Notes", 1000)
    if not hasattr(date_time, "tzinfo") or timezone.is_naive(date_time):
        raise ValidationError("Choose a valid date and time.")
    now = timezone.now()
    if not now + timedelta(minutes=30) <= date_time <= now + timedelta(days=90):
        raise ValidationError("Book at least 30 minutes ahead and no more than 90 days ahead.")
    if type(guests) is not int or not 1 <= guests <= 12:
        raise ValidationError("Bookings support 1 to 12 guests.")
    return Booking.objects.create(user=actor, customer_name=customer_name, date_time=date_time, guests=guests, notes=notes)


@transaction.atomic
def update_booking_status(*, actor, booking_id, status):
    actor = _actor(actor, {User.Role.CUSTOMER, User.Role.WORKER, User.Role.BILLING})
    booking = Booking.objects.select_for_update().get(pk=booking_id)
    if actor.role != User.Role.BILLING and (booking.user_id != actor.pk or status != Booking.Status.CANCELLED):
        raise PermissionDenied("You can only cancel your own future reservation.")
    if status not in Booking.Status.values:
        raise ValidationError("Choose a valid booking status.")
    if booking.status == Booking.Status.CANCELLED and status != booking.status:
        raise ValidationError("A cancelled booking cannot be reopened.")
    if booking.date_time <= timezone.now() and status != booking.status:
        raise ValidationError("A past booking cannot be changed.")
    booking.status = status
    booking.save(update_fields=["status", "updated_at"])
    return booking


@transaction.atomic
def create_staff_user(*, actor, name, email, role, initial_password):
    actor = _actor(actor, {User.Role.BILLING})
    name = _text(name, "Name", 120, True)
    email = _text(email, "Email", 254, True).lower()
    validate_email(email)
    if role not in {User.Role.WORKER, User.Role.BILLING}:
        raise ValidationError("Choose Worker or Billing counter.")
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError("An account already exists with that email.")
    user = User(email=email, username=email, first_name=name, role=role, created_by=actor,
                must_change_password=True, is_staff=False, is_superuser=False)
    validate_password(initial_password, user)
    user.set_password(initial_password)
    user.full_clean(exclude=["last_login", "date_joined"])
    user.save()
    return user


@transaction.atomic
def update_staff_user(*, actor, user_id, role, is_active):
    actor = _actor(actor, {User.Role.BILLING})
    if role not in {User.Role.WORKER, User.Role.BILLING}:
        raise ValidationError("Choose Worker or Billing counter.")
    target = User.objects.select_for_update().get(pk=user_id)
    if target.role not in {User.Role.WORKER, User.Role.BILLING} or target.is_superuser:
        raise PermissionDenied("This account cannot be managed from the employee directory.")
    if target.pk == actor.pk and (role != User.Role.BILLING or not is_active):
        raise ValidationError("You cannot disable or demote your own account.")
    if target.role == User.Role.BILLING and target.is_active and (role != User.Role.BILLING or not is_active):
        if not User.objects.filter(role=User.Role.BILLING, is_active=True).exclude(pk=target.pk).exists():
            raise ValidationError("At least one active Billing counter account is required.")
    target.role = role
    target.is_active = bool(is_active)
    target.is_staff = False
    target.save(update_fields=["role", "is_active", "is_staff"])
    return target


def cart_snapshot(request):
    raw = request.session.get("cart", {})
    if not isinstance(raw, dict):
        raw = {}
    quantities = {}
    for key, quantity in raw.items():
        try:
            dish_id = int(key)
        except (ValueError, TypeError):
            continue
        if dish_id > 0 and type(quantity) is int and 1 <= quantity <= 99:
            quantities[dish_id] = quantity
    dishes = {dish.pk: dish for dish in Dish.objects.select_related("category").filter(pk__in=quantities)}
    cart_items, cart_errors = [], []
    for key, quantity in quantities.items():
        dish = dishes.get(key)
        if not dish:
            cart_errors.append("A dish was removed from the menu. It has been removed from your cart.")
            continue
        if not dish.is_available:
            cart_errors.append(f"{dish.name} is currently unavailable. Remove it to continue.")
        cart_items.append({"dish": dish, "quantity": quantity, "line_total": dish.price * quantity})
    clean_cart = {str(item["dish"].pk): item["quantity"] for item in cart_items}
    if clean_cart != raw:
        request.session["cart"] = clean_cart
    total = sum((item["line_total"] for item in cart_items), Decimal("0.00"))
    return {"cart_items": cart_items, "cart_errors": cart_errors, "cart_total": total,
            "total": total, "cart_count": sum(item["quantity"] for item in cart_items)}
