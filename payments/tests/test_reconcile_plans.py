import types
import pytest
from django.contrib.auth import get_user_model
from payments.models import Subscription
from users.models import Tenant
from django.core.management import call_command


class DummyPrice:
    def __init__(self, id):
        self.id = id


class DummyItem:
    def __init__(self, price_id):
        self.price = DummyPrice(price_id)


class DummyStripeSub:
    def __init__(self, price_id):
        self.items = types.SimpleNamespace(data=[DummyItem(price_id)])
        self.metadata = {"plan_code": None}
        self.status = "active"
        self.current_period_end = 1737763200  # fixed ts
        self.cancel_at_period_end = False


@pytest.mark.django_db
def test_reconcile_updates_tenant_plan(monkeypatch, settings):
    settings.STRIPE_PRICE_PRO_MONTHLY_ID = "price_pro"

    User = get_user_model()
    tenant = Tenant.objects.create(name="T1", slug="t1")
    user = User.objects.create(username="u1", tenant=tenant)

    sub = Subscription.objects.create(
        user=user,
        stripe_subscription_id="sub_123",
        status="active",
    )

    import payments.services as services

    class DummySubscriptionAPI:
        @staticmethod
        def retrieve(sub_id):
            assert sub_id == sub.stripe_subscription_id
            return DummyStripeSub("price_pro")

    monkeypatch.setattr(
        services, "stripe", types.SimpleNamespace(Subscription=DummySubscriptionAPI)
    )

    assert tenant.plan_tier == Tenant.PLAN_BASIC

    call_command("reconcile_stripe_plans", "--only", tenant.slug)

    tenant.refresh_from_db()
    assert tenant.plan_tier == Tenant.PLAN_PRO
