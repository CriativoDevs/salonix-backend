from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class PlatformAnnouncementQuerySet(models.QuerySet):
    """Queries de leitura para comunicados da plataforma (BE-PLATFORM-01).

    Métodos encadeáveis para que a mesma regra de "ativo" seja usada tanto no
    endpoint de leitura das apps quanto em qualquer uso futuro (ex.: BE-PLATFORM-02).
    """

    def published(self):
        return self.filter(status=PlatformAnnouncement.STATUS_PUBLISHED)

    def within_window(self, at=None):
        at = at or timezone.now()
        return self.filter(publish_at__lte=at).filter(
            Q(expire_at__isnull=True) | Q(expire_at__gte=at)
        )

    def for_environment(self, environment):
        """Anúncios sem `environments` definido aparecem em todos os ambientes.

        Filtrado em Python (e não via `__contains` do JSONField) porque esse
        lookup não é suportado no SQLite (dev/test) — apenas no Postgres
        (staging/prod). O volume de comunicados é pequeno, então o custo é
        desprezível.
        """
        ids = [
            obj.pk
            for obj in self.only("id", "environments")
            if not obj.environments or environment in obj.environments
        ]
        return self.filter(pk__in=ids)

    def for_tenant(self, tenant):
        """Aplica a segmentação de público (audience_scope) para um tenant específico.

        A checagem de `target_plans` é feita em Python pelo mesmo motivo do
        `for_environment` (compatibilidade SQLite/Postgres).
        """
        candidates = self.filter(
            Q(audience_scope=PlatformAnnouncement.AUDIENCE_ALL)
            | Q(audience_scope=PlatformAnnouncement.AUDIENCE_TENANTS, tenants=tenant)
            | Q(audience_scope=PlatformAnnouncement.AUDIENCE_PLANS)
        ).distinct()

        ids = [
            obj.pk
            for obj in candidates.only("id", "audience_scope", "target_plans")
            if obj.audience_scope != PlatformAnnouncement.AUDIENCE_PLANS
            or tenant.plan_tier in (obj.target_plans or [])
        ]
        return self.filter(pk__in=ids)

    def active_for_tenant(self, tenant, environment=None, at=None):
        environment = environment or getattr(settings, "ENV", "dev")
        return (
            self.published()
            .within_window(at=at)
            .for_environment(environment)
            .for_tenant(tenant)
        )


class PlatformAnnouncementManager(models.Manager):
    def get_queryset(self):
        return PlatformAnnouncementQuerySet(self.model, using=self._db)

    def active_for_tenant(self, tenant, environment=None, at=None):
        return self.get_queryset().active_for_tenant(
            tenant, environment=environment, at=at
        )


class PlatformAnnouncement(models.Model):
    """Comunicado interno da plataforma (avisos de manutenção, correções, updates).

    BE-PLATFORM-01 (#439): domínio base com segmentação por tenant/plano/ambiente
    e janela de publicação. O modelo foi desenhado para ser estendido em
    BE-PLATFORM-02 (#440) — inbox por usuário com estado de leitura/dismissal e
    auditoria — sem grande refatoração: a relação "quem viu o quê" deve ficar
    numa tabela separada (ex. `PlatformAnnouncementReceipt`) com FK para este
    model, e o `created_by` já registrado aqui serve de base para a auditoria.
    """

    TYPE_MAINTENANCE = "maintenance"
    TYPE_INCIDENT = "incident"
    TYPE_FIX = "fix"
    TYPE_FEATURE = "feature"
    TYPE_GENERAL = "general"
    TYPE_CHOICES = [
        (TYPE_MAINTENANCE, "Manutenção"),
        (TYPE_INCIDENT, "Incidente"),
        (TYPE_FIX, "Correção"),
        (TYPE_FEATURE, "Novidade"),
        (TYPE_GENERAL, "Geral"),
    ]

    PRIORITY_LOW = "low"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_HIGH = "high"
    PRIORITY_CRITICAL = "critical"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Baixa"),
        (PRIORITY_MEDIUM, "Média"),
        (PRIORITY_HIGH, "Alta"),
        (PRIORITY_CRITICAL, "Crítica"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Rascunho"),
        (STATUS_PUBLISHED, "Publicado"),
        (STATUS_ARCHIVED, "Arquivado"),
    ]

    # Segmentação de público. AUDIENCE_ALL ignora `tenants`/`target_plans`;
    # AUDIENCE_TENANTS usa a M2M `tenants`; AUDIENCE_PLANS usa `target_plans`
    # (lista de `Tenant.plan_tier`, ex.: ["basic", "founder"]).
    AUDIENCE_ALL = "all_tenants"
    AUDIENCE_TENANTS = "specific_tenants"
    AUDIENCE_PLANS = "specific_plans"
    AUDIENCE_CHOICES = [
        (AUDIENCE_ALL, "Todos os tenants"),
        (AUDIENCE_TENANTS, "Tenants específicos"),
        (AUDIENCE_PLANS, "Planos específicos"),
    ]

    # Ambientes espelham DJANGO_ENV (settings.ENV): dev, uat (staging), prod.
    ENV_DEV = "dev"
    ENV_UAT = "uat"
    ENV_PROD = "prod"
    ENV_CHOICES = [
        (ENV_DEV, "Dev"),
        (ENV_UAT, "Staging/UAT"),
        (ENV_PROD, "Produção"),
    ]

    title = models.CharField(max_length=255)
    body = models.TextField()
    announcement_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_GENERAL
    )
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM
    )
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True
    )

    publish_at = models.DateTimeField(
        default=timezone.now,
        help_text="Início da janela de exibição do comunicado.",
    )
    expire_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fim da janela de exibição. Vazio = sem data de expiração.",
    )

    audience_scope = models.CharField(
        max_length=20,
        choices=AUDIENCE_CHOICES,
        default=AUDIENCE_ALL,
        help_text="Como o público-alvo é determinado.",
    )
    tenants = models.ManyToManyField(
        "users.Tenant",
        blank=True,
        related_name="platform_announcements",
        help_text="Tenants alvo quando audience_scope=specific_tenants.",
    )
    target_plans = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Lista de plan_tier (ex.: ['basic', 'founder']) alvo quando "
            "audience_scope=specific_plans."
        ),
    )

    environments = models.JSONField(
        default=list,
        blank=True,
        help_text="Ambientes (dev/uat/prod) onde o comunicado aparece. Vazio = todos.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="platform_announcements_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PlatformAnnouncementManager()

    class Meta:
        ordering = ("-publish_at", "-created_at")
        indexes = [
            models.Index(fields=["status", "publish_at"], name="pc_status_publish_idx"),
            models.Index(fields=["audience_scope"], name="pc_audience_scope_idx"),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def publish(self):
        self.status = self.STATUS_PUBLISHED
        self.save(update_fields=["status", "updated_at"])

    def archive(self):
        self.status = self.STATUS_ARCHIVED
        self.save(update_fields=["status", "updated_at"])

    @property
    def is_within_window(self) -> bool:
        now = timezone.now()
        if self.publish_at and self.publish_at > now:
            return False
        if self.expire_at and self.expire_at < now:
            return False
        return True
