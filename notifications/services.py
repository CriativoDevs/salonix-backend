import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from django.contrib.auth import get_user_model
from django.utils import timezone
from users.models import Tenant
from .models import Notification, NotificationDevice, NotificationLog

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationService:
    """
    Serviço central para envio de notificações.
    Abstrai os diferentes canais (in-app, push, sms, whatsapp).
    """

    def __init__(self):
        self.drivers = {
            "in_app": InAppNotificationDriver(),
            "push_web": WebPushDriver(),
            "push_mobile": MobilePushDriver(),
            "sms": SMSDriver(),
            "whatsapp": WhatsAppDriver(),
        }

    def send_notification(
        self,
        tenant: Tenant,
        user: Any,
        channels: List[str],
        notification_type: str,
        title: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:
        """
        Enviar notificação através de múltiplos canais.

        Args:
            tenant: Tenant da notificação
            user: Usuário destinatário
            channels: Lista de canais ['in_app', 'push_web', etc.]
            notification_type: Tipo da notificação
            title: Título
            message: Conteúdo
            metadata: Dados extras (appointment_id, etc.)

        Returns:
            Dict com resultado por canal: {'in_app': True, 'sms': False}
        """
        if metadata is None:
            metadata = {}

        results = {}

        for channel in channels:
            if channel not in self.drivers:
                logger.warning(f"Canal desconhecido: {channel}")
                results[channel] = False
                continue

            try:
                driver = self.drivers[channel]
                success = driver.send(
                    tenant=tenant,
                    user=user,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    metadata=metadata,
                )
                results[channel] = success

                # Log do resultado
                self._log_notification(
                    tenant=tenant,
                    user=user,
                    channel=channel,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    status="sent" if success else "failed",
                    metadata=metadata,
                )

            except Exception as e:
                logger.error(
                    f"Erro ao enviar notificação via {channel}: {e}",
                    extra={
                        "tenant_id": tenant.id,
                        "user_id": user.id,
                        "channel": channel,
                        "notification_type": notification_type,
                    },
                )
                results[channel] = False

                # Log do erro
                self._log_notification(
                    tenant=tenant,
                    user=user,
                    channel=channel,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    status="failed",
                    error_message=str(e),
                    metadata=metadata,
                )

        return results

    def test_channel(
        self,
        tenant: Tenant,
        user: Any,
        channel: str,
        message: str = "Teste de notificação",
    ) -> bool:
        """
        Testar um canal específico.
        Usado pelo endpoint POST /api/notifications/test
        """
        return self.send_notification(
            tenant=tenant,
            user=user,
            channels=[channel],
            notification_type="system",
            title="Teste de Notificação",
            message=message,
            metadata={"is_test": True},
        ).get(channel, False)

    def _log_notification(
        self,
        tenant: Tenant,
        user: Any,
        channel: str,
        notification_type: str,
        title: str,
        message: str,
        status: str,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Criar log da notificação para métricas"""
        NotificationLog.objects.create(
            tenant=tenant,
            user=user,
            channel=channel,
            notification_type=notification_type,
            title=title,
            message=message,
            status=status,
            error_message=error_message,
            metadata=metadata or {},
            sent_at=timezone.now() if status == "sent" else None,
        )


class NotificationDriverBase:
    """Classe base para drivers de notificação"""

    def send(
        self,
        tenant: Tenant,
        user: Any,
        notification_type: str,
        title: str,
        message: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Implementar envio específico do canal"""
        raise NotImplementedError


class InAppNotificationDriver(NotificationDriverBase):
    """Driver para notificações in-app"""

    def send(
        self,
        tenant: Tenant,
        user: Any,
        notification_type: str,
        title: str,
        message: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Criar notificação in-app no banco de dados"""
        try:
            Notification.objects.create(
                tenant=tenant,
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                metadata=metadata,
            )
            logger.info(
                f"Notificação in-app criada para {user.username}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "notification_type": notification_type,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Erro ao criar notificação in-app: {e}")
            return False


class WebPushDriver(NotificationDriverBase):
    """Driver para web push notifications (stub na fase 1)"""

    def send(
        self,
        tenant: Tenant,
        user: Any,
        notification_type: str,
        title: str,
        message: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Simular envio de web push"""
        # Verificar se usuário tem device web registrado
        device = NotificationDevice.objects.filter(
            tenant=tenant, user=user, device_type="web", is_active=True
        ).first()

        if not device:
            logger.warning(
                f"Usuário {user.username} não tem device web registrado",
                extra={"tenant_id": tenant.id, "user_id": user.id},
            )
            return False

        # FASE 1: Apenas simular e logar
        logger.info(
            f"[SIMULADO] Web push enviado para {user.username}",
            extra={
                "tenant_id": tenant.id,
                "user_id": user.id,
                "device_token": device.token[:20] + "...",  # Não logar token completo
                "title": title,
                "notification_message": message,  # Renomeado para evitar conflito
            },
        )
        return True


class MobilePushDriver(NotificationDriverBase):
    """Driver para mobile push notifications via Expo (stub na fase 1)"""

    def send(
        self,
        tenant: Tenant,
        user: Any,
        notification_type: str,
        title: str,
        message: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Simular envio de mobile push"""
        device = NotificationDevice.objects.filter(
            tenant=tenant, user=user, device_type="mobile", is_active=True
        ).first()

        if not device:
            logger.warning(
                f"Usuário {user.username} não tem device mobile registrado",
                extra={"tenant_id": tenant.id, "user_id": user.id},
            )
            return False

        # FASE 1: Apenas simular e logar
        logger.info(
            f"[SIMULADO] Mobile push (Expo) enviado para {user.username}",
            extra={
                "tenant_id": tenant.id,
                "user_id": user.id,
                "expo_token": device.token[:20] + "...",
                "title": title,
                "notification_message": message,  # Renomeado para evitar conflito
            },
        )
        return True


class SMSDriver(NotificationDriverBase):
    """Driver para SMS (stub na fase 1)"""

    def send(
        self,
        tenant: Tenant,
        user: Any,
        notification_type: str,
        title: str,
        message: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Simular envio de SMS"""
        # Verificar se usuário tem telefone
        if not user.phone_number:
            logger.warning(
                f"Usuário {user.username} não tem telefone cadastrado",
                extra={"tenant_id": tenant.id, "user_id": user.id},
            )
            return False

        # FASE 1: Apenas simular e logar
        logger.info(
            f"[SIMULADO] SMS enviado para {user.username}",
            extra={
                "tenant_id": tenant.id,
                "user_id": user.id,
                "phone": user.phone_number,
                "notification_message": message,  # Renomeado para evitar conflito
            },
        )
        return True


class WhatsAppDriver(NotificationDriverBase):
    """Driver para WhatsApp Business API (stub na fase 1)"""

    def send(
        self,
        tenant: Tenant,
        user: Any,
        notification_type: str,
        title: str,
        message: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Simular envio de WhatsApp"""
        # Verificar se usuário tem telefone
        if not user.phone_number:
            logger.warning(
                f"Usuário {user.username} não tem telefone cadastrado para WhatsApp",
                extra={"tenant_id": tenant.id, "user_id": user.id},
            )
            return False

        # FASE 1: Apenas simular e logar
        logger.info(
            f"[SIMULADO] WhatsApp enviado para {user.username}",
            extra={
                "tenant_id": tenant.id,
                "user_id": user.id,
                "phone": user.phone_number,
                "notification_message": f"{title}\n{message}",  # Renomeado para evitar conflito
            },
        )
        return True


# Instância global do serviço
notification_service = NotificationService()
