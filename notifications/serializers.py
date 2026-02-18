from rest_framework import serializers
import logging
from enum import Enum
from .models import Notification, NotificationDevice, NotificationLog
from core.models import CustomerCommunicationConsent, SalonCustomer


class NotificationChannel(str, Enum):
    in_app = "in_app"
    push_web = "push_web"
    push_mobile = "push_mobile"
    sms = "sms"
    whatsapp = "whatsapp"


class NotificationStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    delivered = "delivered"
    failed = "failed"
    skipped = "skipped"


class CommunicationChannel(str, Enum):
    in_app = "in_app"
    push_web = "push_web"
    push_mobile = "push_mobile"
    sms = "sms"
    whatsapp = "whatsapp"
    email = "email"


class CommunicationPurpose(str, Enum):
    marketing = "marketing"
    transactional = "transactional"


class CommunicationStatus(str, Enum):
    consented = "consented"
    withdrawn = "withdrawn"
    pending = "pending"


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
            "platform",
            "app_version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_token(self, value):
        """Validar que o token não está vazio"""
        if not value or not value.strip():
            raise serializers.ValidationError("Token do dispositivo é obrigatório.")
        return value.strip()

    def create(self, validated_data):
        logger = logging.getLogger("notifications.device")
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        raw_tenant = getattr(request, "tenant", None) if request else None
        user_tenant = getattr(user, "tenant", None) if user else None
        tenant = raw_tenant or user_tenant

        if (
            tenant is None
            or user is None
            or not getattr(user, "is_authenticated", False)
        ):
            logger.error(
                "NotificationDeviceSerializer.create tenant_or_user_missing",
                extra={
                    "serializer_version": "v2",
                    "has_request": bool(request),
                    "user_repr": repr(user),
                    "raw_tenant_repr": repr(raw_tenant),
                    "user_tenant_repr": repr(user_tenant),
                    "user_is_authenticated": getattr(user, "is_authenticated", None),
                },
            )
            raise serializers.ValidationError("tenant_or_user_missing")

        device = NotificationDevice.objects.create(
            tenant=tenant,
            user=user,
            **validated_data,
        )
        logger.info(
            "NotificationDeviceSerializer.create success",
            extra={
                "serializer_version": "v2",
                "tenant_id": tenant.id if tenant else None,
                "user_id": user.id if user else None,
                "device_id": device.id,
                "device_type": device.device_type,
                "platform": device.platform,
            },
        )
        return device


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

    channel = serializers.ChoiceField(
        choices=NotificationChannel, help_text="Canal a ser testado"
    )
    message = serializers.CharField(
        max_length=500, default="Teste de notificação", help_text="Mensagem de teste"
    )

    def validate_message(self, value):
        """Validar que a mensagem não está vazia"""
        if not value or not value.strip():
            raise serializers.ValidationError("Mensagem de teste é obrigatória.")
        return value.strip()


class TestPushNotificationSerializer(serializers.Serializer):
    """
    Serializer para testar push notifications mobile.
    Usado no endpoint POST /api/notifications/test-push/
    """

    user_id = serializers.IntegerField(
        help_text="ID do usuário para enviar push de teste"
    )
    title = serializers.CharField(
        max_length=100,
        default="Teste de Push",
        help_text="Título da notificação",
    )
    message = serializers.CharField(
        max_length=500,
        default="Esta é uma notificação de teste",
        help_text="Mensagem da notificação",
    )
    appointment_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID do agendamento (opcional, para testar deep link)",
    )

    def validate_title(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Título é obrigatório.")
        return value.strip()

    def validate_message(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Mensagem é obrigatória.")
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


class CommunicationConsentSerializer(serializers.ModelSerializer):
    customer_id = serializers.IntegerField(source="customer.id", read_only=True)
    channel = serializers.ChoiceField(choices=CommunicationChannel, read_only=True)
    purpose = serializers.ChoiceField(choices=CommunicationPurpose, read_only=True)
    status = serializers.ChoiceField(choices=CommunicationStatus, read_only=True)

    class Meta:
        model = CustomerCommunicationConsent
        fields = [
            "id",
            "tenant",
            "customer_id",
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
        ]
        read_only_fields = [
            "id",
            "tenant",
            "status",
            "consented_at",
            "withdrawn_at",
            "created_at",
            "updated_at",
        ]


class CommunicationConsentCreateSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    channel = serializers.ChoiceField(choices=CommunicationChannel)
    purpose = serializers.ChoiceField(choices=CommunicationPurpose)
    source = serializers.ChoiceField(
        choices=[
            ("admin", "Admin"),
            ("self_service", "Self Service"),
            ("import", "Import"),
        ],
        required=False,
        allow_null=True,
    )
    ip_address = serializers.IPAddressField(required=False, allow_null=True)
    user_agent = serializers.CharField(required=False, allow_null=True, max_length=256)
    version = serializers.CharField(required=False, allow_null=True, max_length=32)
    locale = serializers.CharField(required=False, allow_null=True, max_length=16)

    def validate_customer_id(self, value):
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None)
        customer = SalonCustomer.objects.filter(id=value).first()
        if not customer:
            raise serializers.ValidationError("Cliente não encontrado.")
        if tenant and customer.tenant_id != tenant.id:
            raise serializers.ValidationError("Cliente não pertence ao tenant.")
        return value


class CommunicationConsentWithdrawSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    channel = serializers.ChoiceField(choices=CommunicationChannel)
    purpose = serializers.ChoiceField(choices=CommunicationPurpose)
    source = serializers.ChoiceField(
        choices=[
            ("admin", "Admin"),
            ("self_service", "Self Service"),
            ("import", "Import"),
        ],
        required=False,
        allow_null=True,
    )
    ip_address = serializers.IPAddressField(required=False, allow_null=True)
    user_agent = serializers.CharField(required=False, allow_null=True, max_length=256)
    channel = serializers.ChoiceField(choices=NotificationChannel, read_only=True)
    status = serializers.ChoiceField(choices=NotificationStatus, read_only=True)


class NotificationChannel(str, Enum):
    in_app = "in_app"
    push_web = "push_web"
    push_mobile = "push_mobile"
    sms = "sms"
    whatsapp = "whatsapp"


class NotificationStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    delivered = "delivered"
    failed = "failed"
    skipped = "skipped"


class CommunicationChannel(str, Enum):
    in_app = "in_app"
    push_web = "push_web"
    push_mobile = "push_mobile"
    sms = "sms"
    whatsapp = "whatsapp"
    email = "email"


class CommunicationPurpose(str, Enum):
    marketing = "marketing"
    transactional = "transactional"
