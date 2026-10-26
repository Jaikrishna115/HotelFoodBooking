"""Create the first counter account without a published or built-in password."""
import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from restaurant.models import User


class Command(BaseCommand):
    help = "Create an initial Billing account. Existing accounts are never overwritten."

    def add_arguments(self, parser):
        parser.add_argument("--email")
        parser.add_argument("--name")
        parser.add_argument("--noinput", action="store_true", help="Read the password from BOOTSTRAP_BILLING_PASSWORD; never prompt.")

    def handle(self, *args, **options):
        email = (options.get("email") or "").strip().lower()
        if not email and User.objects.filter(role=User.Role.BILLING).exists():
            self.stdout.write("A Billing account already exists. No changes made.")
            return
        if not email:
            if options["noinput"]:
                raise CommandError("Supply --email with --noinput.")
            email = input("Billing email: ").strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError("Enter a valid email address.") from None
        existing = User.objects.filter(email__iexact=email).first()
        if existing:
            if existing.role != User.Role.BILLING:
                raise CommandError("That email belongs to another account. It was not promoted or changed.")
            self.stdout.write("This Billing account already exists. Its password and permissions were not changed.")
            return
        name = (options.get("name") or "").strip()
        if not name and not options["noinput"]:
            name = input("Billing person's name: ").strip()
        if not name or len(name) > 120:
            raise CommandError("Supply a name containing 1 to 120 characters.")
        password = os.environ.get("BOOTSTRAP_BILLING_PASSWORD", "")
        if not password:
            if options["noinput"]:
                raise CommandError("Set BOOTSTRAP_BILLING_PASSWORD before using --noinput.")
            password = getpass.getpass("Initial password (hidden): ")
            if password != getpass.getpass("Repeat initial password (hidden): "):
                raise CommandError("The passwords did not match.")
        user = User(email=email, username=email, first_name=name, role=User.Role.BILLING,
                    must_change_password=True, is_staff=False, is_superuser=False)
        try:
            validate_password(password, user)
            user.set_password(password)
            user.full_clean(exclude=["last_login", "date_joined"])
            with transaction.atomic():
                user.save()
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from None
        except IntegrityError:
            raise CommandError("An account with this email was created concurrently. No existing account was changed.") from None
        self.stdout.write(self.style.SUCCESS(f"Billing account created for {email}. A password change is required at first login."))
