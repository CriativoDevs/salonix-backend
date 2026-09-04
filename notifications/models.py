from django.db import models
from typing import Any, cast, Optional
from django.contrib.auth import get_user_model
from users.models import Tenant


User = get_user_model()


class NotificationDevice(models.Model):
    """
    Modelo para armazenar tokens de dispositivos para push notifications.
    Usado para web push e mobile push (Expo).
    """

    DEVICE_TYPES = [
        ("web", "Web Push"),
        ("mobile", "Mobile Push (Expo)"),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="notification_devices",
        help_text="Tenant ao qual o device pertence",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notification_devices",
        help_text="Usuário dono do device",
    )
    device_type = models.CharField(
        max_length=10,
        choices=DEVICE_TYPES,
        help_text="Tipo do dispositivo (web/mobile)",
    )
    token = models.CharField(
        max_length=512, help_text="Token do dispositivo para push notifications"
    )
    is_active = models.BooleanField(
        default=cast(Any, True),
        help_text="Se o device está ativo para receber notificações",
    )
    platform = models.CharField(
        max_length=10,
        choices=[("ios", "iOS"), ("android", "Android")],
        null=True,
        blank=True,
        help_text="Sistema operacional do dispositivo (iOS/Android)",
    )
    app_version = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Versão do app mobile (ex: 1.2.3)",
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Data/hora do último uso bem-sucedido deste token",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "user", "device_type"]),
            models.Index(fields=["tenant", "is_active"]),
        ]
        unique_together = [["tenant", "user", "device_type", "token"]]

    def __str__(self):
        tenant_name = self.tenant.name if self.tenant else "No Tenant"
        return (
            f"{self.user.username} - {self.get_device_type_display()} ({tenant_name})"
        )


class Notification(models.Model):
    """
    Modelo para notificações in-app.
    Armazena notificações que aparecem dentro da aplicação.
    """

    NOTIFICATION_TYPES = [
        ("appointment_created", "Agendamento Criado"),
        ("appointment_cancelled", "Agendamento Cancelado"),
        ("appointment_reminder", "Lembrete de Agendamento"),
        ("appointment_completed", "Agendamento Concluído"),
        ("payment_received", "Pagamento Recebido"),
        ("system", "Notificação do Sistema"),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="notifications",
        help_text="Tenant ao qual a notificação pertence",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
        help_text="Usuário que recebe a notificação",
    )
    notification_type = models.CharField(
        max_length=30, choices=NOTIFICATION_TYPES, help_text="Tipo da notificação"
    )
    title = models.CharField(max_length=255, help_text="Título da notificação")
    message = models.TextField(help_text="Conteúdo da notificação")
    is_read = models.BooleanField(
        default=cast(Any, False), help_text="Se a notificação foi lida"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dados adicionais da notificação (appointment_id, etc.)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(
        null=True, blank=True, help_text="Quando a notificação foi lida"
    )
    customer = models.ForeignKey(
        "core.SalonCustomer",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
        help_text="Cliente que recebe a notificação (se não for usuário do sistema)",
    )
    appointment = models.ForeignKey(
        "core.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
        help_text="Agendamento relacionado (se houver)",
    )

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "user", "-created_at"]),
            models.Index(fields=["tenant", "user", "is_read"]),
            models.Index(fields=["tenant", "notification_type"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        tenant_name = self.tenant.name if self.tenant else "No Tenant"
        status = "✓" if self.is_read else "●"
        return f"{status} {self.title} - {self.user.username} ({tenant_name})"


class NotificationLog(models.Model):
    """
    Modelo para logs de envio de notificações.
    Usado para métricas e debugging de todos os canais.
    """

    CHANNELS = [
        ("in_app", "In-App"),
        ("push_web", "Web Push"),
        ("push_mobile", "Mobile Push"),
        ("sms", "SMS"),
        ("whatsapp", "WhatsApp"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pendente"),
        ("sent", "Enviado"),
        ("delivered", "Entregue"),
        ("failed", "Falhou"),
        ("skipped", "Pulado"),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="notification_logs",
        help_text="Tenant da notificação",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notification_logs",
        null=True,
        blank=True,
        help_text="Usuário destinatário",
    )
    customer = models.ForeignKey(
        "core.SalonCustomer",
        on_delete=models.CASCADE,
        related_name="notification_logs",
        null=True,
        blank=True,
        help_text="Cliente destinatário",
    )
    channel = models.CharField(
        max_length=15, choices=CHANNELS, help_text="Canal de envio da notificação"
    )
    notification_type = models.CharField(
        max_length=30, help_text="Tipo da notificação (mesmo do Notification)"
    )
    title = models.CharField(max_length=255, help_text="Título da notificação enviada")
    message = models.TextField(help_text="Conteúdo da notificação enviada")
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default="pending",
        help_text="Status do envio",
    )
    error_message = models.TextField(
        null=True, blank=True, help_text="Mensagem de erro (se houver)"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dados adicionais (device_token, provider_response, etc.)",
    )
    sent_at = models.DateTimeField(
        null=True, blank=True, help_text="Quando foi enviado"
    )
    delivered_at = models.DateTimeField(
        null=True, blank=True, help_text="Quando foi entregue (se disponível)"
    )
    appointment = models.ForeignKey(
        "core.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_logs",
        help_text="Agendamento relacionado (se houver)",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "channel", "-created_at"]),
            models.Index(fields=["tenant", "user", "-created_at"]),
            models.Index(fields=["tenant", "status", "channel"]),
            models.Index(fields=["created_at"]),  # Para métricas temporais
        ]
        ordering = ["-created_at"]

    def __str__(self):
        tenant_name = self.tenant.name if self.tenant else "No Tenant"
        return f"{self.get_channel_display()} - {self.status} - {self.user.username} ({tenant_name})"


