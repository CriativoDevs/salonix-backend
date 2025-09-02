from django.db import models
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
    token = models.TextField(help_text="Token do dispositivo para push notifications")
    is_active = models.BooleanField(
        default=True, help_text="Se o device está ativo para receber notificações"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "user", "device_type"]),
            models.Index(fields=["tenant", "is_active"]),
        ]
        unique_together = [["user", "device_type", "token"]]

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
        help_text="Usuário que recebe a notificação",
    )
    notification_type = models.CharField(
        max_length=30, choices=NOTIFICATION_TYPES, help_text="Tipo da notificação"
    )
    title = models.CharField(max_length=255, help_text="Título da notificação")
    message = models.TextField(help_text="Conteúdo da notificação")
    is_read = models.BooleanField(default=False, help_text="Se a notificação foi lida")
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dados adicionais da notificação (appointment_id, etc.)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(
        null=True, blank=True, help_text="Quando a notificação foi lida"
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
        help_text="Usuário destinatário",
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
