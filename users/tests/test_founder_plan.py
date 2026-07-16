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
        """Testa se o plano Founder recebe 2€ de crédito inicial."""
        tenant = Tenant.objects.create(
            name="Tenant Founder",
            slug="tenant-founder-credits",
            plan_tier=Tenant.PLAN_BASIC,
            is_founder=True,
        )

        tenant.refresh_from_db()

        assert tenant.comm_credit_eur == Decimal("2.00")

        ledger_entry = CommLedger.objects.filter(tenant=tenant).first()
        assert ledger_entry is not None
        assert ledger_entry.amount_eur == Decimal("2.00")
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


class TestFounderIsBasicBlocked:
    @pytest.mark.django_db
    def test_blocked_when_vacancies_remain_and_tenant_has_no_history(self):
        tenant = Tenant.objects.create(
            name="Fresh Tenant", slug="fresh-tenant", is_founder=False
        )
        with patch.object(FounderService, "FOUNDER_LIMIT", 500):
            assert FounderService.is_basic_blocked(tenant=tenant) is True

    @pytest.mark.django_db
    def test_not_blocked_when_tenant_is_active_founder(self):
        tenant = Tenant.objects.create(
            name="Founder Tenant", slug="founder-tenant", is_founder=True
        )
        assert FounderService.is_basic_blocked(tenant=tenant) is False

    @pytest.mark.django_db
    @patch("payments.stripe_utils.get_plan_code_from_price")
    def test_not_blocked_when_tenant_left_founder_before(self, mock_get_plan):
        mock_get_plan.return_value = "founder"
        from payments.models import Subscription

        tenant = Tenant.objects.create(
            name="Ex Founder", slug="ex-founder", is_founder=False
        )
        owner = CustomUser.objects.create_user(
            username="ex_founder_owner",
            email="exfounder@example.com",
            password="pass",
            tenant=tenant,
        )
        Subscription.objects.create(
            user=owner,
            stripe_subscription_id="sub_ex_founder",
            price_id="price_founder_old",
            status="canceled",
        )
        assert FounderService.is_basic_blocked(tenant=tenant) is False

    @pytest.mark.django_db
    def test_not_blocked_when_founder_vacancies_exhausted(self):
        tenant = Tenant.objects.create(
            name="Fresh Tenant 2", slug="fresh-tenant-2", is_founder=False
        )
        with patch.object(FounderService, "FOUNDER_LIMIT", 0):
            assert FounderService.is_basic_blocked(tenant=tenant) is False

    @pytest.mark.django_db
    def test_blocked_with_no_tenant_and_vacancies_remain(self):
        with patch.object(FounderService, "FOUNDER_LIMIT", 500):
            assert FounderService.is_basic_blocked(tenant=None) is True

    @pytest.mark.django_db
    def test_not_blocked_with_no_tenant_and_vacancies_exhausted(self):
        with patch.object(FounderService, "FOUNDER_LIMIT", 0):
            assert FounderService.is_basic_blocked(tenant=None) is False


@pytest.mark.django_db
class TestRegistrationBasicBlockedByFounder:
    def test_registration_blocked_when_plan_omitted_and_founder_available(self):
        from django.urls import reverse
        from rest_framework.test import APIClient

        client = APIClient()
        url = reverse("register")
        response = client.post(
            url,
            {
                "username": "newowner",
                "email": "newowner@example.com",
                "password": "StrongPass123",
            },
        )
        assert response.status_code == 400

    def test_registration_allowed_with_explicit_founder_plan(self):
        from django.urls import reverse
        from rest_framework.test import APIClient

        client = APIClient()
        url = reverse("register")
        response = client.post(
            url,
            {
                "username": "newfounder",
                "email": "newfounder@example.com",
                "password": "StrongPass123",
                "plan": "founder",
            },
        )
        assert response.status_code == 201

    def test_registration_allowed_with_basic_when_founder_exhausted(self):
        from unittest.mock import patch
        from django.urls import reverse
        from rest_framework.test import APIClient

        client = APIClient()
        url = reverse("register")
        with patch(
            "users.services.FounderService.get_availability",
            return_value={"total_limit": 500, "used_count": 500, "remaining_count": 0},
        ):
            response = client.post(
                url,
                {
                    "username": "newbasic",
                    "email": "newbasic@example.com",
                    "password": "StrongPass123",
                    "plan": "basic",
                },
            )
        assert response.status_code == 201


@pytest.mark.django_db
class TestFounderAvailabilityEndpointTenantAware:
    def test_anonymous_request_returns_global_availability_only(self):
        from django.urls import reverse
        from rest_framework.test import APIClient

        client = APIClient()
        url = reverse("founder_availability")
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["remaining_count"] == 500

    def test_authenticated_ex_founder_sees_zero_remaining(self):
        from django.urls import reverse
        from rest_framework.test import APIClient
        from payments.models import Subscription

        tenant = Tenant.objects.create(
            name="Ex Founder Avail", slug="ex-founder-avail", is_founder=False
        )
        owner = CustomUser.objects.create_user(
            username="ex_founder_avail_owner",
            email="exfounderavail@example.com",
            password="pass",
            tenant=tenant,
        )
        with patch("payments.stripe_utils.get_plan_code_from_price") as mock_get_plan:
            mock_get_plan.return_value = "founder"
            Subscription.objects.create(
                user=owner,
                stripe_subscription_id="sub_ex_founder_avail",
                price_id="price_founder_old_avail",
                status="canceled",
            )

            client = APIClient()
            client.force_authenticate(user=owner)
            url = reverse("founder_availability")
            response = client.get(url)

        assert response.status_code == 200
        assert response.data["remaining_count"] == 0

    def test_authenticated_active_founder_tenant_still_sees_remaining(self):
        from django.urls import reverse
        from rest_framework.test import APIClient

        tenant = Tenant.objects.create(
            name="Active Founder Avail", slug="active-founder-avail", is_founder=True
        )
        owner = CustomUser.objects.create_user(
            username="active_founder_avail_owner",
            email="activefounderavail@example.com",
            password="pass",
            tenant=tenant,
        )

        client = APIClient()
        client.force_authenticate(user=owner)
        url = reverse("founder_availability")
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["remaining_count"] == 500

    def test_authenticated_fresh_tenant_sees_global_remaining(self):
        from django.urls import reverse
        from rest_framework.test import APIClient

        tenant = Tenant.objects.create(
            name="Fresh Avail", slug="fresh-avail", is_founder=False
        )
        owner = CustomUser.objects.create_user(
            username="fresh_avail_owner",
            email="freshavail@example.com",
            password="pass",
            tenant=tenant,
        )

        client = APIClient()
        client.force_authenticate(user=owner)
        url = reverse("founder_availability")
        response = client.get(url)

        assert response.status_code == 200
        assert response.data["remaining_count"] == 500
