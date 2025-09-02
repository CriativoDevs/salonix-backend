"""
Signals para envio automático de notificações baseado em eventos de agendamento.
"""

import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from core.models import Appointment
from .services import notification_service

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Appointment)
def send_appointment_notifications(sender, instance, created, **kwargs):
    """
    Enviar notificações quando um agendamento é criado ou atualizado.

    Eventos que geram notificações:
    - Criação de agendamento
    - Mudança de status para cancelled
    - Mudança de status para completed
    - Mudança de status para paid
    """

    # Skip se não tiver tenant ou cliente
    if not instance.tenant or not instance.client:
        return

    # Determinar tipo de notificação e canais baseado no evento
    notification_type = None
    title = None
    message = None
    channels = ["in_app"]  # Sempre enviar in-app

    if created:
        # Novo agendamento criado
        notification_type = "appointment_created"
        title = "Novo Agendamento Confirmado"
        # Garantir que start_time é datetime para formatar
        start_time = instance.slot.start_time
        if hasattr(start_time, "strftime"):
            formatted_time = start_time.strftime("%d/%m/%Y às %H:%M")
        else:
            formatted_time = str(start_time)  # Fallback para testes
        message = f"Seu agendamento de {instance.service.name} foi confirmado para {formatted_time}"

        # Para novos agendamentos, enviar também push
        channels.extend(["push_web", "push_mobile"])

    else:
        # Agendamento atualizado - verificar mudanças de status
        # Precisamos comparar com o estado anterior
        try:
            previous_instance = Appointment.objects.get(pk=instance.pk)

            # Se status mudou
            if (
                hasattr(instance, "_previous_status")
                and instance._previous_status != instance.status
            ):
                if instance.status == "cancelled":
                    notification_type = "appointment_cancelled"
                    title = "Agendamento Cancelado"
                    message = (
                        f"Seu agendamento de {instance.service.name} foi cancelado"
                    )
                    channels.extend(["push_web", "push_mobile", "sms"])

                elif instance.status == "completed":
                    notification_type = "appointment_completed"
                    title = "Serviço Concluído"
                    message = f"Seu serviço de {instance.service.name} foi concluído. Obrigado!"

                elif instance.status == "paid":
                    notification_type = "payment_received"
                    title = "Pagamento Confirmado"
                    message = f"Pagamento do serviço {instance.service.name} confirmado. Obrigado!"

        except Appointment.DoesNotExist:
            # Caso não encontre instância anterior, ignorar
            pass

    # Se não há tipo de notificação, não enviar
    if not notification_type:
        return

    # Preparar metadata
    metadata = {
        "appointment_id": instance.id,
        "service_name": instance.service.name,
        "professional_name": (
            instance.professional.name if instance.professional else None
        ),
        "appointment_date": (
            instance.slot.start_time.isoformat()
            if instance.slot and hasattr(instance.slot.start_time, "isoformat")
            else str(instance.slot.start_time) if instance.slot else None
        ),
        "status": instance.status,
    }

    try:
        # Enviar notificação
        results = notification_service.send_notification(
            tenant=instance.tenant,
            user=instance.client,
            channels=channels,
            notification_type=notification_type,
            title=title,
            message=message,
            metadata=metadata,
        )

        logger.info(
            f"Notificações de agendamento enviadas: {notification_type}",
            extra={
                "tenant_id": instance.tenant.id,
                "user_id": instance.client.id,
                "appointment_id": instance.id,
                "notification_type": notification_type,
                "channels": channels,
                "results": results,
            },
        )

    except Exception as e:
        logger.error(
            f"Erro ao enviar notificações de agendamento: {e}",
            extra={
                "tenant_id": instance.tenant.id,
                "user_id": instance.client.id,
                "appointment_id": instance.id,
                "notification_type": notification_type,
                "error": str(e),
            },
        )


@receiver(pre_save, sender=Appointment)
def track_appointment_status_change(sender, instance, **kwargs):
    """
    Rastrear mudanças de status do agendamento para usar no post_save.
    """
    if instance.pk:
        try:
            previous = Appointment.objects.get(pk=instance.pk)
            instance._previous_status = previous.status
        except Appointment.DoesNotExist:
            instance._previous_status = None
    else:
        instance._previous_status = None
