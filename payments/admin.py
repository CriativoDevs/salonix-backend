from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import PaymentCustomer, Subscription


@admin.register(PaymentCustomer)
class PaymentCustomerAdmin(admin.ModelAdmin):
    """Admin para clientes de pagamento com filtro por tenant."""

    list_display = ("user", "tenant_name", "stripe_customer_id", "subscription_status")
    list_filter = ("user__tenant",)
    search_fields = (
        "user__username",
        "user__email",
        "stripe_customer_id",
        "user__tenant__name",
    )
    readonly_fields = ("subscription_status",)

    fieldsets = (
        ("Cliente", {"fields": ("user", "tenant_name")}),
        ("Stripe", {"fields": ("stripe_customer_id", "subscription_status")}),
    )

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.user and obj.user.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.user.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.user.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "user__tenant__name"

    def subscription_status(self, obj):
        """Exibe status da assinatura ativa."""
        subscription = obj.subscriptions.filter(status="active").first()
        if subscription:
            return format_html(
                '<span style="color: green;">✓ Ativa</span> ({})',
                subscription.current_period_end.strftime("%d/%m/%Y"),
            )
        return format_html('<span style="color: red;">✗ Inativa</span>')

    subscription_status.short_description = "Status Assinatura"


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """Admin para assinaturas com filtro por tenant."""

    list_display = (
        "user",
        "tenant_name",
        "stripe_subscription_id",
        "status",
        "price_id",
        "current_period_end",
        "cancel_at_period_end",
    )
    list_filter = ("status", "cancel_at_period_end", "user__tenant")
    search_fields = (
        "user__username",
        "user__email",
        "stripe_subscription_id",
        "price_id",
        "user__tenant__name",
    )
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "current_period_end"

    fieldsets = (
        ("Cliente", {"fields": ("user", "tenant_name")}),
        ("Assinatura", {"fields": ("stripe_subscription_id", "status", "price_id")}),
        (
            "Período",
            {
                "fields": (
                    "current_period_end",
                    "cancel_at_period_end",
                )
            },
        ),
        (
            "Metadados",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.user and obj.user.tenant:
            tenant = obj.user.tenant
            url = reverse("admin:users_tenant_change", args=[tenant.pk])
            return format_html('<a href="{}">{}</a>', url, tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "user__tenant__name"
