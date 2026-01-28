import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "salonix_backend.settings")
django.setup()

from users.models import Tenant
from payments.models import Subscription
from payments.stripe_utils import get_plan_code_from_price

print("Procurando tenants que tiveram Founder e mudaram de plano...\n")

all_subs = Subscription.objects.all()
tenant_plans = {}

for sub in all_subs:
    if not sub.price_id or not sub.user or not sub.user.tenant:
        continue

    tenant_slug = sub.user.tenant.slug
    plan = get_plan_code_from_price(sub.price_id)

    if tenant_slug not in tenant_plans:
        tenant_plans[tenant_slug] = []
    tenant_plans[tenant_slug].append((plan, sub.status, sub.created_at))

# Encontra tenants que tiveram founder
for slug, plans in tenant_plans.items():
    has_founder = any(p[0] == "founder" for p in plans)
    has_other = any(p[0] != "founder" for p in plans)

    if has_founder:
        tenant = Tenant.objects.get(slug=slug)
        latest_plan = sorted(plans, key=lambda x: x[2], reverse=True)[0]

        print(f"{slug}:")
        print(f"  is_founder atual: {tenant.is_founder}")
        print(f"  plan_tier: {tenant.plan_tier}")
        print(f"  Total subs: {len(plans)}")
        print(f"  Última sub: plan={latest_plan[0]}, status={latest_plan[1]}")

        if has_other and latest_plan[0] != "founder":
            print(f"  ⚠️  EX-FOUNDER! (teve Founder mas agora é {latest_plan[0]})")

        print()
