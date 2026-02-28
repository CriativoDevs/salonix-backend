import logging
from celery import shared_task
from django.conf import settings
from core.email_utils import send_staff_invite_email

logger = logging.getLogger(__name__)


@shared_task(name="users.tasks.send_staff_invite_task")
def send_staff_invite_task(to_email, accept_url, salon_name, inviter_name):
    """
    Task assíncrona para enviar e-mail de convite para membros da equipe.
    Evita que o timeout do worker ocorra durante o envio síncrono de e-mail.
    """
    try:
        logger.info(f"Iniciando envio de convite assíncrono para {to_email}")
        ok = send_staff_invite_email(
            to_email=to_email,
            accept_url=accept_url,
            salon_name=salon_name,
            inviter_name=inviter_name,
        )
        if ok:
            logger.info(f"Convite assíncrono enviado com sucesso para {to_email}")
        else:
            logger.error(f"Falha no envio do convite assíncrono para {to_email}")
        return ok
    except Exception as e:
        logger.error(
            f"Erro inesperado ao enviar convite assíncrono para {to_email}: {str(e)}",
            exc_info=True,
        )
        return False
