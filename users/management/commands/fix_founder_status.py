"""
Management command para corrigir status de is_founder inconsistente.

Limpa is_founder=True de tenants que mudaram para outros planos
mas cujo webhook não foi processado (ex: em modo MOCK).
"""

from django.core.management.base import BaseCommand
from users.models import Tenant


class Command(BaseCommand):
    help = "Corrige status is_founder inconsistente baseado em subscriptions históricas"

    def handle(self, *args, **options):
        try:
            from payments.models import Subscription
            from payments.stripe_utils import get_plan_code_from_price
        except ImportError:
            self.stdout.write(
                self.style.ERROR(
                    "Módulo payments não disponível. Certifique-se de que está instalado."
                )
            )
            return

        # Busca tenants que tem is_founder=True
        founder_tenants = Tenant.objects.filter(is_founder=True)
        self.stdout.write(
            self.style.WARNING(
                f"Encontrados {founder_tenants.count()} tenants com is_founder=True"
            )
        )

        fixed_count = 0

        for tenant in founder_tenants:
            # Busca subscriptions do tenant
            subs = Subscription.objects.filter(user__tenant=tenant).order_by(
                "-created_at"
            )

            if not subs.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"  {tenant.slug}: Sem subscriptions, mantendo is_founder=True"
                    )
                )
                continue

            # Pega a subscription mais recente
            latest_sub = subs.first()
            latest_plan = None

            if latest_sub and latest_sub.price_id:
                latest_plan = get_plan_code_from_price(latest_sub.price_id)

            status = latest_sub.status if latest_sub else "N/A"
            self.stdout.write(
                f"  {tenant.slug}: Última subscription: plan={latest_plan}, status={status}"
            )

            # Se a subscription mais recente NÃO é founder, limpa o flag
            if latest_plan and latest_plan != "founder":
                tenant.is_founder = False
                # Atualiza plan_tier se necessário
                if tenant.plan_tier != latest_plan:
                    tenant.plan_tier = latest_plan
                    tenant.save(update_fields=["is_founder", "plan_tier", "updated_at"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"    ✓ Corrigido: is_founder=False, plan_tier={latest_plan}"
                        )
                    )
                else:
                    tenant.save(update_fields=["is_founder", "updated_at"])
                    self.stdout.write(
                        self.style.SUCCESS(f"    ✓ Corrigido: is_founder=False")
                    )
                fixed_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"\n✅ Concluído! {fixed_count} tenant(s) corrigido(s).")
        )
