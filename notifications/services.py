import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional, Any
import requests
import time as pytime
import pytz
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core import signing
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException
from users.models import Tenant
from core.models import CustomerCommunicationConsent, Feedback
from core.utils.client_access import create_client_access_data
from salonix_backend.validators import sanitize_phone_number
from .models import Notification, NotificationDevice, NotificationLog
from .credit_service import credit_service
from users.services import sms_rate_limiter
from salonix_backend.error_handling import BusinessError, ErrorCodes
from prometheus_client import Counter, REGISTRY

User = get_user_model()
logger = logging.getLogger(__name__)


def _get_or_create_counter(
    name: str, documentation: str, labelnames: tuple[str, ...]
) -> Counter:
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation, labelnames)


SMS_QUOTA_USAGE_TOTAL = _get_or_create_counter(
    "sms_quota_usage_total",
    "Incrementos de cota de SMS por janela",
    ("tenant_id", "scope"),
)

SMS_RATE_LIMIT_BLOCKED_TOTAL = _get_or_create_counter(
    "sms_rate_limit_blocked_total",
    "SMS bloqueados por rate limit",
    ("tenant_id", "scope"),
)


def send_customer_pwa_invite(
    tenant: Tenant,
    customer,
    invited_by: Optional[Any] = None,
    link: Optional[str] = None,
) -> bool:
    """Envia convite do PWA Cliente por e-mail com link de acesso.

    Requisitos:
    - `FRONTEND_BASE_URL` definido nas settings para montar o link.
    - Configuração SMTP em `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`.
    - Respeita `EMAIL_DISABLE_OUTBOUND` (não envia em ambientes com bloqueio).
    """
    to_email = (getattr(customer, "email", None) or "").strip()
    if not to_email:
        return False

    if not link:
        _, _, link = create_client_access_data(tenant, customer)

    subject = f"Seu acesso ao {getattr(tenant, 'name', 'TimelyOne')}"
    # BE-MARKETING-02 (#477): acesso do cliente ao PWA não é confirmação de
    # agendamento nem cobre os outros buckets — usa o remetente de suporte.
    sender_email = (
        getattr(settings, "EMAIL_FROM_SUPPORT", "")
        or settings.EMAIL_HOST_USER
        or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost")
    )

    text_body = (
        f"Olá,\n\n"
        f"Para acessar sua área de cliente no {getattr(tenant, 'name', 'TimelyOne')}, utilize o link abaixo:\n\n"
        f"{link}\n\n"
        f"Se você não solicitou este acesso, ignore esta mensagem.\n"
    )

    html_body = f"""
    <div style="font-family: Arial, sans-serif;">
      <p>Olá,</p>
      <p>Para acessar sua área de cliente no <strong>{getattr(tenant, 'name', 'TimelyOne')}</strong>, utilize o link abaixo:</p>
      <p><a href="{link}" style="color:#2563eb;text-decoration:underline">Acessar</a></p>
      <p>Se você não solicitou este acesso, ignore esta mensagem.</p>
      <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
      <p style="font-size: 12px; color: #777;">
        {getattr(tenant, 'name', 'TimelyOne')}<br>
        Esta é uma mensagem automática.
      </p>
    </div>
    """

    message = MIMEMultipart("alternative")
    message["From"] = sender_email
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    if getattr(settings, "EMAIL_DISABLE_OUTBOUND", False):
        logger.info(
            "Outbound email disabled — PWA invite skipped",
            extra={
                "tenant_id": getattr(tenant, "id", None),
                "customer_id": getattr(customer, "id", None),
                "to": to_email,
            },
        )
        return False

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=sender_email,
            to=[to_email],
        )
        email.attach_alternative(html_body, "text/html")
        email.send(fail_silently=False)
        return True
    except Exception as e:
        logger.error(
            f"Error sending PWA invite to {to_email}: {e}",
            exc_info=True,
            extra={
                "tenant_id": getattr(tenant, "id", None),
                "customer_id": getattr(customer, "id", None),
            },
        )
        return False


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
            "email": EmailDriver(),
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
                purpose = (metadata or {}).get("purpose")
                customer_id = (metadata or {}).get("customer_id")
                if purpose == "marketing" and customer_id:
                    consent = CustomerCommunicationConsent.objects.filter(
                        tenant=tenant,
                        customer_id=customer_id,
                        channel=(
                            channel
                            if channel
                            in (
                                "sms",
                                "whatsapp",
                                "push",
                                "push_web",
                                "push_mobile",
                                "in_app",
                            )
                            else "email"
                        ),
                        purpose="marketing",
                        status="consented",
                    ).exists()
                    if not consent:
                        results[channel] = False
                        self._log_notification(
                            tenant=tenant,
                            user=user,
                            channel=channel,
                            notification_type=notification_type,
                            title=title,
                            message=message,
                            status="skipped",
                            metadata=metadata,
                        )
                        continue
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
        from users.models import CustomUser

        # Extrair IDs de agendamento e cliente do metadata se existirem
        appointment_id = (metadata or {}).get("appointment_id")
        customer_id = (metadata or {}).get("customer_id")

        # Preparar dados para criação
        log_data = {
            "tenant": tenant,
            "channel": channel,
            "notification_type": notification_type,
            "title": title,
            "message": message,
            "status": status,
            "error_message": error_message,
            "metadata": metadata or {},
            "sent_at": timezone.now() if status == "sent" else None,
        }

        # Lógica para user vs customer
        if isinstance(user, CustomUser):
            log_data["user"] = user
        elif user and hasattr(user, "pk") and not customer_id:
            # Se não é CustomUser mas tem pk, assumimos que é SalonCustomer via duck typing se o ID bater
            # Mas o ideal é usar o metadata explícito injetado nos signals
            from core.models import SalonCustomer

            if isinstance(user, SalonCustomer):
                log_data["customer"] = user

        # Priorizar IDs do metadata
        if customer_id:
            log_data["customer_id"] = customer_id
        if appointment_id:
            log_data["appointment_id"] = appointment_id

        NotificationLog.objects.create(**log_data)


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
        from users.models import CustomUser
        from core.models import SalonCustomer

        try:
            # Extrair IDs do metadata
            appointment_id = metadata.get("appointment_id")
            customer_id = metadata.get("customer_id")

            notif_data = {
                "tenant": tenant,
                "notification_type": notification_type,
                "title": title,
                "message": message,
                "metadata": metadata,
            }

            if isinstance(user, CustomUser):
                notif_data["user"] = user
            elif isinstance(user, SalonCustomer):
                notif_data["customer"] = user

            # Priorizar IDs do metadata
            if customer_id:
                notif_data["customer_id"] = customer_id
            if appointment_id:
                notif_data["appointment_id"] = appointment_id

            Notification.objects.create(**notif_data)
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
    """Driver para mobile push notifications via Expo Push Notifications Service"""

    EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

    def send(
        self,
        tenant: Tenant,
        user: Any,
        notification_type: str,
        title: str,
        message: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Enviar mobile push via Expo Push Notifications Service"""
        device = NotificationDevice.objects.filter(
            tenant=tenant, user=user, device_type="mobile", is_active=True
        ).first()

        if not device:
            logger.warning(
                f"Usuário {user.username} não tem device mobile registrado",
                extra={"tenant_id": tenant.id, "user_id": user.id},
            )
            return False

        # Montar payload para Expo
        expo_token = device.token
        data = metadata.copy() if metadata else {}

        # Adicionar deep link se houver appointment_id
        if "appointment_id" in data:
            data["route"] = f"appointment/{data['appointment_id']}"

        payload = {
            "to": expo_token,
            "title": title,
            "body": message,
            "data": data,
            "sound": "default",
            "priority": "high",
            "channelId": "default",
        }

        try:
            # Enviar requisição HTTP POST para Expo
            response = requests.post(
                self.EXPO_PUSH_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()

            result = response.json()

            # Verificar resposta do Expo
            if "data" in result and len(result["data"]) > 0:
                ticket = result["data"][0]

                if ticket.get("status") == "error":
                    error_details = ticket.get("details", {})
                    error_type = error_details.get("error")

                    # DeviceNotRegistered: token inválido/expirado
                    if error_type == "DeviceNotRegistered":
                        logger.warning(
                            f"Token Expo inválido para {user.username} - desativando device",
                            extra={
                                "tenant_id": tenant.id,
                                "user_id": user.id,
                                "device_id": device.id,
                            },
                        )
                        device.is_active = False
                        device.save()
                        return False

                    # Outros erros
                    logger.error(
                        f"Erro Expo ao enviar push para {user.username}: {error_type}",
                        extra={
                            "tenant_id": tenant.id,
                            "user_id": user.id,
                            "error": error_details,
                        },
                    )
                    return False

            # Sucesso - atualizar last_used_at
            device.last_used_at = timezone.now()
            device.save(update_fields=["last_used_at"])

            logger.info(
                f"Mobile push enviado para {user.username}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "device_id": device.id,
                    "title": title,
                },
            )
            return True

        except requests.exceptions.RequestException as e:
            logger.error(
                f"Erro HTTP ao enviar push para {user.username}: {str(e)}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "error": str(e),
                },
            )
            return False
        except Exception as e:
            logger.error(
                f"Erro inesperado ao enviar push para {user.username}: {str(e)}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "error": str(e),
                },
            )
            return False


class SMSDriver(NotificationDriverBase):
    """Driver para SMS via Twilio"""

    def send(
        self,
        tenant: Tenant,
        user: Any,
        notification_type: str,
        title: str,
        message: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Enviar SMS via Twilio com cobrança de créditos"""
        if not getattr(settings, "SMS_ENABLED", False):
            logger.info("SMS desativado globalmente (SMS_ENABLED=False)")
            return False

        if getattr(tenant, "sms_enabled", True) is False:
            logger.info(
                f"SMS desativado para o tenant {tenant.name}",
                extra={"tenant_id": tenant.id},
            )
            return False

        account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
        auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
        messaging_service_sid = getattr(settings, "TWILIO_MESSAGING_SERVICE_SID", "")
        if not account_sid or not auth_token or not messaging_service_sid:
            logger.error(
                "Credenciais Twilio ausentes ou incompletas",
                extra={"tenant_id": tenant.id},
            )
            return False

        phone_raw = (
            (metadata or {}).get("recipient_phone")
            or getattr(user, "phone_number", None)
            or ""
        ).strip()
        if not phone_raw:
            logger.warning(
                f"Usuário {getattr(user, 'username', 'cliente')} não tem telefone cadastrado",
                extra={"tenant_id": tenant.id, "user_id": getattr(user, "id", None)},
            )
            return False

        phone = sanitize_phone_number(phone_raw)
        if not phone.startswith("+"):
            logger.warning(
                f"Telefone inválido para SMS: {phone_raw}",
                extra={"tenant_id": tenant.id, "user_id": getattr(user, "id", None)},
            )
            return False

        recipient_name = (metadata or {}).get("recipient_name") or getattr(
            user, "username", getattr(user, "name", "cliente")
        )

        try:
            counts = sms_rate_limiter.check_and_increment(tenant)
            for scope, _count in counts.items():
                SMS_QUOTA_USAGE_TOTAL.labels(
                    tenant_id=str(tenant.id), scope=scope
                ).inc()
        except BusinessError as e:
            scope = (e.details or {}).get("scope", "unknown")
            SMS_RATE_LIMIT_BLOCKED_TOTAL.labels(
                tenant_id=str(tenant.id), scope=scope
            ).inc()
            logger.warning(
                f"SMS bloqueado por rate limit ({scope})",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": getattr(user, "id", None),
                    "scope": scope,
                },
            )
            return False

        charge_result = credit_service.charge_for_message(
            tenant=tenant,
            communication_type="sms",
            description=f"SMS para {recipient_name} - {notification_type}",
            user=user,
        )

        if not charge_result["success"]:
            logger.warning(
                f"Falha ao cobrar crédito de SMS para tenant {tenant.id}: {charge_result['error']}",
                extra={
                    "tenant_id": tenant.id,
                    "reason": charge_result["error"]
                }
            )
            return False

        cost_charged = charge_result["cost"]

        try:
            client = TwilioClient(account_sid, auth_token)
            twilio_message = client.messages.create(
                body=message,
                messaging_service_sid=messaging_service_sid,
                to=phone,
            )

            logger.info(
                f"SMS enviado via Twilio: {twilio_message.sid}",
                extra={
                    "tenant_id": tenant.id,
                    "recipient": phone,
                    "cost_eur": float(cost_charged),
                    "twilio_sid": twilio_message.sid,
                    "notification_type": notification_type
                }
            )
            return True
        except TwilioRestException as e:
            logger.error(
                f"Erro Twilio ao enviar SMS para {recipient_name}: {str(e)}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": getattr(user, "id", None),
                    "phone": phone,
                    "error_code": e.code,
                },
            )
            return False
        except Exception as e:
            logger.error(
                f"Erro inesperado ao enviar SMS via Twilio: {str(e)}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": getattr(user, "id", None),
                },
            )
            return False


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
        """Enviar WhatsApp com cobrança de créditos"""
        # Verificar se usuário tem telefone
        if not user.phone_number:
            logger.warning(
                f"Usuário {user.username} não tem telefone cadastrado para WhatsApp",
                extra={"tenant_id": tenant.id, "user_id": user.id},
            )
            return False

        # Determinar categoria da mensagem WhatsApp baseado no tipo de notificação
        message_category = "utility"  # Padrão para confirmações/lembretes
        if "marketing" in notification_type.lower():
            message_category = "marketing"
        elif "service" in notification_type.lower():
            message_category = "service"

        # Verificar e cobrar créditos
        charge_result = credit_service.charge_for_message(
            tenant=tenant,
            communication_type="whatsapp",
            message_category=message_category,
            description=f"WhatsApp para {user.username} - {notification_type} ({message_category})",
            user=user,
        )

        if not charge_result["success"]:
            logger.warning(
                f"WhatsApp não enviado - {charge_result['error']}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "error": charge_result["error"],
                    "cost": str(charge_result.get("cost", 0)),
                    "balance": str(charge_result.get("balance", 0)),
                    "message_category": message_category,
                },
            )
            return False

        # FASE 1: Apenas simular e logar (com cobrança real de créditos)
        logger.info(
            f"[SIMULADO] WhatsApp enviado para {user.username} - Crédito cobrado: €{charge_result['cost']}",
            extra={
                "tenant_id": tenant.id,
                "user_id": user.id,
                "phone": user.phone_number,
                "notification_message": f"{title}\n{message}",
                "message_category": message_category,
                "cost_charged": str(charge_result["cost"]),
                "new_balance": str(charge_result["new_balance"]),
                "ledger_id": charge_result["ledger_entry"].id,
            },
        )
        return True


