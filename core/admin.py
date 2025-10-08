from django.contrib import admin
from django.db.models import Count
from django.utils import timezone
from django.utils.html import format_html
from django.urls import reverse
from core.models import (
    Appointment,
    AppointmentSeries,
    Professional,
    SalonCustomer,
    ScheduleSlot,
    Service,
)
from core.email_utils import (
    send_appointment_confirmation_email,
    send_appointment_cancellation_email,
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
        "customer_name",
        "service",
        "professional",
        "tenant_name",
        "appointment_datetime",
        "status",
        "series_link",
        "total_price_eur",
    )
    list_filter = ("tenant", "customer", "status", "created_at", "series")
    search_fields = (
        "customer__name",
        "customer__email",
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
            {"fields": ("tenant", "client", "customer", "service", "professional", "slot", "series")},
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

    def customer_name(self, obj):
        if obj.customer:
            return obj.customer.name
        return "—"

    customer_name.short_description = "Cliente"
    customer_name.admin_order_field = "customer__name"

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change and obj.pk:
            previous_status = (
                Appointment.objects.filter(pk=obj.pk)
                .values_list("status", flat=True)
                .first()
            )

        super().save_model(request, obj, form, change)

        obj.refresh_from_db()
        customer = obj.customer
        recipient_email = (
            customer.email if customer and customer.email else (obj.client.email or "")
        )
        if not recipient_email:
            return

        client_display_name = (
            customer.name
            if customer and customer.name
            else (
                obj.client.get_full_name()
                or obj.client.username
                or (obj.client.email or "").split("@")[0]
            )
        )

        try:
            if not change:
                salon_name = obj.tenant.name if obj.tenant else "Salonix"
                send_appointment_confirmation_email(
                    to_email=recipient_email,
                    client_name=client_display_name,
                    service_name=obj.service.name,
                    date_time=obj.slot.start_time,
                    salon_name=salon_name,
                )
            elif previous_status != "cancelled" and obj.status == "cancelled":
                salon_email = obj.professional.user.email if obj.professional else ""
                if salon_email:
                    salon_name = obj.tenant.name if obj.tenant else "Salonix"
                    send_appointment_cancellation_email(
                        client_email=recipient_email,
                        salon_email=salon_email,
                        client_name=client_display_name,
                        service_name=obj.service.name,
                        date_time=obj.slot.start_time,
                        salon_name=salon_name,
                    )
        except Exception as exc:  # pragma: no cover - apenas log
            import logging

            logging.getLogger(__name__).warning(
                "Falha ao enviar e-mail via admin",
                extra={
                    "appointment_id": obj.id,
                    "tenant_id": getattr(obj.tenant, "id", None),
                    "error": str(exc),
                },
            )

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
        "customer",
        "slot",
        "status",
        "appointment_datetime",
    )
    readonly_fields = (
        "client",
        "customer",
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
@admin.register(SalonCustomer)
class SalonCustomerAdmin(admin.ModelAdmin):
    """Admin do Django para clientes do salão."""

    list_display = ("name", "tenant_name", "email", "phone_number", "is_active", "marketing_opt_in", "created_at")
    list_filter = ("tenant", "is_active", "marketing_opt_in", "created_at")
    search_fields = ("name", "email", "phone_number", "tenant__name")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("name",)

    fieldsets = (
        ("Informações Básicas", {"fields": ("tenant", "name", "email", "phone_number")}),
        ("Preferências", {"fields": ("marketing_opt_in", "is_active")}),
        ("Notas", {"fields": ("notes",)}),
        ("Metadados", {"fields": ("created_at", "updated_at")}),
    )

    def tenant_name(self, obj):
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"
