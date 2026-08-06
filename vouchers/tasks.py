import logging
from datetime import timedelta

from celery import shared_task
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.email_utils import send_voucher_email

logger = logging.getLogger(__name__)


@shared_task(name="vouchers.send_voucher_email", bind=True, max_retries=3)
def send_voucher_email_task(self, client_voucher_id: int):
    """
    Envia (assincronamente) o e-mail de voucher a um cliente e regista
    `sent_at` (BE-VOUCHER-04, #473).

    A view (`VoucherViewSet.send_email`) já valida que o cliente tem e-mail
    e que o voucher está atribuído antes de disparar esta task — aqui apenas
    re-checamos por segurança, já que o estado pode ter mudado entre o
    disparo e a execução assíncrona.
    """
    from vouchers.models import ClientVoucher

    try:
        client_voucher = ClientVoucher.objects.select_related(
            "voucher", "voucher__service", "client", "tenant"
        ).get(id=client_voucher_id)
    except ClientVoucher.DoesNotExist:
        logger.error(
            "voucher_email_client_voucher_not_found",
            extra={"client_voucher_id": client_voucher_id},
        )
        return

    client = client_voucher.client
    voucher = client_voucher.voucher

    if not client.email:
        logger.warning(
            "voucher_email_client_missing_email",
            extra={"client_voucher_id": client_voucher_id, "client_id": client.id},
        )
        return

    try:
        send_voucher_email(
            to_email=client.email,
            client_name=client.name,
            voucher_code=voucher.code,
            voucher_type=voucher.type,
            voucher_value=voucher.value,
            service_name=voucher.service.name if voucher.service_id else None,
            valid_until=voucher.valid_until,
            salon_name=client_voucher.tenant.name,
        )
        client_voucher.sent_at = timezone.now()
        client_voucher.save(update_fields=["sent_at"])

        logger.info(
            "voucher_email_sent",
            extra={
                "client_voucher_id": client_voucher_id,
                "voucher_id": voucher.id,
                "client_id": client.id,
                "tenant_id": client_voucher.tenant_id,
            },
        )
    except Exception as exc:
        logger.error(
            "voucher_email_failed",
            extra={"client_voucher_id": client_voucher_id, "error": str(exc)},
            exc_info=True,
        )
        raise self.retry(exc=exc, countdown=60)


@shared_task(name="vouchers.send_birthday_vouchers")
def send_birthday_vouchers() -> dict:
    """Task periódica (BE-VOUCHER-05, #474): gera e envia automaticamente um
    voucher de aniversário para cada cliente que faz anos hoje, usando o
    template `BirthdayVoucherConfig` marcado como `is_selected=True` em
    cada tenant (nenhum selecionado = feature desligada nesse tenant).

    Chamada de forma síncrona pelo management command
    `send_birthday_vouchers` (mesmo padrão de substituição do Celery Beat
    por Cron Jobs nativos do Railway já usado por
    `notifications.tasks.send_appointment_reminders` e
    `reports.tasks.update_daily_aggregates` — ver BE-INFRA-01, #502).

    Idempotência: `BirthdayVoucherLog` tem uma constraint única
    `(tenant, client, sent_date)` — se o job correr mais de uma vez no
    mesmo dia, a segunda tentativa de criar o log falha com
    `IntegrityError` e o cliente é simplesmente ignorado (nenhum voucher
    duplicado, nenhum e-mail duplicado).
    """
    from core.models import SalonCustomer
    from vouchers.models import BirthdayVoucherConfig, BirthdayVoucherLog, ClientVoucher, Voucher

    today = timezone.localdate()
    vouchers_sent = 0

    configs = BirthdayVoucherConfig.objects.filter(is_selected=True).select_related(
        "tenant", "service"
    )

    for config in configs:
        # Escopado sempre ao tenant do config — nunca cruzar clientes de
        # tenants diferentes no mesmo lote.
        birthday_clients = SalonCustomer.objects.filter(
            tenant=config.tenant,
            is_active=True,
            birthday__month=today.month,
            birthday__day=today.day,
        )

        for client in birthday_clients:
            try:
                with transaction.atomic():
                    log = BirthdayVoucherLog.objects.create(
                        tenant=config.tenant, client=client, sent_date=today
                    )
            except IntegrityError:
                # Já processado hoje (execução anterior do job) — idempotente.
                continue

            voucher = Voucher.objects.create(
                tenant=config.tenant,
                type=config.voucher_type,
                value=config.voucher_value,
                service=config.service,
                valid_until=today + timedelta(days=config.validity_days),
                notes="Voucher de aniversário gerado automaticamente.",
            )
            client_voucher = ClientVoucher.objects.create(
                tenant=config.tenant, voucher=voucher, client=client
            )
            log.client_voucher = client_voucher
            log.save(update_fields=["client_voucher"])

            send_voucher_email_task.delay(client_voucher.id)
            vouchers_sent += 1

            logger.info(
                "birthday_voucher_generated",
                extra={
                    "tenant_id": config.tenant_id,
                    "client_id": client.id,
                    "voucher_id": voucher.id,
                    "client_voucher_id": client_voucher.id,
                },
            )

    return {"vouchers_sent": vouchers_sent}
