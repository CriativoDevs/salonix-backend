import logging

from celery import shared_task
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
