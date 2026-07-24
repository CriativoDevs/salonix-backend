from django.core.management.base import BaseCommand

from reports.tasks import update_daily_aggregates


class Command(BaseCommand):
    help = "Recalcula o agregado de relatórios de ontem para todos os tenants ativos (substitui o Celery Beat)."

    def handle(self, *args, **options):
        self.stdout.write("Iniciando atualização de agregados diários...")
        result = update_daily_aggregates()
        self.stdout.write(
            self.style.SUCCESS(f"Agregados atualizados para {len(result)} tenant(s).")
        )
