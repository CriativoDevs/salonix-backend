from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from core.models import Service, Professional, ScheduleSlot, Appointment


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    """Admin para serviços com filtro por tenant."""

    list_display = ("name", "tenant_name", "user", "price_eur", "duration_minutes")
    list_filter = ("tenant",)
    search_fields = ("name", "user__username", "tenant__name")

    fieldsets = (
        ("Informações Básicas", {"fields": ("tenant", "user", "name")}),
        ("Preços e Duração", {"fields": ("price_eur", "duration_minutes")}),
    )

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"


@admin.register(Professional)
class ProfessionalAdmin(admin.ModelAdmin):
    """Admin para profissionais com filtro por tenant."""

    list_display = ("name", "tenant_name", "user", "is_active")
    list_filter = ("tenant", "is_active")
    search_fields = ("name", "user__username", "tenant__name")

    fieldsets = (
        (
            "Informações Básicas",
            {"fields": ("tenant", "user", "name", "bio", "is_active")},
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


@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    """Admin para slots de horário com filtro por tenant."""

    list_display = (
        "professional",
        "start_time",
        "end_time",
        "tenant_name",
        "is_available",
        "status",
    )
    list_filter = ("tenant", "is_available", "status", "start_time")
    search_fields = ("professional__name", "tenant__name")
    date_hierarchy = "start_time"

    fieldsets = (
        (
            "Informações Básicas",
            {"fields": ("tenant", "professional", "start_time", "end_time")},
        ),
        ("Status", {"fields": ("is_available", "status")}),
    )

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    """Admin para agendamentos com filtro por tenant."""

    list_display = (
        "client",
        "service",
        "professional",
        "tenant_name",
        "appointment_datetime",
        "status",
        "total_price_eur",
    )
    list_filter = ("tenant", "status", "created_at")
    search_fields = (
        "client__username",
        "service__name",
        "professional__name",
        "tenant__name",
    )
    readonly_fields = ("created_at", "appointment_datetime", "total_price_eur")
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Informações do Agendamento",
            {"fields": ("tenant", "client", "service", "professional", "slot")},
        ),
        ("Status e Notas", {"fields": ("status", "notes", "cancelled_by")}),
        (
            "Metadados",
            {
                "fields": ("created_at", "appointment_datetime", "total_price_eur"),
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

    def appointment_datetime(self, obj):
        """Exibe data e hora do agendamento."""
        if obj.slot:
            return f"{obj.slot.start_time.strftime('%d/%m/%Y %H:%M')}"
        return "-"

    appointment_datetime.short_description = "Data/Hora"
    appointment_datetime.admin_order_field = "slot__start_time"

    def total_price_eur(self, obj):
        """Exibe preço total formatado."""
        if obj.service:
            return f"€{obj.service.price_eur}"
        return "-"

    total_price_eur.short_description = "Preço"
