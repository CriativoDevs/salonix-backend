import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from users.models import Tenant, CommLedger, CustomUser, TenantStaffMember
from users.services import FounderService, TenantService
from django.utils import timezone
from unittest.mock import patch


@pytest.mark.django_db
class TestFounderPlan:
    def test_founder_plan_initial_credits(self):
        """Testa se o plano Founder recebe 5€ de crédito inicial."""
        tenant = Tenant.objects.create(
            name="Tenant Founder",
            slug="tenant-founder-credits",
            plan_tier=Tenant.PLAN_BASIC,
            is_founder=True,
        )

        tenant.refresh_from_db()

        assert tenant.comm_credit_eur == Decimal("5.00")

        ledger_entry = CommLedger.objects.filter(tenant=tenant).first()
        assert ledger_entry is not None
        assert ledger_entry.amount_eur == Decimal("5.00")
        assert ledger_entry.description == "Crédito inicial do plano Founder"

    def test_founder_cancellation_resets_status(self):
        """Testa se o cancelamento remove o status de Founder."""
        tenant = Tenant.objects.create(
            name="Tenant Founder Cancel",
            slug="tenant-founder-cancel",
            is_founder=True,
            is_active=True,
        )
        owner = CustomUser.objects.create_user(
            username="founder_owner",
            email="founder@example.com",
            password="password",
            tenant=tenant,
        )

        TenantService.cancel_tenant(tenant, user=owner)

        tenant.refresh_from_db()
        assert tenant.is_active is False
        assert tenant.is_founder is False

    @patch("payments.stripe_utils.get_plan_code_from_price")
    def test_founder_availability_endpoint(self, mock_get_plan):
        """Testa o endpoint de disponibilidade do Founder."""
        mock_get_plan.return_value = "founder"

        from payments.models import Subscription

        client = APIClient()
        url = reverse("founder_availability")

        # Cria alguns founders com subscriptions
        t1 = Tenant.objects.create(
            name="F1", slug="f1", is_founder=True, is_active=True
        )
        u1 = CustomUser.objects.create_user(
            username="u1", email="u1@test.com", password="pass", tenant=t1
        )
        Subscription.objects.create(
            user=u1,
            stripe_subscription_id="sub_f1",
            price_id="price_founder_1",
            status="active",
        )

        t2 = Tenant.objects.create(
            name="F2", slug="f2", is_founder=True, is_active=True
        )
        u2 = CustomUser.objects.create_user(
            username="u2", email="u2@test.com", password="pass", tenant=t2
        )
        Subscription.objects.create(
            user=u2,
            stripe_subscription_id="sub_f2",
            price_id="price_founder_2",
            status="active",
        )

        # Inativo não deve contar se não tem subscription founder
        Tenant.objects.create(name="F3", slug="f3", is_founder=True, is_active=False)
        # Não founder não conta
        Tenant.objects.create(name="NF1", slug="nf1", is_founder=False, is_active=True)

        response = client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.data

        assert data["total_limit"] == 500
        assert data["used_count"] == 2
        assert data["remaining_count"] == 498

    @patch("payments.stripe_utils.get_plan_code_from_price")
    def test_founder_limit_enforcement(self, mock_get_plan):
        """Testa se o limite é calculado corretamente."""
        mock_get_plan.return_value = "founder"

        from payments.models import Subscription

        # Mock FOUNDER_LIMIT to a small number
        with patch.object(FounderService, "FOUNDER_LIMIT", 3):
            # Check initial state
            assert FounderService.get_availability()["remaining_count"] == 3

            # Criar primeiro founder com subscription
            t1 = Tenant.objects.create(
                name="F1_lim", slug="f1-lim", is_founder=True, is_active=True
            )
            u1 = CustomUser.objects.create_user(
                username="u1_lim", email="u1_lim@test.com", password="pass", tenant=t1
            )
            Subscription.objects.create(
                user=u1,
                stripe_subscription_id="sub_f1_lim",
                price_id="price_founder_lim1",
                status="active",
            )
            assert FounderService.get_availability()["remaining_count"] == 2

            # Criar mais dois founders
            t2 = Tenant.objects.create(
                name="F2_lim", slug="f2-lim", is_founder=True, is_active=True
            )
            u2 = CustomUser.objects.create_user(
                username="u2_lim", email="u2_lim@test.com", password="pass", tenant=t2
            )
            Subscription.objects.create(
                user=u2,
                stripe_subscription_id="sub_f2_lim",
                price_id="price_founder_lim2",
                status="active",
            )

            t3 = Tenant.objects.create(
                name="F3_lim", slug="f3-lim", is_founder=True, is_active=True
            )
            u3 = CustomUser.objects.create_user(
                username="u3_lim", email="u3_lim@test.com", password="pass", tenant=t3
            )
            Subscription.objects.create(
                user=u3,
                stripe_subscription_id="sub_f3_lim",
                price_id="price_founder_lim3",
                status="active",
            )
            assert FounderService.get_availability()["remaining_count"] == 0

            # Create one more
            t4 = Tenant.objects.create(
                name="F4_lim", slug="f4-lim", is_founder=True, is_active=True
            )
            u4 = CustomUser.objects.create_user(
                username="u4_lim", email="u4_lim@test.com", password="pass", tenant=t4
            )
            Subscription.objects.create(
                user=u4,
                stripe_subscription_id="sub_f4_lim",
                price_id="price_founder_lim4",
                status="active",
            )

            availability = FounderService.get_availability()
            assert availability["used_count"] == 4
            assert availability["remaining_count"] == 0
