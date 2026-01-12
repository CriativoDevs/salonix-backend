from django import forms
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
    ProfessionalService,
    CustomerCommunicationConsent,
    Feedback,
)
from core.email_utils import (
    send_appointment_confirmation_email,
    send_appointment_cancellation_email,
)
from users.models import TenantStaffMember


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


class ProfessionalAdminForm(forms.ModelForm):
    class Meta:
        model = Professional
        fields = ("staff_member", "name", "bio", "is_active")


class ProfessionalServiceInline(admin.TabularInline):
    model = ProfessionalService
    fields = ("service", "is_active", "created_at")
    readonly_fields = ("created_at",)
    extra = 1
    can_delete = True

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "service":
            qs = Service.objects.select_related("tenant")
            tenant = getattr(request.user, "tenant", None)
            if tenant and not request.user.is_superuser:
                qs = qs.filter(tenant=tenant)
            kwargs["queryset"] = qs
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Professional)
class ProfessionalAdmin(admin.ModelAdmin):
    """Admin para profissionais com filtro por tenant."""

    form = ProfessionalAdminForm
    list_display = (
        "name",
        "tenant_name",
        "user",
        "user_email",
        "staff_member",
        "is_active",
    )
    list_filter = ("tenant", "is_active")
    search_fields = ("name", "user__username", "tenant__name")
    readonly_fields = ("tenant", "user", "user_email")
    inlines = (ProfessionalServiceInline,)

    fieldsets = (
        (
            "Informações Básicas",
            {
                "fields": (
                    "staff_member",
                    "name",
                    "bio",
                    "is_active",
                    "tenant",
                    "user",
                    "user_email",
                )
            },
        ),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "staff_member":
            qs = TenantStaffMember.objects.filter(
                status=TenantStaffMember.Status.ACTIVE
            ).select_related("user", "tenant")
            tenant = getattr(request.user, "tenant", None)
            if tenant and not request.user.is_superuser:
                qs = qs.filter(tenant=tenant)
            kwargs["queryset"] = qs
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if obj.staff_member:
            obj.user = obj.staff_member.user
            obj.tenant = obj.staff_member.tenant
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        # Garante que tenant e professional são definidos corretamente nos inlines
        for inst in instances:
            if isinstance(inst, ProfessionalService):
                inst.tenant = form.instance.tenant
                inst.professional = form.instance
            inst.save()
        formset.save_m2m()

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"

    def user_email(self, obj):
        return obj.user.email or "-"

    user_email.short_description = "E-mail"
    user_email.admin_order_field = "user__email"


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
    readonly_fields = (
        "created_at",
        "appointment_datetime",
        "total_price_eur",
        "series",
    )
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Informações do Agendamento",
            {
                "fields": (
                    "tenant",
                    "client",
                    "customer",
                    "service",
                    "professional",
                    "slot",
                    "series",
                )
            },
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
            url = reverse(
                f"{namespace}:core_appointmentseries_change", args=[obj.series.pk]
            )
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


class CommunicationConsentInline(admin.TabularInline):
    model = CustomerCommunicationConsent
    fields = (
        "channel",
        "purpose",
        "status",
        "consented_at",
        "withdrawn_at",
        "source",
        "ip_address",
        "user_agent",
        "version",
        "locale",
        "created_at",
        "updated_at",
    )
    readonly_fields = ("created_at", "updated_at")
    extra = 1


@admin.register(SalonCustomer)
class SalonCustomerAdmin(admin.ModelAdmin):
    """Admin do Django para clientes do salão."""

    list_display = (
        "name",
        "tenant_name",
        "email",
        "phone_number",
        "is_active",
        "marketing_opt_in",
        "created_at",
    )
    list_filter = ("tenant", "is_active", "marketing_opt_in", "created_at")
    search_fields = ("name", "email", "phone_number", "tenant__name")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("name",)

    fieldsets = (
        (
            "Informações Básicas",
            {"fields": ("tenant", "name", "email", "phone_number")},
        ),
        ("Preferências", {"fields": ("marketing_opt_in", "is_active")}),
        ("Notas", {"fields": ("notes",)}),
        ("Metadados", {"fields": ("created_at", "updated_at")}),
    )
    inlines = (CommunicationConsentInline,)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for inst in instances:
            if isinstance(inst, CustomerCommunicationConsent):
                inst.tenant = form.instance.tenant
                inst.customer = form.instance
                if inst.status == "consented":
                    if not inst.consented_at:
                        inst.consented_at = timezone.now()
                    inst.withdrawn_at = None
                elif inst.status == "withdrawn":
                    if not inst.withdrawn_at:
                        inst.withdrawn_at = timezone.now()
                elif inst.status == "pending":
                    inst.consented_at = None
                    # mantém withdrawn_at conforme histórico, salvo alteração explícita
            inst.save()
        formset.save_m2m()

    def tenant_name(self, obj):
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"


@admin.register(CustomerCommunicationConsent)
class CustomerCommunicationConsentAdmin(admin.ModelAdmin):
    list_display = (
        "customer",
        "tenant_name",
        "channel",
        "purpose",
        "status",
        "consented_at",
        "withdrawn_at",
        "source",
        "created_at",
    )
    list_filter = ("tenant", "channel", "purpose", "status", "source", "created_at")
    search_fields = ("customer__name", "customer__email", "tenant__name")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    actions = ("withdraw_selected",)

    def tenant_name(self, obj):
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"

    def withdraw_selected(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(
            status="withdrawn", withdrawn_at=now, consented_at=None
        )
        self.message_user(
            request, f"Consentimento retirado para {updated} registro(s)."
        )

    withdraw_selected.short_description = "Retirar consentimento (selecionados)"

    def get_inline_instances(self, request, obj=None):
        return []


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant_name",
        "category_display",
        "rating",
        "sender_info",
        "created_at",
    )
    list_filter = ("tenant", "category", "rating", "created_at", "is_anonymous")
    search_fields = (
        "message",
        "tenant__name",
        "custom_category",
        "user__email",
        "customer__name",
    )
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"

    def tenant_name(self, obj):
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"

    def category_display(self, obj):
        if obj.category == "other" and obj.custom_category:
            return f"Outro: {obj.custom_category}"
        return obj.get_category_display()

    category_display.short_description = "Categoria"
    category_display.admin_order_field = "category"

    def sender_info(self, obj):
        if obj.is_anonymous:
            return "Anônimo"
        if obj.user:
            return f"User: {obj.user.email}"
        if obj.customer:
            return f"Customer: {obj.customer.name}"
        return "-"

    sender_info.short_description = "Remetente"


SalonCustomerAdmin.inlines = (CommunicationConsentInline,)
