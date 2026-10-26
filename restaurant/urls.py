from django.urls import path
from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("signup/", views.signup, name="signup"),
    path("password/change/", views.password_change, name="password_change"),
    path("menu/", views.menu, name="menu"),
    path("cart/", views.cart, name="cart"),
    path("cart/add/<int:pk>/", views.cart_add, name="cart_add"),
    path("cart/update/<int:pk>/", views.cart_update, name="cart_update"),
    path("checkout/", views.checkout, name="checkout"),
    path("orders/", views.orders, name="orders"),
    path("orders/updates/", views.order_updates, name="order_updates"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/status/", views.order_status, name="order_status"),
    path("orders/<int:pk>/assign/", views.order_assign, name="order_assign"),
    path("orders/<int:pk>/collect/", views.order_collect, name="order_collect"),
    path("worker/", views.worker, name="worker"),
    path("billing/", views.billing, name="billing"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/users/", views.users, name="users"),
    path("settings/users/new/", views.user_create, name="user_create"),
    path("bookings/", views.bookings, name="bookings"),
    path("bookings/new/", views.book_table, name="book_table"),
    path("bookings/<int:pk>/status/", views.booking_update, name="booking_update"),
    path("settings/menu/", views.menu_manage, name="menu_manage"),
    path("settings/menu/new/", views.dish_create, name="dish_create"),
    path("settings/menu/<int:pk>/", views.dish_edit, name="dish_edit"),
    path("settings/tables/", views.tables, name="tables"),
]
