from rest_framework import serializers
from .models import Notification, NotificationDevice, NotificationLog


class NotificationDeviceSerializer(serializers.ModelSerializer):
    """
    Serializer para registro de dispositivos para push notifications.
    Usado no endpoint POST /api/notifications/register_device
    """

    class Meta:
        model = NotificationDevice
        fields = [
            "id",
            "device_type",
            "token",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_token(self, value):
        """Validar que o token não está vazio"""
        if not value or not value.strip():
            raise serializers.ValidationError("Token do dispositivo é obrigatório.")
        return value.strip()


class NotificationSerializer(serializers.ModelSerializer):
    """
    Serializer para notificações in-app.
    Usado para listar e marcar notificações como lidas.
    """

    class Meta:
        model = Notification
        fields = [
            "id",
            "notification_type",
            "title",
            "message",
            "is_read",
            "metadata",
            "created_at",
            "read_at",
        ]
        read_only_fields = ["id", "created_at", "read_at"]


class NotificationMarkReadSerializer(serializers.Serializer):
    """
    Serializer para marcar notificações como lidas.
    Usado no endpoint PATCH /api/notifications/{id}/read/
    """

    is_read = serializers.BooleanField(default=True)


class NotificationTestSerializer(serializers.Serializer):
    """
    Serializer para testar canais de notificação.
    Usado no endpoint POST /api/notifications/test
    """

    CHANNEL_CHOICES = [
        ("in_app", "In-App"),
        ("push_web", "Web Push"),
        ("push_mobile", "Mobile Push"),
        ("sms", "SMS"),
        ("whatsapp", "WhatsApp"),
    ]

    channel = serializers.ChoiceField(
        choices=CHANNEL_CHOICES, help_text="Canal a ser testado"
    )
    message = serializers.CharField(
        max_length=500, default="Teste de notificação", help_text="Mensagem de teste"
    )

    def validate_message(self, value):
        """Validar que a mensagem não está vazia"""
        if not value or not value.strip():
            raise serializers.ValidationError("Mensagem de teste é obrigatória.")
        return value.strip()


class NotificationLogSerializer(serializers.ModelSerializer):
    """
    Serializer para logs de notificações.
    Usado para debugging e métricas (apenas leitura).
    """

    channel_display = serializers.CharField(
        source="get_channel_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = NotificationLog
        fields = [
            "id",
            "channel",
            "channel_display",
            "notification_type",
            "title",
            "message",
            "status",
            "status_display",
            "error_message",
            "metadata",
            "sent_at",
            "delivered_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "channel",
            "channel_display",
            "notification_type",
            "title",
            "message",
            "status",
            "status_display",
            "error_message",
            "metadata",
            "sent_at",
            "delivered_at",
            "created_at",
        ]


class NotificationMarkAllReadResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    updated_count = serializers.IntegerField()


class NotificationTestResponseSerializer(serializers.Serializer):
    channel = serializers.CharField()
    success = serializers.BooleanField()
    message = serializers.CharField()


class NotificationStatsResponseSerializer(serializers.Serializer):
    total_notifications = serializers.IntegerField()
    unread_notifications = serializers.IntegerField()
    read_notifications = serializers.IntegerField()
    registered_devices = serializers.IntegerField()
