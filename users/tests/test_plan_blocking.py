"""
Testes do BE-PLANS-01 (#481): bloqueio do plano Pro e absorção das suas
features pelos planos Basic e Founder.
"""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from payments.services import SubscriptionService
from users.models import CustomUser, Tenant, TenantStaffMember


@pytest.fixture
def basic_tenant(db):
    return Tenant.objects.create(
        name="Salon Basic", slug="salon-basic", plan_tier=Tenant.PLAN_BASIC
    )


@pytest.fixture
def founder_tenant(db):
    return Tenant.objects.create(
        name="Salon Founder",
        slug="salon-founder",
        plan_tier=Tenant.PLAN_FOUNDER,
        is_founder=True,
    )


@pytest.fixture
def pro_tenant(db):
    return Tenant.objects.create(
        name="Salon Pro", slug="salon-pro", plan_tier=Tenant.PLAN_PRO
    )


def _make_owner(tenant, username):
    user = CustomUser.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="pass",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=user, role=TenantStaffMember.Role.OWNER
    )
    return user


class TestPlanBlocked:
    def test_pro_is_blocked(self):
        assert Tenant.is_plan_blocked(Tenant.PLAN_PRO) is True

    def test_basic_and_founder_are_not_blocked(self):
        assert Tenant.is_plan_blocked(Tenant.PLAN_BASIC) is False
        assert Tenant.is_plan_blocked(Tenant.PLAN_FOUNDER) is False

    def test_pro_absent_from_available_plans(self, db):
        plans = SubscriptionService.get_available_plans()
        plan_codes = [p["plan_code"] for p in plans]
        assert "pro" not in plan_codes
        assert "basic" in plan_codes

    @pytest.mark.django_db
    @patch("payments.views.stripe_utils.get_or_create_customer")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("payments.views.stripe_utils.get_stripe")
    def test_checkout_with_pro_rejected(
        self, mock_get_stripe, mock_get_price, mock_get_customer, basic_tenant
    ):
        """
        Plano Pro continua inalcançável via checkout. Na view legada, o
        plano é sempre derivado do tenant (nunca do payload do cliente) —
        um tenant Basic que envie plan="pro" simplesmente faz checkout
        como Basic, o payload é ignorado. Na view v2, o serializer ainda
        valida e rejeita "pro" explicitamente com 400.
        """
        owner = _make_owner(basic_tenant, "owner-basic")
        client = APIClient()
        client.force_authenticate(user=owner)

        mock_get_customer.return_value = "cus_123"
        mock_get_price.return_value = "price_basic_123"
        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.url = "http://checkout.url"
        mock_stripe.checkout.Session.create.return_value = mock_session
        mock_get_stripe.return_value = mock_stripe

        # View legada de checkout: payload "pro" é ignorado, deriva "basic"
        resp = client.post(
            "/api/payments/stripe/create-checkout-session/",
            {"plan": "pro"},
            format="json",
        )
        assert resp.status_code == 200
        mock_get_price.assert_called_with("basic", interval="monthly")

        # View v2 (serializer com validate_plan) continua a rejeitar "pro"
        resp_v2 = client.post(
            "/api/payments/stripe/v2/checkout/", {"plan": "pro"}, format="json"
        )
        assert resp_v2.status_code == 400

    @pytest.mark.django_db
    def test_promotional_transition_never_converts_to_blocked_plan(
        self, basic_tenant
    ):
        from django.utils import timezone
        from datetime import timedelta

        basic_tenant.billing_mode = Tenant.BILLING_MODE_PROMOTIONAL
        basic_tenant.promotional_expires_at = timezone.now() - timedelta(days=1)
        basic_tenant.promotional_converts_to_plan = Tenant.PLAN_PRO
        basic_tenant.save()

        assert basic_tenant.apply_promotional_transition() is True
        basic_tenant.refresh_from_db()
        assert basic_tenant.plan_tier == Tenant.PLAN_BASIC


