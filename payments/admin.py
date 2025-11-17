from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import PaymentCustomer, Subscription, CreditPayment, StripeWebhookEvent


@admin.register(PaymentCustomer)
class PaymentCustomerAdmin(admin.ModelAdmin):
    """Admin para clientes de pagamento com filtro por tenant."""

    list_display = ("user", "tenant_name", "stripe_customer_id")
    list_filter = ("user__tenant",)
    search_fields = (
        "user__username",
        "user__email",
        "stripe_customer_id",
        "user__tenant__name",
    )
    readonly_fields = ()

    fieldsets = (
        ("Cliente", {"fields": ("user", "tenant_name")}),
        ("Stripe", {"fields": ("stripe_customer_id",)}),
    )

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.user and obj.user.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.user.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.user.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "user__tenant__name"


@admin.register(CreditPayment)
class CreditPaymentAdmin(admin.ModelAdmin):
    """Admin para pagamentos de créditos."""

    list_display = (
        "user",
        "tenant_name",
        "amount",
        "credits_purchased",
        "status",
        "credits_applied",
        "created_at",
    )
    list_filter = ("status", "credits_applied", "currency", "user__tenant")
    search_fields = (
        "user__username",
        "user__email",
        "stripe_payment_intent_id",
        "user__tenant__name",
    )
    readonly_fields = ("created_at", "updated_at", "completed_at")
    date_hierarchy = "created_at"

    fieldsets = (
        ("Cliente", {"fields": ("user", "tenant", "tenant_name")}),
        (
            "Stripe",
            {
                "fields": (
                    "stripe_payment_intent_id",
                    "stripe_customer_id",
                    "stripe_price_id",
                )
            },
        ),
        (
            "Pagamento",
            {"fields": ("amount", "currency", "status", "completed_at")},
        ),
        (
            "Créditos",
            {"fields": ("credits_purchased", "credits_applied")},
        ),
        (
            "Metadados",
            {
                "fields": ("metadata", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "tenant")


@admin.register(StripeWebhookEvent)
class StripeWebhookEventAdmin(admin.ModelAdmin):
    """Admin para eventos de webhook do Stripe."""

    list_display = (
        "stripe_event_id",
        "event_type",
        "processed",
        "processing_error_short",
        "created_at",
    )
    list_filter = ("event_type", "processed")
    search_fields = ("stripe_event_id", "event_type")
    readonly_fields = ("created_at", "processed_at")
    date_hierarchy = "created_at"

    fieldsets = (
        ("Evento", {"fields": ("stripe_event_id", "event_type")}),
        (
            "Processamento",
            {"fields": ("processed", "processed_at", "processing_error")},
        ),
        (
            "Dados",
            {"fields": ("event_data",), "classes": ("collapse",)},
        ),
        (
            "Metadados",
            {"fields": ("created_at",), "classes": ("collapse",)},
        ),
    )

    def processing_error_short(self, obj):
        """Exibe versão curta do erro de processamento."""
        if obj.processing_error:
            error = obj.processing_error[:100]
            if len(obj.processing_error) > 100:
                error += "..."
            return format_html('<span style="color: red;">{}</span>', error)
        return "-"

    processing_error_short.short_description = "Erro"


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
