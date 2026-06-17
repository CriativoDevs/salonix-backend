"""
BE-PLANS-02: consistência da elegibilidade de trial.

O checkout legado (views.py) já exclui subscrições `incomplete`/`incomplete_expired`
ao decidir se concede o trial. O checkout v2 (services.py) e a billing overview
contavam *qualquer* subscrição, divergindo do legado e dos testes de checkout.

Estes testes fixam o comportamento esperado: uma subscrição apenas `incomplete`
(checkout abandonado) NÃO consome o trial — o tenant continua elegível.
"""

import pytest
from django.test import override_settings

from payments.models import Subscription
from payments.services import BillingService


@pytest.mark.django_db
@override_settings(STRIPE_TRIAL_PERIOD_DAYS=14)
def test_overview_trial_eligible_with_only_incomplete_subscription(user_fixture):
    """Subscrição apenas `incomplete` não deve tornar o tenant inelegível ao trial."""
    user_fixture.tenant = user_fixture.staff_member.tenant
    user_fixture.save()

    Subscription.objects.create(
        user=user_fixture,
        stripe_subscription_id="sub_incomplete_1",
        status="incomplete",
    )

    overview = BillingService.get_billing_overview(user_fixture)

    assert overview["trial_eligible"] is True
    assert overview["trial_exhausted"] is False


@pytest.mark.django_db
@override_settings(STRIPE_TRIAL_PERIOD_DAYS=14)
def test_overview_trial_not_eligible_with_canceled_subscription(user_fixture):
    """Subscrição `canceled` (cliente que já teve trial) continua inelegível."""
    user_fixture.tenant = user_fixture.staff_member.tenant
    user_fixture.save()

    Subscription.objects.create(
        user=user_fixture,
        stripe_subscription_id="sub_canceled_1",
        status="canceled",
    )

    overview = BillingService.get_billing_overview(user_fixture)

    assert overview["trial_eligible"] is False
