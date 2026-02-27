import logging
from datetime import timedelta
from django.utils import timezone
from celery import shared_task
from core.models import Appointment
from .services import notification_service

logger = logging.getLogger(__name__)

@shared_task(name="notifications.tasks.send_appointment_reminders")
def send_appointment_reminders():
    """
    Task periódica para enviar lembretes de agendamentos.
    Procura agendamentos que ocorrerão em aproximadamente 24 horas.
    """
    now = timezone.now()
    # Janela de 24h: entre 23h e 25h a partir de agora para garantir que não perdemos nenhum
    # dependendo da frequência de execução da task (ex: a cada hora)
    start_window = now + timedelta(hours=23)
    end_window = now + timedelta(hours=25)

    appointments = Appointment.objects.filter(
        status="scheduled",
        slot__start_time__range=(start_window, end_window)
    ).select_related('tenant', 'client', 'customer', 'service', 'slot')

    count = 0
    for appt in appointments:
        # Verificar se já enviamos lembrete para este agendamento recentemente
        # Isso evita duplicidade se a janela de busca for maior que o intervalo da task
        from .models import NotificationLog
        already_sent = NotificationLog.objects.filter(
            appointment=appt,
            notification_type="appointment_reminder",
            status="sent"
        ).exists()

        if already_sent:
            continue

        recipient_customer = getattr(appt, "customer", None)
        recipient_client = getattr(appt, "client", None)
        
        # Preferir customer se disponível
        recipient = recipient_customer if recipient_customer else recipient_client
        
        if not recipient:
            continue

        # Preparar dados para o driver
        recipient_name = (
            getattr(recipient_customer, "name", None)
            if recipient_customer
            else getattr(recipient_client, "username", "Cliente")
        )
        
        start_time = appt.slot.start_time
        formatted_time = start_time.strftime("%H:%M")
        formatted_date = start_time.strftime("%d/%m/%Y")
        tenant_name = appt.tenant.name

        title = "Lembrete de Agendamento"
        message = f"[{tenant_name}] Olá {recipient_name}! Lembramos o seu agendamento de {appt.service.name} para amanhã, {formatted_date} às {formatted_time}. Até lá!"

        # Enviar canais: SMS e In-App (e Push se configurado no futuro)
        channels = ["sms", "in_app"]
        
        metadata = {
            "appointment_id": appt.id,
            "customer_id": recipient_customer.id if recipient_customer else None,
            "service_name": appt.service.name,
            "reminder_type": "24h"
        }

        # Adicionar dados de telefone explicitamente para o SMSDriver
        recipient_phone = (
            getattr(recipient_customer, "phone_number", None)
            if recipient_customer
            else getattr(recipient_client, "phone_number", None)
        )
        if recipient_phone:
            metadata["recipient_phone"] = recipient_phone
            metadata["recipient_name"] = recipient_name

        try:
            notification_service.send_notification(
                tenant=appt.tenant,
                user=recipient,
                channels=channels,
                notification_type="appointment_reminder",
                title=title,
                message=message,
                metadata=metadata
            )
            count += 1
        except Exception as e:
            logger.error(f"Erro ao enviar lembrete para agendamento {appt.id}: {e}")

    return f"Lembretes enviados: {count}"
