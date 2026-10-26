from .models import RestaurantSettings, User
from .services import cart_snapshot


def site_context(request):
    role = request.user.role if request.user.is_authenticated else None
    return {"restaurant_settings": RestaurantSettings.current(),
            "is_customer": role == User.Role.CUSTOMER,
            "is_worker": role == User.Role.WORKER,
            "is_billing": role == User.Role.BILLING,
            **cart_snapshot(request)}
