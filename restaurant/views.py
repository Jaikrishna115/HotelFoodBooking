"""Server-rendered HTTP entry points. Mutations use POST and Django CSRF protection."""
from datetime import timedelta
from decimal import Decimal
from functools import wraps
import hashlib
import uuid

from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import (BookingForm, CategoryForm, CheckoutForm, DishForm, EmailAuthenticationForm,
                    RequiredPasswordChangeForm, SettingsForm, SignupForm, StaffUserForm, TableForm)
from .models import (Booking, CashPayment, Category, Dish, LoginAttempt, Order,
                     RestaurantSettings, RestaurantTable, User)
from . import services


def roles_required(*roles):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles or not request.user.is_active:
                raise PermissionDenied("Your role cannot open this page.")
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def _dashboard(user):
    if user.must_change_password:
        return "password_change"
    return {User.Role.WORKER: "worker", User.Role.BILLING: "billing"}.get(user.role, "menu")


def _error(request, error):
    for message in error.messages:
        messages.error(request, message)


def _positive_pk(value):
    """Accept only positive ASCII decimal IDs within PostgreSQL bigint range."""
    if not isinstance(value, str) or not value or len(value) > 19:
        return None
    if not value.isascii() or not value.isdecimal():
        return None
    identifier = int(value)
    return identifier if 1 <= identifier <= 2**63 - 1 else None


def _menu_context(request):
    query = request.GET.get("q", "").strip()[:120]
    selected = request.GET.get("category", "").strip()[:100]
    veg = request.GET.get("veg") == "1"
    dishes = Dish.objects.select_related("category").filter(is_available=True).order_by("-is_featured", "category__sort_order", "name")
    if query:
        dishes = dishes.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if selected:
        dishes = dishes.filter(category__slug=selected)
    if veg:
        dishes = dishes.filter(is_veg=True)
    return {"dishes": dishes, "categories": Category.objects.all(), "query": query,
            "selected_category": selected, "vegetarian_only": veg}


@require_GET
def home(request):
    context = _menu_context(request)
    context["featured_dishes"] = context["dishes"].filter(is_featured=True)[:6]
    context["dishes"] = context["dishes"][:8]
    return render(request, "restaurant/home.html", context)


@never_cache
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(_dashboard(request.user))
    form = EmailAuthenticationForm(request, data=request.POST or None)
    next_url = request.POST.get("next") or request.GET.get("next", "")
    status = 200
    if request.method == "POST":
        email = request.POST.get("username", "").strip().lower()[:254]
        ip = request.META.get("REMOTE_ADDR", "unknown")
        key = salted_hmac("restaurant-login", f"{email}|{ip}").hexdigest()
        now = timezone.now()
        with transaction.atomic():
            attempt, _ = LoginAttempt.objects.get_or_create(key=key, defaults={"window_started_at": now})
            attempt = LoginAttempt.objects.select_for_update().get(pk=attempt.pk)
            if attempt.blocked_until and attempt.blocked_until > now:
                form = EmailAuthenticationForm(request, data={})
                form.is_valid()
                form.add_error(None, "Too many sign-in attempts. Try again in 15 minutes.")
                status = 429
            elif form.is_valid():
                attempt.delete()
                user = form.get_user()
                auth_login(request, user)
                if not user.must_change_password and next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(next_url)
                return redirect(_dashboard(user))
            else:
                if attempt.window_started_at <= now - timedelta(minutes=15):
                    attempt.failures = 0
                    attempt.window_started_at = now
                attempt.failures += 1
                attempt.blocked_until = now + timedelta(minutes=15) if attempt.failures >= 5 else None
                attempt.save()
                status = 400
        # Expired counters have no value after a day; prune without storing raw emails.
        LoginAttempt.objects.filter(window_started_at__lt=now - timedelta(days=1)).delete()
    return render(request, "restaurant/login.html", {"form": form, "next": next_url}, status=status)


@require_POST
def logout_view(request):
    auth_logout(request)
    return redirect("home")


@never_cache
@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect(_dashboard(request.user))
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError:
            form.add_error("email", "An account already exists with this email address.")
        else:
            auth_login(request, user)
            messages.success(request, "Your customer account is ready.")
            return redirect("menu")
    return render(request, "restaurant/signup.html", {"form": form})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def password_change(request):
    form = RequiredPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Your password has been changed.")
        return redirect(_dashboard(user))
    return render(request, "restaurant/password_change.html", {"form": form})


@require_GET
def menu(request):
    table_id = request.GET.get("table")
    if request.user.is_authenticated and request.user.role == User.Role.WORKER and table_id:
        table_id = _positive_pk(table_id)
        table = RestaurantTable.objects.filter(pk=table_id, is_active=True).first() if table_id is not None else None
        if table:
            request.session["order_table_id"] = table.pk
    return render(request, "restaurant/menu.html", _menu_context(request))


