from __future__ import annotations
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from typing import Any
from typing import Any, cast
from django.db.models.signals import post_save
from django.dispatch import receiver

from .managers import CustomUserManager
from .validators import validate_hex_color, validate_logo_image


class Tenant(models.Model):
    """
    Modelo para multi-tenancy. Cada tenant representa um salão/organização.
    """

    name = models.CharField(max_length=255, help_text="Nome do salão/organização")
    slug = models.SlugField(unique=True, help_text="Identificador único (URL-friendly)")

    # Branding/White-label
    logo = models.ImageField(
        upload_to="tenant_logos/",
        blank=True,
        null=True,
        validators=[validate_logo_image],
        help_text="Logo do salão (PNG, JPG, SVG - max 2MB)",
    )
    logo_url = models.URLField(
        blank=True, null=True, help_text="URL do logo do salão (para compatibilidade)"
    )
    primary_color = models.CharField(
        max_length=7,
        default="#3B82F6",
        validators=[validate_hex_color],
        help_text="Cor primária (hex) para branding",
    )
    secondary_color = models.CharField(
        max_length=7,
        default="#1F2937",
        validators=[validate_hex_color],
        help_text="Cor secundária (hex) para branding",
    )

    # Configurações
    timezone = models.CharField(
        max_length=50, default="Europe/Lisbon", help_text="Timezone do salão"
    )
    currency = models.CharField(
        max_length=3, default="EUR", help_text="Moeda padrão (ISO 4217)"
    )

    # Planos e Feature Flags
    PLAN_BASIC = "basic"
    PLAN_STANDARD = "standard"
    PLAN_PRO = "pro"
    PLAN_ENTERPRISE = "enterprise"
    PLAN_CHOICES = [
        (PLAN_BASIC, "Basic"),
        (PLAN_STANDARD, "Standard"),
        (PLAN_PRO, "Pro"),
        (PLAN_ENTERPRISE, "Enterprise"),
    ]

    plan_tier = models.CharField(
        max_length=20,
        choices=PLAN_CHOICES,
        default=PLAN_BASIC,
        help_text="Nível do plano contratado",
    )
    addons_enabled = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista de addons habilitados (ex: ['rn_admin', 'rn_client'])",
    )

    # Feature Flags - Módulos
    reports_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita módulo de relatórios"
    )
    pwa_admin_enabled = models.BooleanField(
        default=cast(Any, True), help_text="Habilita PWA Admin"
    )
    pwa_client_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita PWA Cliente"
    )
    rn_admin_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita app nativo Admin (React Native)"
    )
    rn_client_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita app nativo Cliente (React Native)"
    )

    # Feature Flags - Canais de Notificação
    push_web_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita notificações web push"
    )
    push_mobile_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita notificações mobile push"
    )
    sms_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita notificações SMS"
    )
    whatsapp_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita notificações WhatsApp"
    )

    # Metadados
    is_active = models.BooleanField(default=cast(Any, True))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return self.name

    @property
    def get_logo_url(self):
        """Retorna a URL do logo (upload ou URL externa)."""
        if self.logo:
            return self.logo.url
        return self.logo_url

    # Métodos para verificação de feature flags baseados no plano
    def can_use_reports(self):
        """Verifica se pode usar relatórios (Standard+)"""
        return self.reports_enabled or self.plan_tier in [
            self.PLAN_STANDARD,
            self.PLAN_PRO,
            self.PLAN_ENTERPRISE,
        ]

    def can_use_pwa_client(self):
        """Verifica se pode usar PWA Cliente (Standard+)"""
        return self.pwa_client_enabled or self.plan_tier in [
            self.PLAN_STANDARD,
            self.PLAN_PRO,
            self.PLAN_ENTERPRISE,
        ]

    def can_use_white_label(self):
        """Verifica se pode usar white-label (Pro apenas)"""
        return self.plan_tier in (self.PLAN_PRO, self.PLAN_ENTERPRISE)

    def can_use_native_apps(self):
        """Verifica se pode usar apps nativos (Pro + addons)"""
        from typing import Any, cast
        addons = cast(list[str], (self.addons_enabled or []))
        return self.plan_tier in (self.PLAN_PRO, self.PLAN_ENTERPRISE) and (
            "rn_admin" in addons or "rn_client" in addons
        )

    def can_use_advanced_notifications(self):
        """Verifica se pode usar SMS/WhatsApp (Pro + configuração)"""
        return self.plan_tier in (self.PLAN_PRO, self.PLAN_ENTERPRISE) and (
            self.sms_enabled or self.whatsapp_enabled
        )

    def get_enabled_notification_channels(self):
        """Retorna lista de canais de notificação habilitados"""
        channels = ["in_app"]  # Sempre habilitado

        if self.push_web_enabled:
            channels.append("push_web")
        if self.push_mobile_enabled:
            channels.append("push_mobile")
        if self.sms_enabled and self.can_use_advanced_notifications():
            channels.append("sms")
        if self.whatsapp_enabled and self.can_use_advanced_notifications():
            channels.append("whatsapp")

        return channels

    def get_feature_flags_dict(self):
        """Retorna dicionário com todas as feature flags para APIs"""
        return {
            "plan_tier": self.plan_tier,
            "addons_enabled": self.addons_enabled,
            "modules": {
                "reports_enabled": self.can_use_reports(),
                "pwa_admin_enabled": self.pwa_admin_enabled,
                "pwa_client_enabled": self.can_use_pwa_client(),
                "rn_admin_enabled": self.rn_admin_enabled
                and self.can_use_native_apps(),
                "rn_client_enabled": self.rn_client_enabled
                and self.can_use_native_apps(),
            },
            "notifications": {
                "push_web": self.push_web_enabled,
                "push_mobile": self.push_mobile_enabled,
                "sms": self.sms_enabled and self.can_use_advanced_notifications(),
                "whatsapp": self.whatsapp_enabled
                and self.can_use_advanced_notifications(),
                "enabled_channels": self.get_enabled_notification_channels(),
            },
            "branding": {
                "white_label_enabled": self.can_use_white_label(),
                "custom_domain_enabled": self.can_use_white_label(),
            },
        }


