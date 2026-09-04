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


@shared_task(name="notifications.send_marketing_campaign", bind=True, max_retries=3)
def send_marketing_campaign_task(self, campaign_id: int, customer_ids: list[int]):
    """
    Envia (assincronamente) os emails de uma campanha de marketing já
    aprovada/contabilizada (BE-MARKETING-04, #522).

    A view (`MarketingCampaignListCreateView.create`) já resolveu, de forma
    síncrona e atômica, quem entra na campanha (elegibilidade, cota grátis
    e crédito de comunicação já foram decididos e cobrados antes de
    disparar esta task) — aqui apenas disparamos o email de fato para cada
    `customer_id` recebido, reaproveitando `send_marketing_email` (que já
    inclui o rodapé com link de unsubscribe).
    """
    from .models import EmailMarketingCampaign
    from core.models import SalonCustomer
    from core.email_utils import send_marketing_email

    try:
        campaign = EmailMarketingCampaign.objects.select_related("tenant").get(
            id=campaign_id
        )
    except EmailMarketingCampaign.DoesNotExist:
        logger.error(
            "marketing_campaign_not_found", extra={"campaign_id": campaign_id}
        )
        return

    customers = SalonCustomer.objects.filter(
        tenant=campaign.tenant, id__in=customer_ids
    )

    sent = 0
    for customer in customers:
        if not customer.email:
            continue
        try:
            send_marketing_email(
                to_email=customer.email,
                client_name=customer.name,
                subject=campaign.subject,
                body_text=campaign.body,
                tenant_id=campaign.tenant_id,
                customer_id=customer.id,
                salon_name=campaign.tenant.name,
                reply_to=campaign.reply_to or None,
            )
            sent += 1
        except Exception:
            logger.exception(
                "marketing_campaign_email_failed",
                extra={"campaign_id": campaign_id, "customer_id": customer.id},
            )

    campaign.status = EmailMarketingCampaign.Status.COMPLETED
    campaign.completed_at = timezone.now()
    campaign.save(update_fields=["status", "completed_at"])

    logger.info(
        "marketing_campaign_sent",
        extra={
            "campaign_id": campaign_id,
            "tenant_id": campaign.tenant_id,
            "emails_sent": sent,
            "requested": len(customer_ids),
        },
    )
    return sent
