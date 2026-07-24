from django.core.management.base import BaseCommand

from reports.tasks import cleanup_expired_export_jobs


class Command(BaseCommand):
    help = "Remove ficheiros e registos de exportação de relatórios expirados (substitui o Celery Beat)."

    def handle(self, *args, **options):
        self.stdout.write("Iniciando limpeza de exportações expiradas...")
        result = cleanup_expired_export_jobs()
        self.stdout.write(
            self.style.SUCCESS(
                f"Limpeza concluída: {result['deleted_jobs']} job(s) removido(s), "
                f"{result['deleted_files']} ficheiro(s) removido(s)."
            )
        )
