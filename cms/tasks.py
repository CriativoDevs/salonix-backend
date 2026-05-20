import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="cms.publish_scheduled_pages")
def publish_scheduled_pages():
    """
    Task agendada (cron a cada 5 minutos).

    Busca paginas com status=draft e scheduled_publish_at <= now()
    e as publica automaticamente.
    """
    from cms.models import PublicPage

    now = timezone.now()
    pages = PublicPage.objects.filter(
        status=PublicPage.STATUS_DRAFT,
        scheduled_publish_at__lte=now,
        scheduled_publish_at__isnull=False,
    )

    count = pages.count()
    logger.info(f"[CMS] Publicando {count} pagina(s) agendada(s)")

    published = 0
    errors = 0

    for page in pages:
        try:
            page.publish()
            published += 1
            logger.info(f"[CMS] Pagina publicada: {page.slug}")
        except Exception as e:
            errors += 1
            logger.error(f"[CMS] Erro ao publicar pagina {page.slug}: {e}")

    logger.info(f"[CMS] Concluido: {published} publicadas, {errors} erros")
    return {"published": published, "errors": errors}
