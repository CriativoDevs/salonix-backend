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
            is_founder=True
        )
        
        tenant.refresh_from_db()
        
        assert tenant.comm_credit_eur == Decimal("5.00")
        
        ledger_entry = CommLedger.objects.filter(tenant=tenant).first()
        assert ledger_entry is not None
        assert ledger_entry.amount_eur == Decimal("5.00")
        assert ledger_entry.description == "Crédito inicial Plano Founder"

    def test_founder_cancellation_resets_status(self):
        """Testa se o cancelamento remove o status de Founder."""
        tenant = Tenant.objects.create(
            name="Tenant Founder Cancel",
            slug="tenant-founder-cancel",
            is_founder=True,
            is_active=True
        )
        owner = CustomUser.objects.create_user(
            username="founder_owner",
            email="founder@example.com",
            password="password",
            tenant=tenant
        )

        TenantService.cancel_tenant(tenant, user=owner)
        
        tenant.refresh_from_db()
        assert tenant.is_active is False
        assert tenant.is_founder is False

    def test_founder_availability_endpoint(self):
        """Testa o endpoint de disponibilidade do Founder."""
        client = APIClient()
        url = reverse("founder_availability")
        
        # Cria alguns founders
        Tenant.objects.create(name="F1", slug="f1", is_founder=True, is_active=True)
        Tenant.objects.create(name="F2", slug="f2", is_founder=True, is_active=True)
        # Inativo não conta
        Tenant.objects.create(name="F3", slug="f3", is_founder=True, is_active=False)
        # Não founder não conta
        Tenant.objects.create(name="NF1", slug="nf1", is_founder=False, is_active=True)

        response = client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        
        assert data["total_limit"] == 500
        assert data["used_count"] == 2
        assert data["remaining_count"] == 498

    def test_founder_limit_enforcement(self):
        """Testa se o limite é calculado corretamente."""
        # Mock FOUNDER_LIMIT to a small number
        with patch.object(FounderService, 'FOUNDER_LIMIT', 3):
            # Check initial state (assuming DB is clean or has the ones from previous tests if not isolated?
            # pytest-django handles DB isolation per test function usually.
            
            assert FounderService.get_availability()["remaining_count"] == 3
            
            Tenant.objects.create(name="F1_lim", slug="f1-lim", is_founder=True, is_active=True)
            assert FounderService.get_availability()["remaining_count"] == 2
            
            Tenant.objects.create(name="F2_lim", slug="f2-lim", is_founder=True, is_active=True)
            Tenant.objects.create(name="F3_lim", slug="f3-lim", is_founder=True, is_active=True)
            assert FounderService.get_availability()["remaining_count"] == 0
            
            # Create one more
            Tenant.objects.create(name="F4_lim", slug="f4-lim", is_founder=True, is_active=True)
            
            status = FounderService.get_availability()
            assert status["used_count"] == 4
            assert status["remaining_count"] == 0