@require_GET
def cart(request):
    return render(request, "restaurant/cart.html", services.cart_snapshot(request))


def _may_shop(request):
    if request.user.is_authenticated and request.user.role == User.Role.BILLING:
        raise PermissionDenied("Billing counter accounts do not place food orders.")


def _quantity(request, allow_zero=False):
    try:
        quantity = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        raise ValidationError("Choose a valid quantity.") from None
    if not (0 if allow_zero else 1) <= quantity <= 99:
        raise ValidationError("Quantity must be between 1 and 99, or zero to remove a dish.")
    return quantity


@require_POST
def cart_add(request, pk):
    _may_shop(request)
    dish = get_object_or_404(Dish, pk=pk, is_available=True)
    services.cart_snapshot(request)
    quantities = dict(request.session.get("cart", {}))
    try:
        quantity = _quantity(request)
        if len(quantities) >= 50 and str(pk) not in quantities:
            raise ValidationError("A cart can contain at most 50 different dishes.")
        if quantities.get(str(pk), 0) + quantity > 99:
            raise ValidationError("A dish cannot exceed 99 portions.")
        quantities[str(pk)] = quantities.get(str(pk), 0) + quantity
        request.session["cart"] = quantities
        messages.success(request, f"{dish.name} added to your cart.")
    except ValidationError as error:
        _error(request, error)
    destination = request.POST.get("next", "")
    if destination and url_has_allowed_host_and_scheme(destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(destination)
    return redirect("menu")


@require_POST
def cart_update(request, pk):
    _may_shop(request)
    services.cart_snapshot(request)
    quantities = dict(request.session.get("cart", {}))
    try:
        quantity = _quantity(request, allow_zero=True)
        if str(pk) not in quantities:
            raise ValidationError("That dish is not in your cart.")
        if quantity:
            quantities[str(pk)] = quantity
        else:
            quantities.pop(str(pk), None)
        request.session["cart"] = quantities
    except ValidationError as error:
        _error(request, error)
    return redirect("cart")


@never_cache
@roles_required(User.Role.CUSTOMER, User.Role.WORKER)
@require_http_methods(["GET", "POST"])
def checkout(request):
    context = services.cart_snapshot(request)
    if request.method == "GET":
        if not context["cart_items"] or context["cart_errors"]:
            messages.error(request, "Review your cart before checking out.")
            return redirect("cart")
        draft = {"request_id": str(uuid.uuid4()), "items": [{"dish_id": item["dish"].pk, "quantity": item["quantity"]} for item in context["cart_items"]], "total": str(context["total"])}
        request.session["checkout_draft"] = draft
        initial = {"customer_name": request.user.display_name[:120], "request_id": draft["request_id"],
                   "order_type": Order.Type.DINE_IN if request.user.role == User.Role.WORKER else Order.Type.TAKEAWAY}
        if request.user.role == User.Role.WORKER:
            initial["table"] = request.session.get("order_table_id")
        form = CheckoutForm(user=request.user, initial=initial)
    else:
        draft = request.session.get("checkout_draft", {})
        form = CheckoutForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            if str(data["request_id"]) != draft.get("request_id"):
                form.add_error(None, "This checkout has expired. Open the cart and start a new checkout.")
            else:
                try:
                    order = services.create_order(actor=request.user, items=draft.get("items", []),
                        order_type=data["order_type"], customer_name=data["customer_name"],
                        table_id=data["table"].pk if data.get("table") else None, address=data["address"],
                        notes=data["notes"], request_id=data["request_id"], expected_total=draft.get("total"))
                except ValidationError as error:
                    form.add_error(None, error)
                else:
                    request.session["cart"] = {}
                    # Retain the server-side draft so a repeated POST can recover its order.
                    messages.success(request, f"Order {order.reference} placed. Pay at the billing counter.")
                    return redirect("order_detail", pk=order.pk)
    context.update({"form": form, "request_id": draft.get("request_id", "")})
    return render(request, "restaurant/checkout.html", context)


def _order_list_context(request, query):
    status = request.GET.get("status", "")
    source = request.GET.get("source", "")
    if status in Order.Status.values:
        query = query.filter(status=status)
    if source in Order.Source.values:
        query = query.filter(source=source)
    page = Paginator(query.order_by("-created_at", "-pk"), 50).get_page(request.GET.get("page"))
    return {"orders": page.object_list, "page_obj": page, "selected_status": status,
            "selected_source": source, "status_choices": Order.Status.choices}


@never_cache
@login_required
@require_GET
def orders(request):
    return render(request, "restaurant/orders.html", _order_list_context(request, services.visible_orders(request.user)))


@never_cache
@login_required
@require_GET
def order_detail(request, pk):
    order = get_object_or_404(services.visible_orders(request.user), pk=pk)
    return render(request, "restaurant/order_detail.html", {"order": order, "items": order.items.all(),
        "status_events": order.status_events.select_related("actor"),
        "allowed_statuses": services.allowed_statuses(request.user, order),
        "workers": User.objects.filter(role=User.Role.WORKER, is_active=True) if request.user.role == User.Role.BILLING else User.objects.none(),
        "can_assign": request.user.role == User.Role.BILLING and order.source == Order.Source.ONLINE and order.is_active,
        "can_collect": request.user.role == User.Role.BILLING and order.payment_status == Order.PaymentStatus.UNPAID and order.status != Order.Status.CANCELLED,
        "payment_request_id": str(uuid.uuid4())})


@login_required
@require_POST
def order_status(request, pk):
    get_object_or_404(services.visible_orders(request.user), pk=pk)
    try:
        services.change_order_status(actor=request.user, order_id=pk, status=request.POST.get("status", ""))
        messages.success(request, "Order status updated.")
    except ValidationError as error:
        _error(request, error)
    return redirect("order_detail", pk=pk)


@roles_required(User.Role.BILLING)
@require_POST
def order_assign(request, pk):
    get_object_or_404(Order, pk=pk)
    worker_id = _positive_pk(request.POST.get("worker_id", ""))
    if worker_id is None:
        messages.error(request, "Choose an active worker.")
    else:
        try:
            services.assign_order(actor=request.user, order_id=pk, worker_id=worker_id)
            messages.success(request, "Responsible worker assigned.")
        except ValidationError as error:
            _error(request, error)
    return redirect("order_detail", pk=pk)


@roles_required(User.Role.BILLING)
@require_POST
def order_collect(request, pk):
    get_object_or_404(Order, pk=pk)
    try:
        services.collect_cash(actor=request.user, order_id=pk, request_id=request.POST.get("request_id") or uuid.uuid4())
        messages.success(request, "Cash collection recorded. A receipt is available below.")
    except ValidationError as error:
        _error(request, error)
    return redirect("order_detail", pk=pk)


@never_cache
@roles_required(User.Role.WORKER)
@require_GET
def worker(request):
    query = services.visible_orders(request.user)
    context = _order_list_context(request, query)
    context.update({"tables": RestaurantTable.objects.filter(is_active=True),
                    "active_count": query.exclude(status__in=[Order.Status.COMPLETED, Order.Status.CANCELLED]).count()})
    return render(request, "restaurant/worker.html", context)


@never_cache
@roles_required(User.Role.BILLING)
@require_GET
def billing(request):
    query = services.visible_orders(request.user)
    context = _order_list_context(request, query)
    unpaid = query.filter(payment_status=Order.PaymentStatus.UNPAID).exclude(status=Order.Status.CANCELLED)
    active_count = query.exclude(status__in=[Order.Status.COMPLETED, Order.Status.CANCELLED]).count()
    unassigned_count = query.filter(source=Order.Source.ONLINE, assigned_worker__isnull=True).exclude(status__in=[Order.Status.COMPLETED, Order.Status.CANCELLED]).count()
    paid_today = CashPayment.objects.filter(collected_at__date=timezone.localdate()).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    context.update({"active_count": active_count, "unpaid_count": unpaid.count(),
                    "unassigned_count": unassigned_count, "cash_today": paid_today,
                    "summary": {"active_count": active_count, "unassigned_count": unassigned_count,
                        "unpaid_total": unpaid.aggregate(total=Sum("total"))["total"] or Decimal("0.00"),
                        "today_paid_total": paid_today}})
    return render(request, "restaurant/billing.html", context)


@never_cache
@login_required
@require_GET
def order_updates(request):
    summary = services.visible_orders(request.user).aggregate(count=Count("pk"), latest=Max("updated_at"))
    # Count changes on reassignment revoke old workers' records; the timestamp covers edits.
    value = f"{summary['count']}|{summary['latest']}"
    return JsonResponse({"revision": hashlib.sha256(value.encode()).hexdigest(), "count": summary["count"]})


@roles_required(User.Role.BILLING)
@require_http_methods(["GET", "POST"])
def settings_view(request):
    instance = RestaurantSettings.current()
    form = SettingsForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Restaurant settings saved.")
        return redirect("settings")
    return render(request, "restaurant/settings.html", {"form": form})


@roles_required(User.Role.BILLING)
@require_http_methods(["GET", "POST"])
def users(request):
    if request.method == "POST":
        user_id = _positive_pk(request.POST.get("user_id", ""))
        if user_id is None:
            messages.error(request, "Choose a staff account.")
        else:
            get_object_or_404(User, pk=user_id)
            try:
                services.update_staff_user(actor=request.user, user_id=user_id, role=request.POST.get("role", ""), is_active=request.POST.get("is_active") in {"on", "1", "true"})
                messages.success(request, "Staff account updated.")
            except ValidationError as error:
                _error(request, error)
        return redirect("users")
    return render(request, "restaurant/users.html", {"staff_users": User.objects.filter(role__in=[User.Role.WORKER, User.Role.BILLING]).order_by("first_name", "email")})


@roles_required(User.Role.BILLING)
@require_http_methods(["GET", "POST"])
def user_create(request):
    form = StaffUserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            data = form.cleaned_data
            services.create_staff_user(actor=request.user, name=data["name"], email=data["email"], role=data["role"], initial_password=data["initial_password"])
        except (ValidationError, IntegrityError) as error:
            form.add_error(None, error if isinstance(error, ValidationError) else "An account already exists with this email address.")
        else:
            messages.success(request, "Staff account created. Share the initial password privately; a password change is required at first login.")
            return redirect("users")
    return render(request, "restaurant/user_create.html", {"form": form})


@login_required
@require_GET
def bookings(request):
    query = Booking.objects.select_related("user")
    if request.user.role != User.Role.BILLING:
        query = query.filter(user=request.user)
    page = Paginator(query, 50).get_page(request.GET.get("page"))
    return render(request, "restaurant/bookings.html", {"bookings": page.object_list, "page_obj": page,
        "can_manage": request.user.role == User.Role.BILLING, "booking_status_choices": Booking.Status.choices, "now": timezone.now()})


@roles_required(User.Role.CUSTOMER, User.Role.WORKER)
@require_http_methods(["GET", "POST"])
def book_table(request):
    form = BookingForm(request.POST or None, initial={"customer_name": request.user.display_name[:120], "guests": 2})
    if request.method == "POST" and form.is_valid():
        try:
            services.create_booking(actor=request.user, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Reservation requested. The billing counter will confirm it.")
            return redirect("bookings")
    return render(request, "restaurant/book_table.html", {"form": form})


@login_required
@require_POST
def booking_update(request, pk):
    query = Booking.objects.all() if request.user.role == User.Role.BILLING else Booking.objects.filter(user=request.user)
    get_object_or_404(query, pk=pk)
    try:
        services.update_booking_status(actor=request.user, booking_id=pk, status=request.POST.get("status", ""))
        messages.success(request, "Reservation updated.")
    except ValidationError as error:
        _error(request, error)
    return redirect("bookings")


@roles_required(User.Role.BILLING)
@require_http_methods(["GET", "POST"])
def menu_manage(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Menu category created.")
        return redirect("menu_manage")
    return render(request, "restaurant/menu_manage.html", {"dishes": Dish.objects.select_related("category"), "categories": Category.objects.all(), "form": form, "category_form": form})


@roles_required(User.Role.BILLING)
@require_http_methods(["GET", "POST"])
def dish_create(request):
    return _dish_form(request)


@roles_required(User.Role.BILLING)
@require_http_methods(["GET", "POST"])
def dish_edit(request, pk):
    dish = get_object_or_404(Dish, pk=pk)
    if request.method == "POST" and request.POST.get("action") == "delete":
        with transaction.atomic():
            dish = get_object_or_404(Dish.objects.select_for_update(of=("self",)), pk=pk)
            dish.delete()
        messages.success(request, "Dish removed. Existing orders retain their original names and prices.")
        return redirect("menu_manage")
    return _dish_form(request, dish)


def _dish_form(request, dish=None):
    form = DishForm(request.POST or None, instance=dish)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Dish saved.")
        return redirect("menu_manage")
    return render(request, "restaurant/dish_form.html", {"form": form, "dish": dish, "is_edit": dish is not None})


@roles_required(User.Role.BILLING)
@require_http_methods(["GET", "POST"])
def tables(request):
    table_id = request.POST.get("table_id") if request.method == "POST" else request.GET.get("edit")
    instance = None
    if table_id:
        table_id = _positive_pk(table_id)
        if table_id is None:
            raise Http404("Choose a valid table.")
        instance = get_object_or_404(RestaurantTable, pk=table_id)
    form = TableForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Table saved.")
        return redirect("tables")
    return render(request, "restaurant/tables.html", {"tables": RestaurantTable.objects.all(), "form": form, "editing_table": instance})