#: notification_type -> setting name para o remetente (BE-MARKETING-02, #477).
_CANCELLATION_NOTIFICATION_TYPES = {"appointment_cancelled"}
_BOOKING_NOTIFICATION_TYPES = {
    "appointment_created",
    "appointment_completed",
    "appointment_reminder",
    "payment_received",
}


def _email_sender_for_notification_type(notification_type: str) -> str:
    """Remetente do EmailDriver por tipo de notificação (BE-MARKETING-02, #477).

    Tipos ligados a agendamento (criação/lembrete/conclusão/pagamento) usam
    EMAIL_FROM_BOOKING; cancelamento usa EMAIL_FROM_CANCELLATION; qualquer
    outro tipo (ex.: "system", usado em testes de canal) cai em
    EMAIL_FROM_SUPPORT como bucket geral de notificações transacionais.
    """
    if notification_type in _CANCELLATION_NOTIFICATION_TYPES:
        setting_name = "EMAIL_FROM_CANCELLATION"
    elif notification_type in _BOOKING_NOTIFICATION_TYPES:
        setting_name = "EMAIL_FROM_BOOKING"
    else:
        setting_name = "EMAIL_FROM_SUPPORT"
    return (
        getattr(settings, setting_name, "")
        or settings.EMAIL_HOST_USER
        or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost")
    )


