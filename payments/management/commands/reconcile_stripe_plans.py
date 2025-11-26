from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from typing import Optional

from users.models import Tenant
from payments.services import SubscriptionService


class Command(BaseCommand):
    help = "Reconcilia plan_tier dos tenants com o estado atual no Stripe"

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            dest="only_slug",
            default=None,
            help="Slug do tenant para reconciliação única",
        )

    def _get_any_user(self, tenant: Tenant) -> Optional[object]:
        User = get_user_model()
        return (
            User.objects.filter(tenant=tenant).order_by("id").first()
        )

    def handle(self, *args, **options):
        only_slug = options.get("only_slug")
        qs = Tenant.objects.filter(is_active=True)
        if only_slug:
            qs = qs.filter(slug=only_slug)

        updated = 0
        checked = 0

        for tenant in qs.iterator():
            checked += 1
            user = self._get_any_user(tenant)
            if not user:
                self.stdout.write(
                    self.style.WARNING(
                        f"[skip] tenant={tenant.slug} sem usuários para reconciliação"
                    )
                )
                continue

            current = SubscriptionService.get_current_subscription(user) or {}
            plan_code = current.get("plan_code")
            if plan_code and plan_code != tenant.plan_tier:
                old = tenant.plan_tier
                tenant.plan_tier = plan_code
                tenant.save(update_fields=["plan_tier", "updated_at"])
                updated += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[updated] tenant={tenant.slug} {old} -> {plan_code}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.NOTICE(
                        f"[ok] tenant={tenant.slug} plano atual={tenant.plan_tier}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Reconciliação concluída: {updated} atualizados, {checked} verificados"
            )
        )
