from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from payments.services import SubscriptionService
from users.models import CommLedger, Tenant


class Command(BaseCommand):
    help = (
        "Repõe o crédito de comunicação de cada tenant pagante até ao teto incluído "
        "no seu plano (€2 Founder / €5 Basic) — nunca soma, nunca reduz quem está "
        "acima do teto (ex.: comprou crédito extra). Roda mensalmente via Cron Job."
    )

    def handle(self, *args, **options):
        self.stdout.write("Iniciando renovação mensal de crédito de comunicação...")

        renewed = 0
        skipped_trial = 0
        skipped_unpaid = 0
        skipped_already_at_cap = 0

        for tenant in Tenant.objects.filter(is_active=True).iterator():
            if tenant.is_in_trial():
                skipped_trial += 1
                continue

            if not tenant.has_active_paid_subscription():
                skipped_unpaid += 1
                continue

            assigned_plan = "founder" if tenant.is_founder else tenant.plan_tier
            plans = SubscriptionService.get_available_plans(tenant=tenant)
            plan_info = next(
                (p for p in plans if p["plan_code"] == assigned_plan), None
            )
            if not plan_info:
                continue

            credits_included = Decimal(str(plan_info.get("credits_included", 0)))
            if credits_included <= 0:
                continue

            balance_before = tenant.comm_credit_eur
            new_balance = max(balance_before, credits_included)

            if new_balance <= balance_before:
                skipped_already_at_cap += 1
                continue

            with transaction.atomic():
                Tenant.objects.filter(pk=tenant.pk).update(comm_credit_eur=new_balance)
                CommLedger.objects.create(
                    tenant=tenant,
                    transaction_type=CommLedger.TransactionType.BONUS,
                    amount_eur=new_balance - balance_before,
                    balance_before=balance_before,
                    balance_after=new_balance,
                    status=CommLedger.Status.COMPLETED,
                    description=f"Renovação mensal do crédito do plano {plan_info.get('name', assigned_plan)}",
                )
            renewed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Renovação concluída: {renewed} renovado(s), "
                f"{skipped_trial} em trial, {skipped_unpaid} sem subscrição paga, "
                f"{skipped_already_at_cap} já no teto ou acima."
            )
        )
