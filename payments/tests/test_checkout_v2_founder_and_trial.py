"""
BE-TRIAL-05: SubscriptionService.create_checkout_session (checkout v2).

Dois problemas encontrados durante a investigação de BE-TRIAL-04 (#545), no
mesmo endpoint dead-code (v2/checkout, sem uso hoje em FE/MOB):

1. "founder" era rejeitado só por não existir em AVAILABLE_PLANS (ValueError
   de chave ausente) -- um efeito colateral, não uma validação de negócio.
   Se "founder" for adicionado a AVAILABLE_PLANS no futuro, o bloqueio some
   silenciosamente. Precisa de checagem explícita via
   FounderService.can_assign_founder, como o v1 já faz.
2. Mesmo bug de "double trial" corrigido no v1 (BE-TRIAL-04): concedia
   trial_period_days do Stripe sempre que não havia Subscription anterior --
   duplicando o trial de 14 dias que já vive na plataforma (BE-TRIAL-01).
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from payments.models import Subscription
from payments.services import SubscriptionService
from users.models import CustomUser, Tenant, TenantStaffMember


@pytest.fixture
def founder_tenant(db):
    tenant = Tenant.objects.create(
        name="Founder Co", slug="founder-co-v2", is_founder=True
    )
    user = CustomUser.objects.create_user(
        username="founder_owner_v2",
        email="founder_owner_v2@example.com",
        password="pass",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return tenant, user


@pytest.fixture
def basic_tenant(db):
    tenant = Tenant.objects.create(
        name="Basic Co", slug="basic-co-v2", is_founder=False
    )
    user = CustomUser.objects.create_user(
        username="basic_owner_v2",
        email="basic_owner_v2@example.com",
        password="pass",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return tenant, user


@pytest.mark.django_db
def test_founder_checkout_rejected_explicitly_for_non_founder_tenant(basic_tenant):
    _, user = basic_tenant

    with pytest.raises(ValueError, match="Founder"):
        SubscriptionService.create_checkout_session(
            user=user,
            plan="founder",
            success_url="https://x/success",
            cancel_url="https://x/cancel",
        )


@pytest.mark.django_db
@override_settings(STRIPE_PRICE_FOUNDER_MONTHLY_ID="price_founder_test")
def test_founder_checkout_allowed_for_eligible_founder_tenant(founder_tenant):
    _, user = founder_tenant

    with patch("payments.services.get_or_create_customer", return_value="cus_1"), patch(
        "payments.services.stripe"
    ) as mock_stripe:
        mock_stripe.checkout.Session.create.return_value = MagicMock(
            id="sess_1", url="https://checkout.stripe.com/sess_1"
        )
        result = SubscriptionService.create_checkout_session(
            user=user,
            plan="founder",
            success_url="https://x/success",
            cancel_url="https://x/cancel",
        )

    assert result["checkout_url"] == "https://checkout.stripe.com/sess_1"


@pytest.mark.django_db
@override_settings(
    STRIPE_TRIAL_PERIOD_DAYS=14,
    STRIPE_PRICE_BASIC_MONTHLY_ID="price_basic_test",
)
def test_checkout_v2_never_grants_stripe_trial(basic_tenant):
    """BE-TRIAL-05: mesmo fix do BE-TRIAL-04, mas no caminho v2."""
    _, user = basic_tenant

    with patch("payments.services.get_or_create_customer", return_value="cus_2"), patch(
        "payments.services.stripe"
    ) as mock_stripe:
        mock_stripe.checkout.Session.create.return_value = MagicMock(
            id="sess_2", url="https://checkout.stripe.com/sess_2"
        )
        SubscriptionService.create_checkout_session(
            user=user,
            plan="basic",
            success_url="https://x/success",
            cancel_url="https://x/cancel",
        )

        _, kwargs = mock_stripe.checkout.Session.create.call_args
        subscription_data = kwargs.get("subscription_data", {})

    assert "trial_period_days" not in subscription_data
    assert subscription_data.get("trial_from_plan") is False


@pytest.mark.django_db
@override_settings(
    STRIPE_TRIAL_PERIOD_DAYS=14,
    STRIPE_PRICE_BASIC_MONTHLY_ID="price_basic_test",
)
def test_checkout_v2_never_grants_stripe_trial_with_incomplete_history(basic_tenant):
    """Antes, uma Subscription só `incomplete` (checkout abandonado) ainda
    concedia trial -- agora nenhum caso concede."""
    _, user = basic_tenant
    Subscription.objects.create(
        user=user, stripe_subscription_id="sub_incomplete_v2", status="incomplete"
    )

    with patch("payments.services.get_or_create_customer", return_value="cus_3"), patch(
        "payments.services.stripe"
    ) as mock_stripe:
        mock_stripe.checkout.Session.create.return_value = MagicMock(
            id="sess_3", url="https://checkout.stripe.com/sess_3"
        )
        SubscriptionService.create_checkout_session(
            user=user,
            plan="basic",
            success_url="https://x/success",
            cancel_url="https://x/cancel",
        )

        _, kwargs = mock_stripe.checkout.Session.create.call_args
        subscription_data = kwargs.get("subscription_data", {})

    assert "trial_period_days" not in subscription_data
    assert subscription_data.get("trial_from_plan") is False
