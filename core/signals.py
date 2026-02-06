from django.db import transaction
from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver
from django.utils import timezone
import logging

from core.models import Appointment
from reports.utils.cache import debounce_invalidate_many

logger = logging.getLogger(__name__)

PREFIXES = (
    "reports:overview:",
    "reports:top_services:",
    "reports:revenue:",
)


def _schedule_invalidation():
    # Coalesce invalidações por 2s (process-local). Seguro para bursts.
    debounce_invalidate_many(PREFIXES, wait_seconds=2.0)


@receiver(post_save, sender=Appointment, dispatch_uid="reports_cache_on_appt_save")
def reports_cache_on_appt_save(sender, instance, **kwargs):
    transaction.on_commit(_schedule_invalidation)


@receiver(post_delete, sender=Appointment, dispatch_uid="reports_cache_on_appt_delete")
def reports_cache_on_appt_delete(sender, instance, **kwargs):
    transaction.on_commit(_schedule_invalidation)


# ============================================================================
# PUSH NOTIFICATIONS - Appointment Events
# ============================================================================


@receiver(post_save, sender=Appointment, dispatch_uid="push_appointment_created")
def push_appointment_created(sender, instance, created, **kwargs):
    """
    Envia push notification quando appointment é criado.
    """
    if not created:
        return  # Apenas novos appointments

    # Evitar import circular
    from notifications.services import notification_service

    appointment = instance

    # Enviar notificação para o cliente
    if appointment.client and appointment.tenant:
        title = "Agendamento Confirmado"

        # start_time pode ser string em alguns testes
        start_time = appointment.slot.start_time
        if isinstance(start_time, str):
            from django.utils.dateparse import parse_datetime

            start_time = parse_datetime(start_time)

        message = (
            f"Seu agendamento de {appointment.service.name} "
            f"com {appointment.professional.name} foi confirmado para "
            f"{start_time.strftime('%d/%m/%Y às %H:%M') if start_time else 'breve'}."
        )

        metadata = {
            "appointment_id": appointment.id,
            "service_name": appointment.service.name,
            "professional_name": appointment.professional.name,
            "start_time": (
                start_time.isoformat()
                if start_time and not isinstance(start_time, str)
                else str(start_time) if start_time else ""
            ),
        }

        def _send_push():
            try:
                notification_service.send(
                    tenant=appointment.tenant,
                    user=appointment.client,
                    notification_type="appointment_created",
                    title=title,
                    message=message,
                    channels=["push_mobile", "in_app"],
                    metadata=metadata,
                )
                logger.info(
                    f"Push enviado para appointment {appointment.id}",
                    extra={
                        "tenant_id": appointment.tenant.id,
                        "user_id": appointment.client.id,
                        "appointment_id": appointment.id,
                    },
                )
            except Exception as e:
                logger.error(
                    f"Erro ao enviar push para appointment {appointment.id}: {str(e)}",
                    extra={
                        "tenant_id": appointment.tenant.id,
                        "user_id": appointment.client.id,
                        "appointment_id": appointment.id,
                        "error": str(e),
                    },
                )

        transaction.on_commit(_send_push)


@receiver(post_delete, sender=Appointment, dispatch_uid="push_appointment_cancelled")
def push_appointment_cancelled(sender, instance, **kwargs):
    """
    Envia push notification quando appointment é cancelado/deletado.
    """
    # Evitar import circular
    from notifications.services import notification_service

    appointment = instance

    # Enviar notificação para o cliente
    if appointment.client and appointment.tenant:
        title = "Agendamento Cancelado"

        # start_time pode ser string em alguns testes
        start_time = appointment.slot.start_time
        if isinstance(start_time, str):
            from django.utils.dateparse import parse_datetime

            start_time = parse_datetime(start_time)

        message = (
            f"Seu agendamento de {appointment.service.name} "
            f"com {appointment.professional.name} "
            f"em {start_time.strftime('%d/%m/%Y às %H:%M') if start_time else 'breve'} foi cancelado."
        )

        # start_time pode ser string em alguns testes
        start_time = appointment.slot.start_time
        if isinstance(start_time, str):
            from django.utils.dateparse import parse_datetime

            start_time = parse_datetime(start_time)

        metadata = {
            "appointment_id": appointment.id,
            "service_name": appointment.service.name,
            "professional_name": appointment.professional.name,
            "start_time": (
                start_time.isoformat()
                if start_time and not isinstance(start_time, str)
                else str(start_time) if start_time else ""
            ),
            "cancelled_at": timezone.now().isoformat(),
        }

        try:
            notification_service.send_notification(
                tenant=appointment.tenant,
                user=appointment.client,
                notification_type="appointment_cancelled",
                title=title,
                message=message,
                channels=["push_mobile", "in_app"],
                metadata=metadata,
            )
            logger.info(
                f"Push de cancelamento enviado para appointment {appointment.id}",
                extra={
                    "tenant_id": appointment.tenant.id,
                    "user_id": appointment.client.id,
                    "appointment_id": appointment.id,
                },
            )
        except Exception as e:
            logger.error(
                f"Erro ao enviar push de cancelamento para appointment {appointment.id}: {str(e)}",
                extra={
                    "tenant_id": appointment.tenant.id,
                    "user_id": appointment.client.id,
                    "appointment_id": appointment.id,
                    "error": str(e),
                },
            )