class EmailMarketingCampaign(models.Model):
    """
    Campanha de email marketing disparada por um tenant à sua base de
    clientes elegíveis (BE-MARKETING-04, #522).

    Uma linha por campanha, com as contagens já resolvidas no momento da
    criação (elegibilidade, cota mensal grátis e crédito de comunicação
    cobrado/insuficiente) — o envio em si acontece de forma assíncrona
    (`notifications.tasks.send_marketing_campaign_task`), mas a decisão de
    quem entra em cada balde (grátis/crédito/bloqueado/sem consentimento)
    é tomada de forma síncrona e atômica na criação, para não haver disputa
    de crédito entre campanhas concorrentes.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Na fila"
        COMPLETED = "completed", "Concluída"
        FAILED = "failed", "Falhou"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="marketing_campaigns",
        help_text="Tenant que disparou a campanha",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketing_campaigns",
        help_text="Staff que compôs/disparou a campanha",
    )
    subject = models.CharField(max_length=255, help_text="Assunto do email")
    body = models.TextField(help_text="Corpo do email (texto)")
    reply_to = models.EmailField(
        blank=True,
        null=True,
        help_text="Reply-To escolhido pelo tenant (opcional); o From é sempre timelyone.today",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.QUEUED
    )

    # Contagens resolvidas na criação (ver docstring da classe)
    eligible_count = models.PositiveIntegerField(
        default=0, help_text="Clientes com consentimento de marketing e email"
    )
    skipped_no_consent_count = models.PositiveIntegerField(
        default=0,
        help_text="Clientes com email mas sem consentimento ativo (ou com unsubscribe)",
    )
    free_sent_count = models.PositiveIntegerField(
        default=0, help_text="Envios cobertos pela cota mensal grátis (50/mês)"
    )
    credit_sent_count = models.PositiveIntegerField(
        default=0, help_text="Envios excedentes cobrados do crédito de comunicação"
    )
    credit_charged_eur = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total cobrado do crédito de comunicação para esta campanha",
    )
    blocked_credit_count = models.PositiveIntegerField(
        default=0,
        help_text="Elegíveis não enviados por falta de crédito de comunicação",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "-created_at"]),
            models.Index(fields=["tenant", "status"]),
        ]
        ordering = ["-created_at"]

    @property
    def total_sent_count(self) -> int:
        return self.free_sent_count + self.credit_sent_count

    def __str__(self):
        tenant_name = self.tenant.name if self.tenant else "No Tenant"
        return f"Campanha '{self.subject}' ({tenant_name}) - {self.status}"
