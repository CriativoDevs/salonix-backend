from django.conf import settings
from django.db import models

from users.models import CustomUser


class Service(models.Model):
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="services"
    )
    name = models.CharField(max_length=100)
    duration_minutes = models.PositiveIntegerField(
        help_text="Duração do serviço em minutos"
    )
    price_eur = models.DecimalField(max_digits=6, decimal_places=2)

    def __str__(self):
        return f"{self.name} ({self.price_eur}€)"


class Professional(models.Model):
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="professionals"
    )
    name = models.CharField(max_length=100)
    bio = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class ScheduleSlot(models.Model):
    professional = models.ForeignKey(
        Professional, on_delete=models.CASCADE, related_name="slots"
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_available = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.professional.name} | {self.start_time} - {self.end_time}"


class Appointment(models.Model):
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="appointments"
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
        choices=[("scheduled", "Scheduled"), ("cancelled", "Cancelled")],
        default="scheduled",
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_appointments",
    )

    def __str__(self):
        return (
            f"{self.client.username} - {self.service.name} com {self.professional.name}"
        )
