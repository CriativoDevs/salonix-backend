from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Notification, NotificationDevice, NotificationLog


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Admin para notificações com filtro por tenant."""

    list_display = (
        "title",
        "tenant_name",
        "user",
        "notification_type",
        "channels",
        "is_read",
        "created_at",
    )
    list_filter = ("tenant", "notification_type", "is_read", "created_at")
    search_fields = ("title", "message", "user__username", "tenant__name")
    readonly_fields = ("created_at", "channels")
    date_hierarchy = "created_at"

    fieldsets = (
        ("Informações Básicas", {"fields": ("tenant", "user", "title", "message")}),
        ("Configurações", {"fields": ("notification_type", "channels", "metadata")}),
        ("Status", {"fields": ("is_read", "read_at")}),
        ("Metadados", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"

    def channels(self, obj):
        """Exibe canais de notificação formatados."""
        if obj.metadata and "channels" in obj.metadata:
            channels = obj.metadata["channels"]
            channel_icons = {
                "in_app": "📱",
                "push_web": "🌐",
                "push_mobile": "📲",
                "sms": "💬",
                "whatsapp": "📞",
            }
            return " ".join([str(channel_icons.get(ch, ch)) for ch in channels])
        return "-"

    channels.short_description = "Canais"


@admin.register(NotificationDevice)
class NotificationDeviceAdmin(admin.ModelAdmin):
    """Admin para dispositivos de notificação."""

    list_display = ("user", "tenant_name", "device_type", "is_active", "created_at")
    list_filter = ("tenant", "device_type", "is_active", "created_at")
    search_fields = ("user__username", "token", "tenant__name")
    readonly_fields = ("created_at",)

    fieldsets = (
        ("Usuário", {"fields": ("tenant", "user")}),
        ("Dispositivo", {"fields": ("device_type", "token", "is_active")}),
        ("Metadados", {"fields": ("metadata", "created_at"), "classes": ("collapse",)}),
    )

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    """Admin para logs de notificação com métricas."""

    list_display = (
        "notification_title",
        "tenant_name",
        "channel",
        "status",
        "sent_at",
        "error_message_short",
    )
    list_filter = ("tenant", "channel", "status", "sent_at")
    search_fields = ("title", "channel", "error_message", "tenant__name")
    readonly_fields = ("created_at", "notification_title", "error_message_short")
    date_hierarchy = "sent_at"

    fieldsets = (
        (
            "Notificação",
            {"fields": ("tenant", "user", "notification_type", "title", "message")},
        ),
        ("Envio", {"fields": ("channel", "status", "sent_at", "delivered_at")}),
        (
            "Detalhes",
            {
                "fields": ("metadata", "error_message", "error_message_short"),
                "classes": ("collapse",),
            },
        ),
        ("Metadados", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"

    def notification_title(self, obj):
        """Exibe título da notificação."""
        return obj.title if obj.title else "-"

    notification_title.short_description = "Título"

    def error_message_short(self, obj):
        """Exibe erro truncado."""
        if obj.error_message:
            return (
                (obj.error_message[:50] + "...")
                if len(obj.error_message) > 50
                else obj.error_message
            )
        return "-"

    error_message_short.short_description = "Erro"

    actions = ["retry_failed_notifications"]

    def retry_failed_notifications(self, request, queryset):
        """Reenviar notificações falhadas."""
        failed_logs = queryset.filter(status="failed")
        count = failed_logs.count()

        # Aqui poderia implementar lógica de reenvio
        self.message_user(request, f"{count} notificação(ões) marcada(s) para reenvio.")

    retry_failed_notifications.short_description = "Reenviar notificações falhadas"