class CustomUser(AbstractUser):
    class OpsRoles(models.TextChoices):
        OPS_ADMIN = "ops_admin", "Ops Admin"
        OPS_SUPPORT = "ops_support", "Ops Support"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,  # Temporário para testes
        help_text="Tenant/salão ao qual o usuário pertence",
    )
    salon_name = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    ops_role = models.CharField(
        max_length=20,
        choices=OpsRoles.choices,
        blank=True,
        null=True,
        help_text="Role de staff do console Ops (ops_admin ou ops_support)",
    )
    objects: Any = CustomUserManager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "username"]),
            models.Index(fields=["tenant", "email"]),
            models.Index(fields=["ops_role"]),
        ]

    def __str__(self):
        if self.tenant:
            return f"{self.username} ({self.tenant.name})"
        return self.username

    @property
    def is_ops_user(self) -> bool:
        return bool(self.ops_role)

    def save(self, *args, **kwargs):
        if self.ops_role:
            self.is_staff = True
        super().save(*args, **kwargs)


class UserFeatureFlags(models.Model):
    PLAN_BASIC = "basic"
    PLAN_STANDARD = "standard"
    PLAN_PRO = "pro"
    PLAN_ENTERPRISE = "enterprise"
    PLAN_CHOICES = (
        (PLAN_BASIC, "Basic"),
        (PLAN_STANDARD, "Standard"),
        (PLAN_PRO, "Pro"),
        (PLAN_ENTERPRISE, "Enterprise"),
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
    is_pro = models.BooleanField(default=cast(Any, False))
    pro_status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_INCOMPLETE
    )
    pro_plan = models.CharField(
        max_length=20, choices=PLAN_CHOICES, blank=True, null=True
    )
    pro_since = models.DateTimeField(blank=True, null=True)
    pro_until = models.DateTimeField(blank=True, null=True)
    trial_until = models.DateTimeField(blank=True, null=True)

    # Módulos opcionais (o salão pode ligar/desligar)
    sms_enabled = models.BooleanField(default=cast(Any, False))
    email_enabled = models.BooleanField(default=cast(Any, True))  # notificações por e‑mail
    reports_enabled = models.BooleanField(default=cast(Any, False))
    audit_log_enabled = models.BooleanField(default=cast(Any, False))
    i18n_enabled = models.BooleanField(default=cast(Any, False))

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
