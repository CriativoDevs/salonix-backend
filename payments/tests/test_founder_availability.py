"""
Testes para validar a lógica de disponibilidade do plano Founder.
"""

from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from users.models import Tenant, TenantStaffMember
from payments.models import Subscription
from payments.services import SubscriptionService
from users.services import FounderService

User = get_user_model()


class FounderAvailabilityTest(TestCase):
    """Testes para validar que tenants que já tiveram Founder não conseguem voltar."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(  # type: ignore[attr-defined]
            username="owner", email="owner@example.com", password="password"
        )
        self.tenant = Tenant.objects.create(
            name="Test Salon", slug="test-salon", is_founder=False
        )
        self.user.tenant = self.tenant
        self.user.save()

        self.staff = TenantStaffMember.objects.create(
            user=self.user,
            tenant=self.tenant,
            role=TenantStaffMember.Role.OWNER,
            status=TenantStaffMember.Status.ACTIVE,
        )

        self.client.force_authenticate(user=self.user)

    @patch("payments.stripe_utils.get_plan_code_from_price")
    def test_founder_tenant_cannot_re_apply_after_cancellation(self, mock_get_plan):
        """
        Testa que um tenant que já teve Founder não consegue aplicar de novo.
        Simula: Tenant teve Founder -> Cancelou -> Tenta voltar -> Deve ser negado
        """
        mock_get_plan.return_value = "founder"

        # Criar subscription fake no histórico
        Subscription.objects.create(
            user=self.user,
            stripe_subscription_id="sub_old_founder",
            price_id="price_founder_123",
            status="canceled",
        )

        # Tenant não é mais founder
        self.tenant.is_founder = False
        self.tenant.save()

        # Tentar fazer checkout de Founder novamente deve falhar
        can_assign = FounderService.can_assign_founder(tenant=self.tenant)
        self.assertFalse(
            can_assign,
            "Tenant que já teve Founder não deve poder re-aplicar",
        )

    @patch("payments.stripe_utils.get_plan_code_from_price")
    def test_founder_plan_marked_unavailable_when_ineligible(self, mock_get_plan):
        """
        Testa que o plano Founder é marcado como indisponível (is_available=False)
        quando o tenant já teve e saiu.
        """
        mock_get_plan.return_value = "founder"

        # Setup: Tenant com histórico de Founder
        Subscription.objects.create(
            user=self.user,
            stripe_subscription_id="sub_old_founder",
            price_id="price_founder_123",
            status="canceled",
        )

        # Tenant não é mais founder
        self.tenant.is_founder = False
        self.tenant.save()

        # Obter planos disponíveis
        plans = SubscriptionService.get_available_plans(
            current_plan=None, tenant=self.tenant
        )

        # Verificar que Founder não está na lista ou está marcado como indisponível
        founder_plan = next((p for p in plans if p["plan_code"] == "founder"), None)

        if founder_plan:
            # Se estiver na lista, deve estar marcado como indisponível
            self.assertFalse(
                founder_plan["is_available"],
                "Founder deve estar marcado como indisponível para este tenant",
            )

    @patch("payments.stripe_utils.get_plan_code_from_price")
    def test_founder_plan_available_for_new_tenant(self, mock_get_plan):
        """
        Testa que um novo tenant (sem histórico Founder) consegue ver Founder como disponível.
        """
        mock_get_plan.return_value = None  # Sem histórico

        # Obter planos disponíveis para novo tenant
        plans = SubscriptionService.get_available_plans(
            current_plan=None, tenant=self.tenant
        )

        # Founder deve estar disponível
        founder_plan = next((p for p in plans if p["plan_code"] == "founder"), None)

        self.assertIsNotNone(
            founder_plan,
            "Founder deve estar na lista para novo tenant",
        )
        assert founder_plan is not None  # Type narrowing for type checker
        self.assertTrue(
            founder_plan["is_available"],
            "Founder deve estar marcado como disponível para novo tenant",
        )

    def test_active_founder_tenant_keeps_elegibility(self):
        """
        Testa que um tenant que é atualmente Founder mantém elegibilidade.
        """
        # Tenant atual É founder
        self.tenant.is_founder = True
        self.tenant.save()

        can_assign = FounderService.can_assign_founder(tenant=self.tenant)
        self.assertTrue(
            can_assign,
            "Tenant que é Founder atualmente deve manter elegibilidade",
        )
