from django.core.management.base import BaseCommand

from vouchers.tasks import send_birthday_vouchers


class Command(BaseCommand):
    help = (
        "Gera e envia vouchers de aniversário para clientes que fazem anos hoje, "
        "em tenants com BirthdayVoucherConfig.is_active=True (substitui o Celery Beat)."
    )

    def handle(self, *args, **options):
        self.stdout.write("Iniciando envio de vouchers de aniversário...")
        result = send_birthday_vouchers()
        self.stdout.write(
            self.style.SUCCESS(
                f"Vouchers de aniversário enviados: {result['vouchers_sent']}."
            )
        )
