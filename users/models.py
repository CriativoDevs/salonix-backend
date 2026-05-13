from __future__ import annotations
from django.conf import settings
from django.apps import apps
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from typing import Any, cast
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import time

from .managers import CustomUserManager
from .validators import validate_logo_image, validate_profile_image


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
    favicon_url = models.URLField(
        blank=True,
        null=True,
        help_text="URL do favicon do salão",
    )
    app_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Nome exibido do salão/aplicativo",
    )
    auto_invite_enabled = models.BooleanField(
        default=cast(Any, False),
        help_text="Envia automaticamente convite do PWA Cliente para novos clientes",
    )

    # Configurações
    timezone = models.CharField(
        max_length=50, default="Europe/Lisbon", help_text="Timezone do salão"
    )
    currency = models.CharField(
        max_length=3, default="EUR", help_text="Moeda padrão (ISO 4217)"
    )
    preferred_language = models.CharField(
        max_length=10,
        default="pt-PT",
        help_text="Idioma preferido do tenant (ex.: pt-PT, en)",
    )

    # Endereço do estabelecimento
    address_street = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Rua/Logradouro do estabelecimento",
    )
    address_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Número",
    )
    address_complement = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Complemento (sala, bloco, etc.)",
    )
    address_neighborhood = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Bairro/Distrito",
    )
    address_city = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Cidade",
    )
    address_state = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Estado/Província/UF",
    )
    address_zip = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="CEP/Código postal",
    )
    address_country = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="País",
    )

    # Contatos do estabelecimento
    contact_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Email de contato público do salão",
    )
    contact_phone = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        help_text="Telefone de contato público do salão (E.164 ou local)",
    )

    # Planos e Feature Flags
    PLAN_BASIC = "basic"
    PLAN_PRO = "pro"
    PLAN_FOUNDER = "founder"
    PLAN_CHOICES = [
        (PLAN_BASIC, "Basic"),
        (PLAN_PRO, "Pro"),
        (PLAN_FOUNDER, "Founder"),  # DEPRECATED: Use PLAN_BASIC + is_founder=True
    ]

    BILLING_MODE_STRIPE = "stripe"
    BILLING_MODE_PROMOTIONAL = "promotional"
    BILLING_MODE_CHOICES = [
        (BILLING_MODE_STRIPE, "Stripe"),
        (BILLING_MODE_PROMOTIONAL, "Promotional"),
    ]

    plan_tier = models.CharField(
        max_length=20,
        choices=PLAN_CHOICES,
        default=PLAN_BASIC,
        help_text="Nível do plano contratado",
    )
    billing_mode = models.CharField(
        max_length=20,
        choices=BILLING_MODE_CHOICES,
        default=BILLING_MODE_STRIPE,
        db_index=True,
        help_text="Modo de billing do tenant (Stripe ou promocional interno)",
    )
    promotional_expires_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Data/hora em que o billing promocional expira, se aplicável",
    )
    promotional_converts_to_plan = models.CharField(
        max_length=20,
        choices=[(PLAN_BASIC, "Basic"), (PLAN_PRO, "Pro")],
        default=PLAN_BASIC,
        help_text="Plano pago alvo quando a promoção expirar",
    )
    addons_enabled = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista de addons habilitados (ex: ['rn_admin', 'rn_client'])",
    )

    # Feature Flags - Módulos
    reports_enabled = models.BooleanField(
        default=cast(Any, True), help_text="Habilita módulo de relatórios"
    )
    pwa_admin_enabled = models.BooleanField(
        default=cast(Any, True), help_text="Habilita PWA Admin"
    )
    pwa_client_enabled = models.BooleanField(
        default=cast(Any, True), help_text="Habilita PWA Cliente"
    )
    rn_admin_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita app nativo Admin (React Native)"
    )
    rn_client_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita app nativo Cliente (React Native)"
    )

    # Feature Flags - Canais de Notificação
    push_web_enabled = models.BooleanField(
        default=cast(Any, True), help_text="Habilita notificações web push"
    )
    push_mobile_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita notificações mobile push"
    )
    sms_enabled = models.BooleanField(
        default=cast(Any, True), help_text="Habilita notificações SMS"
    )
    whatsapp_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita notificações WhatsApp"
    )

    # Feedback notifications config
    feedback_webhook_url = models.URLField(
        blank=True,
        null=True,
        help_text="URL de webhook para eventos de feedback",
    )
    feedback_digest_enabled = models.BooleanField(
        default=cast(Any, False),
        help_text="Habilita digest de feedback por e-mail",
    )
    feedback_digest_frequency = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Frequência do digest (daily/weekly)",
        default="daily",
    )
    feedback_digest_time = models.TimeField(
        blank=True,
        null=True,
        help_text="Horário local do tenant para envio do digest",
        default=time(9, 0),
    )
    feedback_digest_last_sent = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Último envio de digest de feedback",
    )

    # Feature Flags - Sistema de Créditos de Comunicação
    comm_credit_eur = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Crédito atual de comunicações em euros",
    )
    comm_extra_allowed = models.BooleanField(
        default=cast(Any, True),
        help_text="Permite compra de créditos avulsos de comunicação",
    )
    comm_auto_renew = models.BooleanField(
        default=cast(Any, False),
        help_text="Renovação automática de crédito mensal (Pro+)",
    )

    # Plano Founder (Promoção Limitada)
    is_founder = models.BooleanField(
        default=cast(Any, False),
        help_text="Indica se o tenant possui o plano Founder (limitado a 500)",
    )

    # Feature Flags - White-label e Domínio
    custom_domain_enabled = models.BooleanField(
        default=cast(Any, False), help_text="Habilita domínio personalizado"
    )
    custom_domain = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Domínio personalizado configurado",
    )

    # Metadados
    is_active = models.BooleanField(default=cast(Any, True))
    deleted_at = models.DateTimeField(
        null=True, blank=True, help_text="Data de cancelamento do tenant (soft delete)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ===== NOVOS CAMPOS: Sistema de Cancelamento (BE-ACCOUNT-CANCEL #396) =====
    STATUS_ACTIVE = "active"
    STATUS_CANCELLED = "cancelled"
    STATUS_DELETED = "deleted"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_DELETED, "Permanently Deleted"),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
        help_text="Status da conta do tenant",
    )

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Data/hora do cancelamento (soft delete)",
    )

    cancellation_reason = models.TextField(
        null=True,
        blank=True,
        help_text="Motivo opcional fornecido pelo owner ao cancelar",
    )

    scheduled_deletion_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Data agendada para hard delete (calculada automaticamente)",
    )

    reactivation_token = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        help_text="Token HMAC para link de reativação seguro",
    )

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["status", "cancelled_at"]),  # Para Celery query
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
        """DEPRECATED: Use can_use_basic_reports. Mantido para compatibilidade."""
        return self.can_use_basic_reports()

    def can_use_basic_reports(self):
        """Verifica se pode usar relatórios básicos/overview (Todos os planos)"""
        return self.reports_enabled or self.plan_tier in [
            self.PLAN_FOUNDER,  # Conforme Decision Brief: todos têm acesso
            self.PLAN_BASIC,
            self.PLAN_PRO,
        ]

    def can_use_standard_reports(self):
        """
        DEPRECATED: Use can_use_advanced_reports.
        No modelo de 2 tiers (Basic/Pro), 'Standard' e 'Advanced' reports são ambos features Pro.
        Mantido apenas para retrocompatibilidade temporária.
        """
        return self.can_use_advanced_reports()

    def can_use_advanced_reports(self):
        """Verifica se pode usar relatórios avançados (Business Analysis + Insights) - Pro+"""
        return self.plan_tier == self.PLAN_PRO

    def can_use_pwa_client(self):
        """Verifica se pode usar PWA Cliente (Todos os planos)"""
        return self.pwa_client_enabled or self.plan_tier in [
            self.PLAN_BASIC,
            self.PLAN_PRO,
        ]

    def can_use_white_label(self):
        """Verifica se pode usar white-label (Pro apenas)"""
        return self.plan_tier == self.PLAN_PRO

    def can_use_custom_domain(self):
        """Verifica se o tenant pode usar domínio personalizado (Pro+)."""
        return self.plan_tier == self.PLAN_PRO and bool(self.custom_domain_enabled)

    def can_purchase_extra_credits(self):
        """Verifica se o tenant pode comprar créditos avulsos."""
        return self.comm_extra_allowed

    def has_auto_credit_renewal(self):
        """Indica renovação automática de créditos; depende somente de comm_auto_renew."""
        return self.comm_auto_renew

    def can_use_native_admin(self):
        """Verifica se pode usar app nativo Admin (Pro+ ou flag explícita)"""
        return self.rn_admin_enabled or self.plan_tier == self.PLAN_PRO

    def can_use_native_client(self):
        """Verifica se pode usar app nativo Cliente (Pro+ ou flag explícita)"""
        return self.rn_client_enabled or self.plan_tier == self.PLAN_PRO

    def can_use_native_apps(self):
        """Verifica se pode usar qualquer app nativo"""
        return self.can_use_native_admin() or self.can_use_native_client()

    def can_use_advanced_notifications(self):
        allowed_by_plan = self.plan_tier == self.PLAN_PRO
        has_channel_flag = self.sms_enabled or self.whatsapp_enabled
        has_extra_credit = (
            bool(self.comm_extra_allowed) and (self.comm_credit_eur or 0) > 0
        )
        return (allowed_by_plan and has_channel_flag) or (
            has_channel_flag and has_extra_credit
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

    def is_promotional_billing(self) -> bool:
        """Retorna se o tenant usa trilha promocional sem Stripe."""
        return self.billing_mode == self.BILLING_MODE_PROMOTIONAL

    def uses_stripe_billing(self) -> bool:
        """Retorna se o tenant usa billing padrão com Stripe."""
        return self.billing_mode == self.BILLING_MODE_STRIPE

    def is_promotional_transition_due(self, at=None) -> bool:
        """Indica se a conta promocional já deve converter para plano pago."""
        if not self.is_promotional_billing() or not self.promotional_expires_at:
            return False
        at = at or timezone.now()
        return at >= self.promotional_expires_at

    def apply_promotional_transition(self, at=None) -> bool:
        """Converte tenant promocional expirado para billing padrão com plano pago."""
        if not self.is_promotional_transition_due(at=at):
            return False

        self.billing_mode = self.BILLING_MODE_STRIPE
        self.plan_tier = self.promotional_converts_to_plan
        self.promotional_expires_at = None
        self.save(
            update_fields=[
                "billing_mode",
                "plan_tier",
                "promotional_expires_at",
                "updated_at",
            ]
        )
        return True

    # ===== Métodos para Sistema de Cancelamento (BE-ACCOUNT-CANCEL #396) =====

    def get_retention_days(self):
        """Retorna dias de retenção baseado no plano."""
        RETENTION_DAYS = {
            self.PLAN_BASIC: 30,
            self.PLAN_PRO: 90,
            self.PLAN_FOUNDER: 90,
        }
        return RETENTION_DAYS.get(self.plan_tier, 30)

    def calculate_deletion_date(self):
        """Calcula data de hard delete baseada em cancelled_at + retenção."""
        if not self.cancelled_at:
            return None
        from datetime import timedelta

        retention_days = self.get_retention_days()
        return self.cancelled_at + timedelta(days=retention_days)

    def can_reactivate(self):
        """Verifica se ainda está dentro do período de reativação."""
        if self.status != self.STATUS_CANCELLED:
            return False
        deletion_date = self.calculate_deletion_date()
        if not deletion_date:
            return False
        return timezone.now() < deletion_date

    def generate_reactivation_token(self):
        """Gera token seguro para link de reativação."""
        import hmac
        import hashlib

        secret = settings.SECRET_KEY.encode()
        message = f"{self.id}{self.slug}{self.cancelled_at}".encode()
        return hmac.new(secret, message, hashlib.sha256).hexdigest()[:32]

    def get_feature_flags_dict(self):
        """Retorna dicionário com todas as feature flags para APIs"""
        return {
            "plan_tier": self.plan_tier,
            "billing_mode": self.billing_mode,
            "promotional_expires_at": self.promotional_expires_at,
            "promotional_converts_to_plan": self.promotional_converts_to_plan,
            "addons_enabled": self.addons_enabled,
            "modules": {
                "reports_enabled": self.can_use_basic_reports(),
                "reports_standard_enabled": self.can_use_standard_reports(),
                "reports_advanced_enabled": self.can_use_advanced_reports(),
                "pwa_admin_enabled": self.pwa_admin_enabled,
                "pwa_client_enabled": self.can_use_pwa_client(),
                "rn_admin_enabled": self.can_use_native_admin(),
                "rn_client_enabled": self.can_use_native_client(),
            },
            "notifications": {
                "push_web": self.push_web_enabled,
                "push_mobile": self.push_mobile_enabled,
                "sms": self.sms_enabled and self.can_use_advanced_notifications(),
                "whatsapp": self.whatsapp_enabled
                and self.can_use_advanced_notifications(),
                "enabled_channels": self.get_enabled_notification_channels(),
            },
            "invites": {
                "auto_invite_enabled": bool(self.auto_invite_enabled),
                "can_auto_invite": self.pwa_client_enabled,
            },
            "branding": {
                "white_label_enabled": self.can_use_white_label(),
                "custom_domain_enabled": self.can_use_custom_domain(),
            },
        }


class TenantBusinessHours(models.Model):
    DAY_MONDAY = 0
    DAY_TUESDAY = 1
    DAY_WEDNESDAY = 2
    DAY_THURSDAY = 3
    DAY_FRIDAY = 4
    DAY_SATURDAY = 5
    DAY_SUNDAY = 6

    DAY_CHOICES = [
        (DAY_MONDAY, "Monday"),
        (DAY_TUESDAY, "Tuesday"),
        (DAY_WEDNESDAY, "Wednesday"),
        (DAY_THURSDAY, "Thursday"),
        (DAY_FRIDAY, "Friday"),
        (DAY_SATURDAY, "Saturday"),
        (DAY_SUNDAY, "Sunday"),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="business_hours",
    )
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=cast(Any, True))

    class Meta:
        unique_together = ("tenant", "day_of_week")
        ordering = ["day_of_week"]
        indexes = [
            models.Index(fields=["tenant"]),
            models.Index(fields=["tenant", "day_of_week"]),
        ]

    def __str__(self):
        return (
            f"{self.tenant.name} | {self.get_day_of_week_display()} "
            f"{self.start_time}-{self.end_time}"
        )


