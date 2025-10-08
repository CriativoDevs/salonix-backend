from django.conf import settings
from django.db import models
from typing import Any, cast

from users.models import CustomUser, Tenant
from django.conf import settings as dj_settings


class SalonCustomer(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="customers",
    )
    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=32, blank=True, null=True)
    notes = models.TextField(blank=True)
    marketing_opt_in = models.BooleanField(default=cast(Any, False))
    is_active = models.BooleanField(default=cast(Any, True))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant"], name="core_customer_tenant_idx"),
            models.Index(fields=["tenant", "name"], name="core_customer_name_idx"),
            models.Index(fields=["tenant", "email"], name="core_customer_email_idx"),
            models.Index(fields=["tenant", "phone_number"], name="core_customer_phone_idx"),
        ]
        ordering = ("name", "id")

    def __str__(self):
        return f"{self.name} ({self.tenant.slug if hasattr(self.tenant, 'slug') else self.tenant_id})"


class Service(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="services",
        null=True,  # Temporário para testes
    )
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="services"
    )
    name = models.CharField(max_length=100)
    duration_minutes = models.PositiveIntegerField(
        help_text="Duração do serviço em minutos"
    )
    price_eur = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        indexes = [
            models.Index(fields=["tenant"]),
            models.Index(fields=["tenant", "user"]),
        ]

    def __str__(self):
        tenant_name = self.tenant.name if self.tenant else "No Tenant"
        return f"{self.name} ({self.price_eur}€) - {tenant_name}"


class AppointmentSeries(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="appointment_series",
        null=True,  # Temporário para testes
    )
    client = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="series"
    )
    service = models.ForeignKey(
        'Service', on_delete=models.CASCADE, related_name="series"
    )
    professional = models.ForeignKey(
        'Professional', on_delete=models.CASCADE, related_name="series"
    )
    notes = models.TextField(blank=True, null=True)
    recurrence_rule = models.CharField(max_length=100, blank=True, null=True)
    count = models.PositiveIntegerField(blank=True, null=True)
    until = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant"]),
            models.Index(fields=["tenant", "client"]),
        ]

    def __str__(self):
        return f"Series<{self.id}> {self.service.name} / {self.professional.name}"

class Professional(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="professionals",
        null=True,  # Temporário para testes
    )
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="professionals"
    )
    name = models.CharField(max_length=100)
    bio = models.TextField(blank=True)
    is_active = models.BooleanField(default=cast(Any, True))

    class Meta:
        indexes = [
            models.Index(fields=["tenant"]),
            models.Index(fields=["tenant", "user"]),
            models.Index(fields=["tenant", "is_active"]),
        ]

    def __str__(self):
        tenant_name = self.tenant.name if self.tenant else "No Tenant"
        return f"{self.name} - {tenant_name}"


class ScheduleSlot(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="schedule_slots",
        null=True,  # Temporário para testes
    )
    professional = models.ForeignKey(
        Professional, on_delete=models.CASCADE, related_name="slots"
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_available = models.BooleanField(default=cast(Any, True))
    STATUS_CHOICES = [
        ("available", "Available"),
        ("booked", "Booked"),
        ("blocked", "Blocked"),
    ]
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="available"
    )

    class Meta:
        indexes = [
            models.Index(fields=["tenant"]),
            models.Index(fields=["tenant", "professional"]),
            models.Index(fields=["tenant", "start_time"]),
            models.Index(fields=["tenant", "is_available"]),
        ]

    def __str__(self):
        return f"{self.professional.name} | {self.start_time} - {self.end_time}"

    def mark_booked(self):
        self.is_available = False
        self.status = "booked"
        self.save(update_fields=["is_available", "status"])

    def mark_available(self):
        self.is_available = True
        self.status = "available"
        self.save(update_fields=["is_available", "status"])


class Appointment(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="appointments",
        null=True,  # Temporário para testes
    )
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="appointments"
    )
    customer = models.ForeignKey(
        "SalonCustomer",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="appointments",
    )
    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="appointments"
    )
    professional = models.ForeignKey(
        Professional, on_delete=models.CASCADE, related_name="appointments"
    )
    slot = models.ForeignKey(
        ScheduleSlot, on_delete=models.CASCADE, related_name="appointments"
    )
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("scheduled", "Scheduled"),
            ("cancelled", "Cancelled"),
            ("completed", "Completed"),
            ("paid", "Paid"),
        ],
        default="scheduled",
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_appointments",
    )
    series = models.ForeignKey(
        AppointmentSeries,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )

    class Meta:
        indexes = [
            models.Index(fields=["tenant"]),
            models.Index(fields=["tenant", "client"]),
            models.Index(fields=["tenant", "customer"], name="core_appoin_tenant_c_idx"),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["tenant", "service"]),
            models.Index(fields=["tenant", "professional"]),
        ]

    def __str__(self):
        tenant_name = self.tenant.name if self.tenant else "No Tenant"
        customer_name = self.customer.name if self.customer else "Sem cliente"
        return f"{customer_name} - {self.service.name} com {self.professional.name} ({tenant_name})"
