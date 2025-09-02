import logging
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from core.mixins import TenantIsolatedMixin
from .models import Notification, NotificationDevice, NotificationLog
from .serializers import (
    NotificationSerializer,
    NotificationDeviceSerializer,
    NotificationMarkReadSerializer,
    NotificationTestSerializer,
    NotificationLogSerializer,
)
from .services import notification_service

logger = logging.getLogger(__name__)


class NotificationListView(TenantIsolatedMixin, generics.ListAPIView):
    """
    GET /api/notifications/

    Lista notificações in-app do usuário autenticado.
    Suporta filtros: ?is_read=false&limit=20
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    queryset = Notification.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtrar por usuário autenticado
        queryset = queryset.filter(user=self.request.user)

        # Filtro por status de leitura
        is_read = self.request.query_params.get("is_read")
        if is_read is not None:
            is_read_bool = is_read.lower() in ["true", "1"]
            queryset = queryset.filter(is_read=is_read_bool)

        # Filtro por tipo
        notification_type = self.request.query_params.get("type")
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)

        return queryset.order_by("-created_at")


class NotificationMarkReadView(TenantIsolatedMixin, generics.UpdateAPIView):
    """
    PATCH /api/notifications/{id}/read/

    Marca uma notificação como lida/não lida.
    """

    serializer_class = NotificationMarkReadSerializer
    permission_classes = [IsAuthenticated]
    queryset = Notification.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        # Só pode marcar suas próprias notificações
        return queryset.filter(user=self.request.user)

    def patch(self, request, *args, **kwargs):
        notification = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        is_read = serializer.validated_data.get("is_read", True)

        notification.is_read = is_read
        notification.read_at = timezone.now() if is_read else None
        notification.save()

        return Response(
            {
                "id": notification.id,
                "is_read": notification.is_read,
                "read_at": notification.read_at,
            }
        )


class NotificationMarkAllReadView(TenantIsolatedMixin, APIView):
    """
    POST /api/notifications/mark-all-read/

    Marca todas as notificações não lidas do usuário como lidas.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Buscar notificações não lidas do usuário no tenant
        queryset = Notification.objects.filter(
            tenant=request.tenant, user=request.user, is_read=False
        )

        # Marcar todas como lidas
        updated_count = queryset.update(is_read=True, read_at=timezone.now())

        logger.info(
            f"Marcadas {updated_count} notificações como lidas",
            extra={
                "tenant_id": request.tenant.id,
                "user_id": request.user.id,
                "updated_count": updated_count,
            },
        )

        return Response(
            {
                "message": f"{updated_count} notificações marcadas como lidas",
                "updated_count": updated_count,
            }
        )


class NotificationDeviceRegisterView(TenantIsolatedMixin, generics.CreateAPIView):
    """
    POST /api/notifications/register_device

    Registra ou atualiza um device token para push notifications.
    """

    serializer_class = NotificationDeviceSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        # Verificar se já existe device com mesmo token
        existing_device = NotificationDevice.objects.filter(
            tenant=self.request.tenant,
            user=self.request.user,
            device_type=serializer.validated_data["device_type"],
            token=serializer.validated_data["token"],
        ).first()

        if existing_device:
            # Atualizar device existente
            existing_device.is_active = serializer.validated_data.get("is_active", True)
            existing_device.save()

            logger.info(
                f"Device {existing_device.device_type} atualizado para {self.request.user.username}",
                extra={
                    "tenant_id": self.request.tenant.id,
                    "user_id": self.request.user.id,
                    "device_type": existing_device.device_type,
                },
            )

            # Retornar o device existente
            self.instance = existing_device
        else:
            # Criar novo device
            serializer.save(tenant=self.request.tenant, user=self.request.user)

            logger.info(
                f"Novo device {serializer.instance.device_type} registrado para {self.request.user.username}",
                extra={
                    "tenant_id": self.request.tenant.id,
                    "user_id": self.request.user.id,
                    "device_type": serializer.instance.device_type,
                },
            )

            self.instance = serializer.instance

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # Serializar o device (existente ou novo)
        response_serializer = self.get_serializer(self.instance)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class NotificationTestView(TenantIsolatedMixin, APIView):
    """
    POST /api/notifications/test

    Testa um canal específico de notificação.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = NotificationTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel = serializer.validated_data["channel"]
        message = serializer.validated_data["message"]

        # Testar o canal
        success = notification_service.test_channel(
            tenant=request.tenant, user=request.user, channel=channel, message=message
        )

        logger.info(
            f"Teste de canal {channel} para {request.user.username}: {'sucesso' if success else 'falha'}",
            extra={
                "tenant_id": request.tenant.id,
                "user_id": request.user.id,
                "channel": channel,
                "success": success,
            },
        )

        return Response(
            {
                "channel": channel,
                "success": success,
                "message": (
                    "Notificação de teste enviada com sucesso"
                    if success
                    else "Falha ao enviar notificação de teste"
                ),
            }
        )


class NotificationStatsView(TenantIsolatedMixin, APIView):
    """
    GET /api/notifications/stats

    Estatísticas de notificações do usuário.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Contar notificações do usuário no tenant
        total_notifications = Notification.objects.filter(
            tenant=request.tenant, user=request.user
        ).count()

        unread_notifications = Notification.objects.filter(
            tenant=request.tenant, user=request.user, is_read=False
        ).count()

        # Contar devices registrados
        registered_devices = NotificationDevice.objects.filter(
            tenant=request.tenant, user=request.user, is_active=True
        ).count()

        return Response(
            {
                "total_notifications": total_notifications,
                "unread_notifications": unread_notifications,
                "read_notifications": total_notifications - unread_notifications,
                "registered_devices": registered_devices,
            }
        )


class NotificationLogListView(TenantIsolatedMixin, generics.ListAPIView):
    """
    GET /api/notifications/logs/

    Lista logs de notificações (apenas para debug/admin).
    Endpoint privado para debugging.
    """

    serializer_class = NotificationLogSerializer
    permission_classes = [IsAuthenticated]
    queryset = NotificationLog.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()

        # Apenas superusers podem ver todos os logs
        if not self.request.user.is_superuser:
            queryset = queryset.filter(user=self.request.user)

        # Filtros opcionais
        channel = self.request.query_params.get("channel")
        if channel:
            queryset = queryset.filter(channel=channel)

        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by("-created_at")
