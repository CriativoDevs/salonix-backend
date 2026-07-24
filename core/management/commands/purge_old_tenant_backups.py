from django.core.management.base import BaseCommand

from core.tasks import purge_old_tenant_backups


class Command(BaseCommand):
    help = (
        "Remove backups de tenant antigos (BE-RGPD-01 / Art. 17) além do período de "
        "retenção (substitui o Celery Beat)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--retention-days",
            type=int,
            default=90,
            help="Dias de retenção antes de purgar um backup (default: 90).",
        )

    def handle(self, *args, **options):
        retention_days = options["retention_days"]
        self.stdout.write(
            f"Iniciando purga de backups com retenção de {retention_days} dia(s)..."
        )
        result = purge_old_tenant_backups(retention_days=retention_days)
        self.stdout.write(
            self.style.SUCCESS(
                f"Purga concluída: {result['removed']} removido(s), "
                f"{result['kept']} mantido(s)."
            )
        )
