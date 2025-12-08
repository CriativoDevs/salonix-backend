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
from users.models import Tenant
from core.models import CustomerCommunicationConsent, Feedback
from .models import Notification, NotificationDevice, NotificationLog
from .credit_service import credit_service

User = get_user_model()
logger = logging.getLogger(__name__)


def send_customer_pwa_invite(
    tenant: Tenant, customer, invited_by: Optional[Any] = None
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

    payload = {
        "tenant_id": getattr(tenant, "id", None),
        "customer_id": getattr(customer, "id", None),
        "ts": int(timezone.now().timestamp()),
        # uso único será validado no accept
        "jti": signing.TimestampSigner().sign_object({"r": timezone.now().timestamp()})[
            :16
        ],
    }
    token = signing.dumps(payload, salt="CLIENT_PWA_INVITE_SALT")
    base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
    slug = getattr(tenant, "slug", "").strip().lower()
    tenant_qs = f"tenant={slug}" if slug else ""
    sep = "&" if tenant_qs else ""
    link = f"{base}/client/access?{tenant_qs}{sep}token={token}"

    subject = "Seu acesso ao Salonix"
    sender_email = settings.EMAIL_HOST_USER or getattr(
        settings, "DEFAULT_FROM_EMAIL", "noreply@localhost"
    )

    text_body = (
        f"Olá,\n\n"
        f"Para acessar sua área de cliente, utilize o link abaixo:\n\n"
        f"{link}\n\n"
        f"Se você não solicitou este acesso, ignore esta mensagem.\n"
    )

    html_body = f"""
    <div style="font-family: Arial, sans-serif;">
      <p>Olá,</p>
      <p>Para acessar sua área de cliente, utilize o link abaixo:</p>
      <p><a href="{link}" style="background:#2563eb;color:#fff;padding:10px 14px;border-radius:6px;text-decoration:none">Acessar</a></p>
      <p>Se você não solicitou este acesso, ignore esta mensagem.</p>
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
        if getattr(settings, "EMAIL_HOST", "").strip():
            with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
                if getattr(settings, "EMAIL_USE_TLS", False):
                    server.starttls()
                if settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD:
                    server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
                server.send_message(message)
        else:
            email = EmailMultiAlternatives(subject, text_body, sender_email, [to_email])
            email.attach_alternative(html_body, "text/html")
            email.send()
        logger.info(
            "PWA invite email sent",
            extra={
                "tenant_id": getattr(tenant, "id", None),
                "tenant_slug": getattr(tenant, "slug", None),
                "customer_id": getattr(customer, "id", None),
                "customer_email": to_email,
                "invited_by": getattr(invited_by, "id", None),
            },
        )
        return True
    except Exception:
        logger.exception(
            "PWA invite email failed",
            extra={
                "tenant_id": getattr(tenant, "id", None),
                "customer_id": getattr(customer, "id", None),
                "customer_email": to_email,
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
        """Enviar SMS com cobrança de créditos"""
        # Verificar se usuário tem telefone
        if not user.phone_number:
            logger.warning(
                f"Usuário {user.username} não tem telefone cadastrado",
                extra={"tenant_id": tenant.id, "user_id": user.id},
            )
            return False

        # Verificar e cobrar créditos
        charge_result = credit_service.charge_for_message(
            tenant=tenant,
            communication_type="sms",
            description=f"SMS para {user.username} - {notification_type}",
            user=user,
        )

        if not charge_result["success"]:
            logger.warning(
                f"SMS não enviado - {charge_result['error']}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "error": charge_result["error"],
                    "cost": str(charge_result.get("cost", 0)),
                    "balance": str(charge_result.get("balance", 0)),
                },
            )
            return False

        # FASE 1: Apenas simular e logar (com cobrança real de créditos)
        logger.info(
            f"[SIMULADO] SMS enviado para {user.username} - Crédito cobrado: €{charge_result['cost']}",
            extra={
                "tenant_id": tenant.id,
                "user_id": user.id,
                "phone": user.phone_number,
                "notification_message": message,
                "cost_charged": str(charge_result["cost"]),
                "new_balance": str(charge_result["new_balance"]),
                "ledger_id": charge_result["ledger_entry"].id,
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
    sender_email = settings.EMAIL_HOST_USER or getattr(
        settings, "DEFAULT_FROM_EMAIL", "noreply@localhost"
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
