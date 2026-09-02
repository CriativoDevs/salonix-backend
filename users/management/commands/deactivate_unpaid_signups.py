from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import Tenant


class Command(BaseCommand):
    help = (
        "Desativa tenants em billing_mode=Stripe que nunca concluíram o "
        "checkout (sem trial em curso e sem subscrição paga confirmada) "
        "após o período de carência do cadastro. Sem isso, um tenant que "
        "abandona o checkout mantém acesso completo indefinidamente, já "
        "que is_founder/is_active/billing_mode já vêm setados no cadastro, "
        "antes de qualquer pagamento. Roda diariamente via Cron Job."
    )

    def handle(self, *args, **options):
        grace_days = settings.STRIPE_TRIAL_PERIOD_DAYS or 14
        cutoff = timezone.now() - timezone.timedelta(days=grace_days)

        deactivated = []
        skipped_in_grace = 0
        skipped_trial = 0
        skipped_paid = 0

        tenants = Tenant.objects.filter(
            is_active=True,
            billing_mode=Tenant.BILLING_MODE_STRIPE,
        ).iterator()

        for tenant in tenants:
            if tenant.created_at > cutoff:
                skipped_in_grace += 1
                continue

            if tenant.is_in_trial():
                skipped_trial += 1
                continue

            if tenant.has_active_paid_subscription():
                skipped_paid += 1
                continue

            tenant.is_active = False
            tenant.save(update_fields=["is_active", "updated_at"])
            deactivated.append(tenant.slug)

        if deactivated:
            self.stdout.write(
                self.style.WARNING(
                    f"Desativados {len(deactivated)} tenant(s) sem pagamento "
                    f"confirmado após {grace_days} dias: {', '.join(deactivated)}"
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Concluído: {len(deactivated)} desativado(s), "
                f"{skipped_in_grace} ainda em carência, "
                f"{skipped_trial} em trial, "
                f"{skipped_paid} com pagamento confirmado."
            )
        )