class CustomUser(AbstractUser):
    class OpsRoles(models.TextChoices):
        OPS_ADMIN = "ops_admin", "Ops Admin"
        OPS_SUPPORT = "ops_support", "Ops Support"

    class ThemePreference(models.TextChoices):
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"
        SYSTEM = "system", "System"

    class LanguagePreference(models.TextChoices):
        SYSTEM = "system", "System"
        PT = "pt-PT", "Português"
        EN = "en", "English"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,  # Temporário para testes
        help_text="Tenant/salão ao qual o usuário pertence",
    )
    salon_name = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    photo = models.ImageField(
        upload_to="staff_photos/",
        blank=True,
        null=True,
        validators=[validate_profile_image],
        help_text="Foto opcional do membro da equipa",
    )
    birthday = models.DateField(
        blank=True,
        null=True,
        help_text="Data de aniversário opcional do membro da equipa",
    )
    ops_role = models.CharField(
        max_length=20,
        choices=OpsRoles.choices,
        blank=True,
        null=True,
        help_text="Role de staff do console Ops (ops_admin ou ops_support)",
    )
    theme_preference = models.CharField(
        max_length=10,
        choices=ThemePreference.choices,
        default=ThemePreference.SYSTEM,
        help_text="Preferência de tema do usuário (light/dark/system)",
    )
    language_preference = models.CharField(
        max_length=10,
        choices=LanguagePreference.choices,
        default=LanguagePreference.SYSTEM,
        help_text="Preferência de idioma do usuário (pt-PT/en/system)",
    )
    onboarding_status = models.JSONField(
        default=dict,
        blank=True,
        help_text="Status do onboarding do usuário (ex: {'tour_completed': True})",
    )
    jwt_version = models.IntegerField(
        default=1,
        help_text="Versão do token JWT. Incrementado para invalidar tokens existentes.",
    )
    objects: Any = CustomUserManager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "username"]),
            models.Index(fields=["tenant", "email"]),
            models.Index(fields=["ops_role"]),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="users_customuser_email_ci_unique",
            )
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

    @property
    def is_owner(self) -> bool:
        if hasattr(self, "_staff_cache"):
            staff_member = getattr(self, "_staff_cache")
            return bool(
                staff_member and staff_member.role == TenantStaffMember.Role.OWNER
            )
        try:
            staff_member = self.staff_member
        except TenantStaffMember.DoesNotExist:
            staff_member = None
        setattr(self, "_staff_cache", staff_member)
        return bool(staff_member and staff_member.role == TenantStaffMember.Role.OWNER)

    @property
    def staff_role(self) -> str | None:
        if hasattr(self, "_staff_cache"):
            staff_member = getattr(self, "_staff_cache")
            return staff_member.role if staff_member else None
        try:
            staff_member = self.staff_member
        except TenantStaffMember.DoesNotExist:
            staff_member = None
        setattr(self, "_staff_cache", staff_member)
        return staff_member.role if staff_member else None

    def has_staff_role(self, *roles: str) -> bool:
        role = self.staff_role
        return role is not None and role in roles


class TenantStaffMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        COLLABORATOR = "collaborator", "Collaborator"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INVITED = "invited", "Invited"
        DISABLED = "disabled", "Disabled"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="staff_members",
        help_text="Tenant ao qual o membro de equipe pertence.",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_member",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.COLLABORATOR,
        help_text="Perfil de permissão dentro do tenant.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        help_text="Estado atual do membro de equipe.",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_invited",
        help_text="Usuário responsável pelo convite (quando aplicável).",
    )
    invite_token = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text="Token de convite pendente.",
    )
    invite_token_expires_at = models.DateTimeField(null=True, blank=True)
    invited_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant"]),
            models.Index(fields=["tenant", "role"]),
            models.Index(fields=["tenant", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant"],
                condition=Q(role="owner"),
                name="unique_staff_owner_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.user} • {self.tenant} ({self.role})"

    def set_invite(self, token: str, expires_at, invited_by=None):
        self.invite_token = token
        self.invite_token_expires_at = expires_at
        self.status = self.Status.INVITED
        self.invited_at = timezone.now()
        update_fields = [
            "invite_token",
            "invite_token_expires_at",
            "status",
            "invited_at",
            "updated_at",
        ]
        if invited_by is not None:
            self.invited_by = invited_by
            update_fields.append("invited_by")
        self.save(update_fields=update_fields)

    def mark_activated(self):
        self.status = self.Status.ACTIVE
        self.activated_at = timezone.now()
        self.invite_token = None
        self.invite_token_expires_at = None
        self.save(
            update_fields=[
                "status",
                "activated_at",
                "updated_at",
                "invite_token",
                "invite_token_expires_at",
            ]
        )
        self.ensure_professional()

    def mark_disabled(self):
        self.status = self.Status.DISABLED
        self.deactivated_at = timezone.now()
        self.save(update_fields=["status", "deactivated_at", "updated_at"])
        self._set_professionals_active(active=False)

    @property
    def is_owner(self) -> bool:
        return self.role == self.Role.OWNER

    @property
    def is_manager(self) -> bool:
        return self.role == self.Role.MANAGER

    @property
    def is_collaborator(self) -> bool:
        return self.role == self.Role.COLLABORATOR

    def ensure_professional(self, *, auto_create: bool = True):
        """
        Garante que colaboradores tenham um Professional associado.
        Reassocia registros existentes quando necessário.
        """
        if not self.tenant_id or not self.user_id:
            return None

        Professional = apps.get_model("core", "Professional")

        professional = (
            Professional.objects.filter(staff_member=self).select_related(None).first()
        )

        if not professional:
            professional = (
                Professional.objects.filter(tenant=self.tenant, user=self.user)
                .order_by("id")
                .first()
            )

        if professional:
            fields_to_update: list[str] = []
            if professional.staff_member_id != self.id:
                professional.staff_member = self
                fields_to_update.append("staff_member")
            if professional.user_id != self.user_id:
                professional.user = self.user
                fields_to_update.append("user")
            if professional.tenant_id != self.tenant_id:
                professional.tenant = self.tenant
                fields_to_update.append("tenant")
            if self.role == self.Role.COLLABORATOR and not professional.is_active:
                professional.is_active = True
                fields_to_update.append("is_active")
            if fields_to_update:
                professional.save(update_fields=list(dict.fromkeys(fields_to_update)))
            return professional

        if not auto_create or self.role != self.Role.COLLABORATOR:
            return None

        display_name = (
            self.user.get_full_name()
            or self.user.first_name
            or self.user.username
            or (self.user.email or "").split("@")[0]
            or "Professional"
        )
        professional = Professional.objects.create(
            tenant=self.tenant,
            user=self.user,
            staff_member=self,
            name=display_name[:100],
            is_active=True,
        )
        return professional

    def _set_professionals_active(self, *, active: bool):
        Professional = apps.get_model("core", "Professional")
        Professional.objects.filter(staff_member=self).update(is_active=active)


class UserFeatureFlags(models.Model):
    PLAN_BASIC = "basic"
    PLAN_PRO = "pro"
    PLAN_CHOICES = (
        (PLAN_BASIC, "Basic"),
        (PLAN_PRO, "Pro"),
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
    email_enabled = models.BooleanField(
        default=cast(Any, True)
    )  # notificações por e‑mail
    reports_enabled = models.BooleanField(default=cast(Any, False))
    audit_log_enabled = models.BooleanField(default=cast(Any, False))
    i18n_enabled = models.BooleanField(default=cast(Any, False))

    # Auditoria mínima
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"FeatureFlags<{self.user_id}> (pro={self.is_pro}, status={self.pro_status})"


class CommLedger(models.Model):
    """
    Modelo para registrar histórico de créditos de comunicação.
    Registra compras, consumos e expiração de créditos.
    """

    class TransactionType(models.TextChoices):
        PURCHASE = "purchase", "Compra"
        CONSUMPTION = "consumption", "Consumo"
        EXPIRATION = "expiration", "Expiração"
        REFUND = "refund", "Reembolso"
        BONUS = "bonus", "Bônus"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        COMPLETED = "completed", "Concluído"
        FAILED = "failed", "Falhou"
        CANCELLED = "cancelled", "Cancelado"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="comm_ledger",
        help_text="Tenant proprietário do crédito",
    )
    transaction_type = models.CharField(
        max_length=20, choices=TransactionType.choices, help_text="Tipo de transação"
    )
    amount_eur = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Valor da transação em euros"
    )
    balance_before = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Saldo antes da transação"
    )
    balance_after = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Saldo após a transação"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Status da transação",
    )
    description = models.TextField(
        blank=True, help_text="Descrição detalhada da transação"
    )
    reference_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="ID de referência externa (ex: Stripe PaymentIntent)",
    )
    expires_at = models.DateTimeField(
        blank=True, null=True, help_text="Data de expiração do crédito (para compras)"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Usuário que iniciou a transação",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Credit History"
        verbose_name_plural = "Credit History"
        indexes = [
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["tenant", "transaction_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["reference_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tenant.name} - {self.transaction_type} - €{self.amount_eur}"


# Cria/garante flags ao criar usuário
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_feature_flags(sender, instance, created, **kwargs):
    if created:
        UserFeatureFlags.objects.get_or_create(user=instance)
