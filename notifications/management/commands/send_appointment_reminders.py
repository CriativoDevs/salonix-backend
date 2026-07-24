from django.core.management.base import BaseCommand

from notifications.tasks import send_appointment_reminders


class Command(BaseCommand):
    help = "Envia lembretes de agendamentos que ocorrerão em ~24h (substitui o Celery Beat)."

    def handle(self, *args, **options):
        self.stdout.write("Iniciando envio de lembretes de agendamento...")
        result = send_appointment_reminders()
        self.stdout.write(
            self.style.SUCCESS(f"Lembretes processados: {result}")
        )
