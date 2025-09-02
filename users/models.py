from __future__ import annotations
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from .managers import CustomUserManager


class Tenant(models.Model):
    """
    Modelo para multi-tenancy. Cada tenant representa um salão/organização.
    """

    name = models.CharField(max_length=255, help_text="Nome do salão/organização")
    slug = models.SlugField(unique=True, help_text="Identificador único (URL-friendly)")

    # Branding/White-label
    logo_url = models.URLField(blank=True, null=True, help_text="URL do logo do salão")
    primary_color = models.CharField(
        max_length=7, default="#3B82F6", help_text="Cor primária (hex) para branding"
    )
    secondary_color = models.CharField(
        max_length=7, default="#1F2937", help_text="Cor secundária (hex) para branding"
    )

    # Configurações
    timezone = models.CharField(
        max_length=50, default="Europe/Lisbon", help_text="Timezone do salão"
    )
    currency = models.CharField(
        max_length=3, default="EUR", help_text="Moeda padrão (ISO 4217)"
    )

    # Metadados
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,  # Temporário para testes
        help_text="Tenant/salão ao qual o usuário pertence",
    )
    salon_name = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    objects = CustomUserManager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "username"]),
            models.Index(fields=["tenant", "email"]),
        ]

    def __str__(self):
        if self.tenant:
            return f"{self.username} ({self.tenant.name})"
        return self.username


class UserFeatureFlags(models.Model):
    PLAN_MONTHLY = "monthly"
    PLAN_YEARLY = "yearly"
    PLAN_CHOICES = (
        (PLAN_MONTHLY, "Monthly"),
        (PLAN_YEARLY, "Yearly"),
    )

    STATUS_ACTIVE = "active"
    STATUS_TRIALING = "trialing"
    STATUS_PAST_DUE = "past_due"
    STATUS_CANCELED = "canceled"
    STATUS_INCOMPLETE = "incomplete"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_TRIALING, "Trialing"),
        (STATUS_PAST_DUE, "Past due"),
        (STATUS_CANCELED, "Canceled"),
        (STATUS_INCOMPLETE, "Incomplete"),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="featureflags",
    )

    # Controle Pro (preenchido via webhooks/adm)
    is_pro = models.BooleanField(default=False)
    pro_status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_INCOMPLETE
    )
    pro_plan = models.CharField(
        max_length=10, choices=PLAN_CHOICES, blank=True, null=True
    )
    pro_since = models.DateTimeField(blank=True, null=True)
    pro_until = models.DateTimeField(blank=True, null=True)
    trial_until = models.DateTimeField(blank=True, null=True)

    # Módulos opcionais (o salão pode ligar/desligar)
    sms_enabled = models.BooleanField(default=False)
    email_enabled = models.BooleanField(default=True)  # notificações por e‑mail
    reports_enabled = models.BooleanField(default=False)
    audit_log_enabled = models.BooleanField(default=False)
    i18n_enabled = models.BooleanField(default=False)

    # Auditoria mínima
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"FeatureFlags<{self.user_id}> (pro={self.is_pro}, status={self.pro_status})"


# Cria/garante flags ao criar usuário
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_feature_flags(sender, instance, created, **kwargs):
    if created:
        UserFeatureFlags.objects.get_or_create(user=instance)