class TestBasicAbsorbsProFeatures:
    @pytest.mark.django_db
    def test_basic_has_ex_pro_features(self, basic_tenant):
        assert basic_tenant.can_use_advanced_reports() is True
        assert basic_tenant.can_use_white_label() is True
        assert basic_tenant.can_use_native_admin() is True
        assert basic_tenant.can_use_native_client() is True

    @pytest.mark.django_db
    def test_founder_has_ex_pro_features(self, founder_tenant):
        assert founder_tenant.can_use_advanced_reports() is True
        assert founder_tenant.can_use_white_label() is True
        assert founder_tenant.can_use_native_admin() is True
        assert founder_tenant.can_use_native_client() is True

    @pytest.mark.django_db
    def test_basic_retention_is_90_days(self, basic_tenant):
        assert basic_tenant.get_retention_days() == 90

    @pytest.mark.django_db
    def test_basic_advanced_notifications_by_plan(self, basic_tenant):
        basic_tenant.sms_enabled = True
        basic_tenant.save(update_fields=["sms_enabled"])
        assert basic_tenant.can_use_advanced_notifications() is True

    @pytest.mark.django_db
    def test_custom_domain_still_requires_flag(self, basic_tenant):
        assert basic_tenant.can_use_custom_domain() is False
        basic_tenant.custom_domain_enabled = True
        basic_tenant.save(update_fields=["custom_domain_enabled"])
        assert basic_tenant.can_use_custom_domain() is True

    @pytest.mark.django_db
    def test_basic_owner_can_enable_auto_renewal(self, basic_tenant):
        owner = _make_owner(basic_tenant, "owner-renew")
        client = APIClient()
        client.force_authenticate(user=owner)

        resp = client.patch(
            "/api/payments/stripe/settings/", {"auto_renewal": True}, format="json"
        )
        assert resp.status_code == 200
        assert resp.data["auto_renewal"] is True

    @pytest.mark.django_db
    def test_basic_prices_and_credits_unchanged(self, db):
        basic = SubscriptionService.AVAILABLE_PLANS["basic"]
        assert str(basic["price_monthly"]) == "29.00"
        assert str(basic["credits_included"]) == "5.00"


class TestOpsBlockedPlan:
    def test_ops_serializer_rejects_blocked_plan(self, db):
        from ops.serializers import OpsTenantPlanUpdateSerializer

        serializer = OpsTenantPlanUpdateSerializer(data={"plan_tier": "pro"})
        assert serializer.is_valid() is False
        assert "plan_tier" in serializer.errors

    def test_ops_serializer_accepts_basic(self, db):
        from ops.serializers import OpsTenantPlanUpdateSerializer

        serializer = OpsTenantPlanUpdateSerializer(data={"plan_tier": "basic"})
        assert serializer.is_valid() is True


class TestMigrateTenantsToBasicCommand:
    @pytest.mark.django_db
    def test_migrates_pro_tenant_to_basic(self, pro_tenant, founder_tenant):
        out = StringIO()
        call_command("migrate_tenants_to_basic", stdout=out)

        pro_tenant.refresh_from_db()
        founder_tenant.refresh_from_db()
        assert pro_tenant.plan_tier == Tenant.PLAN_BASIC
        assert founder_tenant.plan_tier == Tenant.PLAN_FOUNDER
        assert "salon-pro" in out.getvalue()

    @pytest.mark.django_db
    def test_idempotent(self, pro_tenant):
        call_command("migrate_tenants_to_basic", stdout=StringIO())
        out = StringIO()
        call_command("migrate_tenants_to_basic", stdout=out)

        pro_tenant.refresh_from_db()
        assert pro_tenant.plan_tier == Tenant.PLAN_BASIC
        assert "Nada a migrar" in out.getvalue()

    @pytest.mark.django_db
    def test_dry_run_does_not_change(self, pro_tenant):
        out = StringIO()
        call_command("migrate_tenants_to_basic", "--dry-run", stdout=out)

        pro_tenant.refresh_from_db()
        assert pro_tenant.plan_tier == Tenant.PLAN_PRO
        assert "dry-run" in out.getvalue()
