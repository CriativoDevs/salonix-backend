from django.contrib import admin
from .models import PaymentCustomer, Subscription


@admin.register(PaymentCustomer)
class PaymentCustomerAdmin(admin.ModelAdmin):
    list_display = ("user", "stripe_customer_id")
    search_fields = ("user__username", "user__email", "stripe_customer_id")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "stripe_subscription_id",
        "status",
        "price_id",
        "current_period_end",
        "cancel_at_period_end",
    )
    list_filter = ("status", "cancel_at_period_end")
    search_fields = (
        "user__username",
        "user__email",
        "stripe_subscription_id",
        "price_id",
    )
