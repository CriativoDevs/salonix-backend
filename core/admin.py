from django.contrib import admin
from django.db.models import Count
from django.utils import timezone
from django.utils.html import format_html
from django.urls import reverse
from core.models import (
    Appointment,
    AppointmentSeries,
    Professional,
    ScheduleSlot,
    Service,
)


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
        "series_link",
        "total_price_eur",
    )
    list_filter = ("tenant", "status", "created_at", "series")
    search_fields = (
        "client__username",
        "service__name",
        "professional__name",
        "tenant__name",
        "series__id",
    )
    readonly_fields = ("created_at", "appointment_datetime", "total_price_eur", "series")
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Informações do Agendamento",
            {"fields": ("tenant", "client", "service", "professional", "slot", "series")},
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

    def series_link(self, obj):
        """Link para a série relacionada."""
        if obj.series:
            namespace = getattr(self.admin_site, "name", "admin")
            url = reverse(f"{namespace}:core_appointmentseries_change", args=[obj.series.pk])
            return format_html('<a href="{}">Série #{}</a>', url, obj.series.pk)
        return "-"

    series_link.short_description = "Série"
    series_link.admin_order_field = "series__id"


class AppointmentInline(admin.TabularInline):
    model = Appointment
    fields = (
        "client",
        "slot",
        "status",
        "appointment_datetime",
    )
    readonly_fields = (
        "client",
        "slot",
        "status",
        "appointment_datetime",
    )
    extra = 0
    ordering = ("slot__start_time",)

    def appointment_datetime(self, obj):
        if obj.slot:
            return obj.slot.start_time
        return "-"

    appointment_datetime.short_description = "Data/Hora"


@admin.register(AppointmentSeries)
class AppointmentSeriesAdmin(admin.ModelAdmin):
    """Admin para séries de agendamentos com visão multi-tenant."""

    list_display = (
        "id",
        "tenant_name",
        "client",
        "service",
        "professional",
        "total_occurrences",
        "upcoming_occurrences",
        "created_at",
    )
    list_filter = ("tenant", "service", "professional", "created_at")
    search_fields = (
        "id",
        "tenant__name",
        "client__username",
        "service__name",
        "professional__name",
    )
    ordering = ("-created_at",)
    list_select_related = ("tenant", "client", "service", "professional")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at_display")
    inlines = (AppointmentInline,)

    fieldsets = (
        (
            "Identificação",
            {
                "fields": (
                    "tenant",
                    "client",
                    "service",
                    "professional",
                    "notes",
                    "created_at",
                    "updated_at_display",
                )
            },
        ),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(total_appointments=Count("appointments"))

    def tenant_name(self, obj):
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"

    def total_occurrences(self, obj):
        return getattr(obj, "total_appointments", obj.appointments.count())

    total_occurrences.short_description = "Ocorrências"
    total_occurrences.admin_order_field = "total_appointments"

    def upcoming_occurrences(self, obj):
        return obj.appointments.filter(slot__start_time__gte=timezone.now()).count()

    upcoming_occurrences.short_description = "Próximas"

    def updated_at_display(self, obj):
        latest = obj.appointments.order_by("-slot__start_time").first()
        if latest and latest.slot:
            return latest.slot.start_time
        return "-"

    updated_at_display.short_description = "Última ocorrência"
