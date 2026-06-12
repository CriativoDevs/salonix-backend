"""
Management command para migrar tenants em planos bloqueados para o Basic.

BE-PLANS-01 (#481): o plano Pro foi bloqueado e o Basic absorveu suas features.
Este comando migra os tenants que ainda estão em planos bloqueados (em produção,
apenas 2 contas de teste) para o plano Basic. Tenants Founder não são alterados.

Uso:
    python manage.py migrate_tenants_to_basic            # executa a migração
    python manage.py migrate_tenants_to_basic --dry-run  # apenas lista, sem alterar

O comando é idempotente: re-execuções não alteram tenants já migrados.
"""

import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from users.models import Tenant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Migra tenants em planos bloqueados (ex: Pro) para o plano Basic "
        "(BE-PLANS-01 #481). Idempotente; suporta --dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Lista os tenants que seriam migrados sem alterar nada.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        tenants_to_migrate = Tenant.objects.filter(
            plan_tier__in=Tenant.BLOCKED_PLANS
        ).order_by("id")

        total = tenants_to_migrate.count()
        if total == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "Nenhum tenant em plano bloqueado. Nada a migrar."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"Encontrados {total} tenant(s) em planos bloqueados "
                f"({', '.join(Tenant.BLOCKED_PLANS)})."
            )
        )

        migrated = 0
        with transaction.atomic():
            for tenant in tenants_to_migrate.select_for_update():
                old_plan = tenant.plan_tier
                if dry_run:
                    self.stdout.write(
                        f"[dry-run] {tenant.slug}: {old_plan} -> {Tenant.PLAN_BASIC}"
                    )
                    continue

                tenant.plan_tier = Tenant.PLAN_BASIC
                tenant.save(update_fields=["plan_tier", "updated_at"])
                migrated += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Migrado {tenant.slug}: {old_plan} -> {Tenant.PLAN_BASIC}"
                    )
                )
                logger.info(
                    "Tenant migrated to basic plan",
                    extra={
                        "tenant_id": tenant.id,
                        "old_plan": old_plan,
                        "new_plan": Tenant.PLAN_BASIC,
                    },
                )

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"[dry-run] {total} tenant(s) seriam migrados. Nada foi alterado."
                    )
                )
                return

        self.stdout.write(
            self.style.SUCCESS(f"Concluído: {migrated} tenant(s) migrados para Basic.")
        )
