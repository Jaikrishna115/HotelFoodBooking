from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from restaurant.models import Category, Dish, RestaurantSettings, RestaurantTable


MENU = [
    ("Starters", "starters", "Paneer Tikka", "Charred paneer, peppers and onions with a mint chutney.", "220.00", True, 20, True, "paneer"),
    ("Starters", "starters", "Crispy Corn", "Golden corn tossed with peppers, spring onion and a little heat.", "160.00", True, 15, False, "corn"),
    ("Starters", "starters", "Chicken Tikka", "Yogurt-marinated chicken cooked until smoky and tender.", "280.00", False, 25, True, "chicken"),
    ("Main Course", "main-course", "Butter Chicken", "Tender chicken in a creamy tomato sauce, finished with butter.", "320.00", False, 25, True, "butter-chicken"),
    ("Main Course", "main-course", "Paneer Butter Masala", "Soft paneer in a smooth tomato, cashew and cream gravy.", "260.00", True, 20, True, "paneer-curry"),
    ("Main Course", "main-course", "Vegetable Biryani", "Fragrant basmati rice layered with vegetables and aromatic spices.", "220.00", True, 25, True, "biryani"),
    ("Main Course", "main-course", "Chicken Biryani", "Slow-cooked chicken and basmati rice with warming spices.", "290.00", False, 30, True, "chicken-biryani"),
    ("Breads", "breads", "Butter Naan", "Soft tandoor bread brushed with melted butter.", "50.00", True, 10, False, "naan"),
    ("Desserts", "desserts", "Gulab Jamun", "Warm milk dumplings in fragrant cardamom syrup.", "90.00", True, 10, False, "gulab-jamun"),
    ("Desserts", "desserts", "Chocolate Brownie", "A rich chocolate brownie served warm.", "140.00", True, 12, True, "brownie"),
    ("Beverages", "beverages", "Fresh Lime Soda", "Fresh lime with soda, served sweet or salted.", "80.00", True, 5, False, "lime"),
    ("Beverages", "beverages", "Mango Lassi", "Mango blended with chilled yogurt.", "120.00", True, 5, True, "lassi"),
]

IMAGES = {
    "paneer": "photo-1567188040759-fb8a883dc6d8", "butter-chicken": "photo-1603894584373-5ac82b2ae398",
    "paneer-curry": "https://images.pexels.com/photos/9609838/pexels-photo-9609838.jpeg?auto=compress&cs=tinysrgb&w=800",
    "biryani": "https://images.pexels.com/photos/35041655/pexels-photo-35041655.jpeg?auto=compress&cs=tinysrgb&w=800",
    "chicken-biryani": "https://images.pexels.com/photos/4224312/pexels-photo-4224312.jpeg?auto=compress&cs=tinysrgb&w=800",
    "brownie": "photo-1606313564200-e75d5e30476c",
    "chicken": "https://images.pexels.com/photos/30749024/pexels-photo-30749024.jpeg?auto=compress&cs=tinysrgb&w=800",
    "corn": "https://images.pexels.com/photos/18379774/pexels-photo-18379774.jpeg?auto=compress&cs=tinysrgb&w=800",
    "naan": "https://images.pexels.com/photos/20446413/pexels-photo-20446413.jpeg?auto=compress&cs=tinysrgb&w=800",
    "gulab-jamun": "https://images.pexels.com/photos/7449105/pexels-photo-7449105.jpeg?auto=compress&cs=tinysrgb&w=800",
    "lime": "https://images.pexels.com/photos/4045205/pexels-photo-4045205.jpeg?auto=compress&cs=tinysrgb&w=800",
    "lassi": "https://images.pexels.com/photos/17200460/pexels-photo-17200460.jpeg?auto=compress&cs=tinysrgb&w=800",
}


class Command(BaseCommand):
    help = "Add starter dishes and tables without replacing existing restaurant edits."

    def add_arguments(self, parser):
        parser.add_argument("--fill-missing-images", action="store_true", help="Add sample photographs only to seeded dishes whose image URL is empty.")

    @transaction.atomic
    def handle(self, *args, **options):
        RestaurantSettings.current()
        created_count = 0
        category_order = {}
        for category_name, slug, name, description, price, veg, prep, featured, image in MENU:
            category_order.setdefault(slug, len(category_order))
            category, _ = Category.objects.get_or_create(slug=slug, defaults={"name": category_name, "sort_order": category_order[slug]})
            image_ref = IMAGES.get(image, "")
            image_url = image_ref if image_ref.startswith("https://") else (f"https://images.unsplash.com/{image_ref}?w=800&q=85" if image_ref else "")
            dish, created = Dish.objects.get_or_create(name=name, category=category, defaults={
                "description": description, "price": Decimal(price), "is_veg": veg,
                "prep_minutes": prep, "is_featured": featured, "is_available": True,
                "image_url": image_url})
            if options.get("fill_missing_images") and not dish.image_url:
                dish.image_url = image_url
                dish.save(update_fields=["image_url", "updated_at"])
            created_count += int(created)
        for number in range(1, 9):
            RestaurantTable.objects.get_or_create(number=number, defaults={"seats": 4})
        self.stdout.write(self.style.SUCCESS(f"Added {created_count} dishes. Existing menu entries, settings and tables were preserved."))
