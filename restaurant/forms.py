from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from .models import Booking, Category, Dish, Order, RestaurantSettings, RestaurantTable, User


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email address", widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}))

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class SignupForm(UserCreationForm):
    name = forms.CharField(max_length=120, label="Your name")
    email = forms.EmailField(label="Email address")

    class Meta:
        model = User
        fields = ("name", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account already exists with this email address.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["name"]
        user.email = self.cleaned_data["email"]
        user.username = user.email
        user.role = User.Role.CUSTOMER
        user.is_staff = False
        user.is_superuser = False
        user.must_change_password = False
        if commit:
            user.save()
        return user


class StaffUserForm(forms.Form):
    name = forms.CharField(max_length=120)
    email = forms.EmailField()
    role = forms.ChoiceField(choices=[(User.Role.WORKER, "Worker"), (User.Role.BILLING, "Billing counter")])
    initial_password = forms.CharField(widget=forms.PasswordInput, help_text="Share this initial password privately. The employee must change it at first login.")
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account already exists with this email address.")
        return email

    def clean(self):
        data = super().clean()
        if data.get("initial_password") != data.get("confirm_password"):
            self.add_error("confirm_password", "The passwords do not match.")
        if data.get("initial_password"):
            user = User(email=data.get("email", ""), first_name=data.get("name", ""))
            try:
                validate_password(data["initial_password"], user)
            except ValidationError as error:
                self.add_error("initial_password", error)
        return data


class CheckoutForm(forms.Form):
    customer_name = forms.CharField(max_length=120, label="Customer name")
    order_type = forms.ChoiceField(choices=Order.Type.choices, label="Order type")
    table = forms.ModelChoiceField(queryset=RestaurantTable.objects.none(), required=False, empty_label="Choose a table")
    address = forms.CharField(max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Delivery address")
    notes = forms.CharField(max_length=1000, required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Kitchen notes")
    request_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["table"].queryset = RestaurantTable.objects.filter(is_active=True)
        if user and user.role == User.Role.WORKER:
            self.fields["order_type"].choices = [(Order.Type.DINE_IN, "Dine in")]
            self.fields["table"].required = True

    def clean(self):
        data = super().clean()
        if data.get("order_type") == Order.Type.DELIVERY and not data.get("address"):
            self.add_error("address", "Enter the delivery address.")
        if data.get("table") and data.get("order_type") != Order.Type.DINE_IN:
            self.add_error("table", "Choose a table only for dine-in orders.")
        return data


class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ["customer_name", "date_time", "guests", "notes"]
        widgets = {"date_time": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), "notes": forms.Textarea(attrs={"rows": 3})}


class DishForm(forms.ModelForm):
    class Meta:
        model = Dish
        fields = ["name", "description", "category", "price", "image_url", "is_veg", "is_available", "is_featured", "prep_minutes"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "slug", "sort_order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["sort_order"].required = False

    def clean_sort_order(self):
        return self.cleaned_data.get("sort_order") or 0

    def clean(self):
        data = super().clean()
        slug = data.get("slug") or slugify(data.get("name", ""))
        if not slug:
            self.add_error("slug", "Enter a category URL name.")
        elif Category.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
            self.add_error("slug", "This category URL name is already in use.")
        data["slug"] = slug
        return data


class TableForm(forms.ModelForm):
    class Meta:
        model = RestaurantTable
        fields = ["number", "seats", "is_active"]


class SettingsForm(forms.ModelForm):
    class Meta:
        model = RestaurantSettings
        fields = ["name", "tagline", "phone", "email", "address", "opening_hours", "accepting_orders"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class RequiredPasswordChangeForm(PasswordChangeForm):
    def save(self, commit=True):
        user = super().save(commit=False)
        user.must_change_password = False
        if commit:
            user.save(update_fields=["password", "must_change_password"])
        return user