class EmailDriver(NotificationDriverBase):
    """Driver para envio de e-mails via SMTP/Backend padrão do Django"""

    def send(
        self,
        tenant: Tenant,
        user: Any,
        notification_type: str,
        title: str,
        message: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Enviar e-mail transacional"""
        to_email = (getattr(user, "email", None) or "").strip()
        if not to_email:
            logger.warning(
                f"Usuário {user.username} não tem e-mail cadastrado",
                extra={"tenant_id": tenant.id, "user_id": user.id},
            )
            return False

        # Configurar remetente (por tipo de notificação — BE-MARKETING-02 #477)
        sender_email = _email_sender_for_notification_type(notification_type)

        # Montar corpo do e-mail
        # Se houver um template HTML específico no metadata, usar.
        # Caso contrário, usar um template genérico simples.
        html_content = metadata.get("html_body")
        if not html_content:
            # Template genérico simples
            html_content = f"""
            <div style="font-family: Arial, sans-serif; color: #333;">
                <h2>{title}</h2>
                <p>{message}</p>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="font-size: 12px; color: #777;">
                    {tenant.name}<br>
                    Esta é uma mensagem automática, por favor não responda.
                </p>
            </div>
            """

        try:
            email = EmailMultiAlternatives(
                subject=title,
                body=message,  # Versão texto plano
                from_email=sender_email,
                to=[to_email],
            )
            email.attach_alternative(html_content, "text/html")
            email.send()

            logger.info(
                f"E-mail enviado para {user.username}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "email": to_email,
                    "subject": title,
                },
            )
            return True

        except Exception as e:
            logger.error(
                f"Erro ao enviar e-mail: {e}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "email": to_email,
                },
            )
            return False


# Instância global do serviço
notification_service = NotificationService()


def trigger_feedback_notifications(tenant: Tenant, feedback: Feedback) -> None:
    if not tenant.can_use_advanced_notifications():
        return
    if tenant.feedback_webhook_url:
        try:
            send_feedback_webhook(tenant, feedback)
        except Exception:
            logger.exception(
                "feedback_webhook_failed",
                extra={"tenant_id": tenant.id, "feedback_id": feedback.id},
            )
    if tenant.feedback_digest_enabled:
        try:
            send_feedback_digest_email_if_due(tenant)
        except Exception:
            logger.exception("feedback_digest_failed", extra={"tenant_id": tenant.id})


def send_feedback_webhook(tenant: Tenant, feedback: Feedback) -> bool:
    url = (tenant.feedback_webhook_url or "").strip()
    if not url:
        return False
    payload: Dict[str, Any] = {
        "id": feedback.id,
        "tenant_id": tenant.id,
        "category": feedback.category,
        "rating": feedback.rating,
        "message": feedback.message,
        "is_anonymous": feedback.is_anonymous,
        "created_at": getattr(
            feedback.created_at, "isoformat", lambda: str(feedback.created_at)
        )(),
    }
    try:
        customer = getattr(feedback, "customer", None)
        if customer and not feedback.is_anonymous:
            payload["customer"] = {
                "id": getattr(customer, "id", None),
                "email": getattr(customer, "email", None),
                "name": getattr(customer, "name", None),
            }
    except Exception:
        pass
    success = False
    for i in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=5)
            if 200 <= resp.status_code < 300:
                success = True
                break
        except Exception:
            pass
        try:
            pytime.sleep(2**i)
        except Exception:
            pass
    return success


def send_feedback_digest_email_if_due(tenant: Tenant) -> bool:
    tz = pytz.timezone(tenant.timezone or "Europe/Lisbon")
    now = timezone.now().astimezone(tz)
    digest_time = tenant.feedback_digest_time
    if not digest_time:
        return False
    if tenant.feedback_digest_frequency == "weekly" and now.weekday() != 0:
        return False
    target = now.replace(
        hour=digest_time.hour, minute=digest_time.minute, second=0, microsecond=0
    )
    last = tenant.feedback_digest_last_sent
    if last is not None:
        last_local = last.astimezone(tz)
        if last_local >= target:
            return False
    if now < target:
        return False
    if tenant.feedback_digest_frequency == "daily":
        cutoff = now - timezone.timedelta(days=1)
    else:
        cutoff = now - timezone.timedelta(days=7)
    qs = Feedback.objects.filter(tenant=tenant, created_at__gte=cutoff).order_by(
        "-created_at"
    )
    items = list(qs[:50])
    if not items:
        tenant.feedback_digest_last_sent = timezone.now()
        tenant.save(update_fields=["feedback_digest_last_sent", "updated_at"])
        return False
    to_email = None
    if tenant.contact_email:
        to_email = tenant.contact_email
    else:
        try:
            from users.models import TenantStaffMember

            owner_member = (
                TenantStaffMember.objects.select_related("user")
                .filter(tenant=tenant, role=TenantStaffMember.Role.OWNER)
                .first()
            )
            to_email = getattr(getattr(owner_member, "user", None), "email", None)
        except Exception:
            to_email = None
    if not to_email:
        tenant.feedback_digest_last_sent = timezone.now()
        tenant.save(update_fields=["feedback_digest_last_sent", "updated_at"])
        return False
    subject = "Digest de feedbacks"
    # BE-MARKETING-02 (#477): "notificações de feedback da plataforma" -> support@.
    sender_email = (
        getattr(settings, "EMAIL_FROM_SUPPORT", "")
        or settings.EMAIL_HOST_USER
        or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost")
    )
    text_lines: List[str] = []
    html_lines: List[str] = []
    for f in items:
        dt = f.created_at.astimezone(tz)
        line = f"[{dt.strftime('%d/%m %H:%M')}] {f.category} • {f.rating}/5 — {f.message[:200]}"
        text_lines.append(line)
        html_lines.append(f"<li>{line}</li>")
    text_body = "\n".join(text_lines)
    html_body = f"""
    <div style=\"font-family: Arial, sans-serif;\">
      <p>Resumo de feedbacks recentes:</p>
      <ul style=\"padding-left:16px;\">{''.join(html_lines)}</ul>
    </div>
    """
    msg = EmailMultiAlternatives(subject, text_body, sender_email, [to_email])
    msg.attach_alternative(html_body, "text/html")
    if getattr(settings, "EMAIL_DISABLE_OUTBOUND", False):
        tenant.feedback_digest_last_sent = timezone.now()
        tenant.save(update_fields=["feedback_digest_last_sent", "updated_at"])
        return False
    try:
        msg.send()
        tenant.feedback_digest_last_sent = timezone.now()
        tenant.save(update_fields=["feedback_digest_last_sent", "updated_at"])
        return True
    except Exception:
        return False
