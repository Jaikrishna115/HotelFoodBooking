"""Database records. Prices are rupee Decimals; order lines retain their snapshots."""
from decimal import Decimal
import uuid

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.text import slugify


class UserManager(DjangoUserManager):
    def create_user(self, email=None, password=None, **extra_fields):
        email = email or extra_fields.pop("username", None)
        if not email:
            raise ValueError("An email address is required.")
        extra_fields.pop("username", None)
        email = self.normalize_email(email).strip().lower()
        user = self.model(email=email, username=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "billing")
        if not extra_fields.get("is_staff") or not extra_fields.get("is_superuser"):
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        WORKER = "worker", "Worker"
        BILLING = "billing", "Billing counter"

    username = models.CharField(max_length=254, unique=True)
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.CUSTOMER)
    must_change_password = models.BooleanField(default=False)
    created_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_users")
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        self.username = self.email
        if kwargs.get("update_fields") and "email" in kwargs["update_fields"]:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"username"}
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name().strip() or self.email

    def __str__(self):
        return self.display_name


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Dish(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="dishes")
    name = models.CharField(max_length=120)
    description = models.TextField(max_length=1500, blank=True)
    price = models.DecimalField(max_digits=9, decimal_places=2, validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("100000.00"))])
    image_url = models.URLField(max_length=800, blank=True)
    is_veg = models.BooleanField(default=True)
    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    prep_minutes = models.PositiveSmallIntegerField(default=20, validators=[MinValueValidator(1), MaxValueValidator(240)])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__sort_order", "name"]
        constraints = [models.CheckConstraint(condition=Q(price__gt=0), name="dish_positive_price")]

    def __str__(self):
        return self.name


class RestaurantTable(models.Model):
    number = models.PositiveSmallIntegerField(unique=True, validators=[MinValueValidator(1), MaxValueValidator(999)])
    seats = models.PositiveSmallIntegerField(default=4, validators=[MinValueValidator(1), MaxValueValidator(30)])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"Table {self.number} ({self.seats} seats)"


class Order(models.Model):
    class Source(models.TextChoices):
        ONLINE = "online", "Customer online"
        STAFF = "staff", "Table order"

    class Type(models.TextChoices):
        DINE_IN = "dine_in", "Dine in"
        TAKEAWAY = "takeaway", "Takeaway"
        DELIVERY = "delivery", "Delivery"

    class Status(models.TextChoices):
        PLACED = "placed", "Placed"
        ACCEPTED = "accepted", "Accepted"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Pay at counter"
        PAID = "paid", "Paid"

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="orders")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="orders_created")
    created_by_name = models.CharField(max_length=254)
    source = models.CharField(max_length=10, choices=Source.choices)
    table = models.ForeignKey(RestaurantTable, null=True, blank=True, on_delete=models.PROTECT, related_name="orders")
    assigned_worker = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_orders")
    assigned_at = models.DateTimeField(null=True, blank=True)
    customer_name = models.CharField(max_length=120)
    order_type = models.CharField(max_length=12, choices=Type.choices)
    address = models.CharField(max_length=500, blank=True)
    notes = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLACED)
    payment_status = models.CharField(max_length=8, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    payment_method = models.CharField(max_length=12, default="cash", editable=False)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    needs_refund = models.BooleanField(default=False)
    request_id = models.UUIDField(default=uuid.uuid4)
    request_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["created_by", "request_id"], name="order_creator_request_unique"), models.CheckConstraint(condition=Q(total__gt=0), name="order_positive_total")]
        indexes = [models.Index(fields=["user", "-created_at"]), models.Index(fields=["assigned_worker", "status"]), models.Index(fields=["status", "-created_at"])]

    @property
    def reference(self):
        return f"HF-{self.pk:06d}" if self.pk else "New order"

    @property
    def is_active(self):
        return self.status not in {self.Status.COMPLETED, self.Status.CANCELLED}

    def __str__(self):
        return self.reference


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    dish = models.ForeignKey(Dish, null=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=9, decimal_places=2)
    quantity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(99)])

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=1) & Q(quantity__lte=99), name="order_item_quantity_range"), models.CheckConstraint(condition=Q(unit_price__gt=0), name="order_item_positive_price")]

    @property
    def line_total(self):
        return self.unit_price * self.quantity


class OrderStatusEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_events")
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12, choices=Order.Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class CashPayment(models.Model):
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="cash_payment")
    collected_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="cash_collections")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    request_id = models.UUIDField(default=uuid.uuid4, unique=True)
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-collected_at"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="cash_payment_positive_amount")]


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="bookings")
    customer_name = models.CharField(max_length=120)
    date_time = models.DateTimeField()
    guests = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    notes = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_time"]
        indexes = [models.Index(fields=["user", "-date_time"])]
        constraints = [models.CheckConstraint(condition=Q(guests__gte=1) & Q(guests__lte=12), name="booking_guests_range")]


class RestaurantSettings(models.Model):
    """The single row has primary key 1. Editing changes the public contact details."""
    name = models.CharField(max_length=120, default="Grand Table")
    tagline = models.CharField(max_length=180, default="Good food. Warm company.")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=500, blank=True)
    opening_hours = models.CharField(max_length=250, default="Daily · 11:00 AM – 11:00 PM")
    accepting_orders = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def current(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def __str__(self):
        return self.name


class LoginAttempt(models.Model):
    """Short-lived rate-limit counters, keyed by a digest of email and remote IP."""
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveSmallIntegerField(default=0)
    window_started_at = models.DateTimeField()
    blocked_until = models.DateTimeField(null=True, blank=True)
