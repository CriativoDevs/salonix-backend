"""
Management command para verificar e deletar tenants com cancelamento expirado.

Uso:
    python manage.py check_expired_tenants [--dry-run]

Este comando pode ser agendado via cron:
    # Todos os dias às 3:00 AM
    0 3 * * * cd /path/to/project && python manage.py check_expired_tenants >> /var/log/celery-check-expired.log 2>&1
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.tasks import check_expired_cancellations


class Command(BaseCommand):
    help = (
        "Verifica tenants com cancelamento expirado e dispara hard delete. "
        "Usado em ambientes sem Celery Beat (PythonAnywhere)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas lista tenants expirados sem deletar",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        self.stdout.write(
            self.style.WARNING(
                f"[{timezone.now()}] Iniciando verificação de cancelamentos expirados"
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.NOTICE("MODO DRY-RUN: Nenhuma deleção será executada")
            )
            # TODO: implementar listagem sem executar
            from users.models import Tenant

            now = timezone.now()
            expired = Tenant.objects.filter(
                status=Tenant.STATUS_CANCELLED,
                scheduled_deletion_at__lte=now,
            ).values_list("id", "slug", "scheduled_deletion_at")

            if not expired:
                self.stdout.write(
                    self.style.SUCCESS("✅ Nenhum tenant expirado encontrado")
                )
                return

            self.stdout.write(
                self.style.WARNING(f"Encontrados {len(expired)} tenants expirados:")
            )
            for tenant_id, slug, deletion_date in expired:
                self.stdout.write(
                    f"  - ID {tenant_id} | {slug} | " f"Expirado em: {deletion_date}"
                )
        else:
            # Executa a task Celery
            result = check_expired_cancellations()

            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ Verificação concluída: {result['dispatched']} tenants "
                    f"despachados para deleção"
                )
            )

            if result["errors"] > 0:
                self.stdout.write(
                    self.style.ERROR(f"❌ {result['errors']} erros encontrados")
                )
