from decimal import Decimal
from unittest.mock import MagicMock, patch
from django.urls import reverse
from django.test import override_settings
from rest_framework.test import APITestCase
from users.models import CustomUser, Tenant, TenantStaffMember
from payments.models import Subscription, PaymentCustomer


@override_settings(
    STRIPE_TRIAL_PERIOD_DAYS=14,
    # BE-PLANS-01 (#481): checkout de teste usa Basic (Pro bloqueado);
    # override garante o price ID independente do ambiente (CI não tem .env).
    STRIPE_PRICE_BASIC_MONTHLY_ID="price_basic_test",
)
class CheckoutTrialTestCase(APITestCase):
    """
    BE-TRIAL-04: o trial de 14 dias vive inteiramente na plataforma
    (Tenant.is_trial_expired(), BE-TRIAL-01). Sem checkout no registro, o
    primeiro checkout de qualquer tenant é sempre pós-trial (ou um pagamento
    voluntário antecipado, durante o trial). Conceder trial_period_days aqui
    duplicaria o período grátis (14 dias na plataforma + 14 dias no Stripe).
    O Stripe nunca mais concede trial próprio -- a cobrança no checkout é
    sempre imediata, independentemente do histórico de Subscription.
    """

    def setUp(self):
        # Create user and tenant
        self.user = CustomUser.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
            first_name="Test",
            last_name="User",
        )
        self.tenant = Tenant.objects.create(name="Test Salon", slug="test-salon")
        self.user.tenant = self.tenant
        self.user.save()

        # Create staff member (owner)
        self.staff = TenantStaffMember.objects.create(
            tenant=self.tenant,
            user=self.user,
            role=TenantStaffMember.Role.OWNER,
            status=TenantStaffMember.Status.ACTIVE,
        )

        self.client.force_authenticate(user=self.user)
        self.url = reverse("payments:create_checkout_session")

        # Mock stripe
        self.patcher = patch("payments.views.stripe_utils.get_stripe")
        self.mock_get_stripe = self.patcher.start()
        self.mock_stripe = MagicMock()
        self.mock_get_stripe.return_value = self.mock_stripe

        # Mock session create
        self.mock_stripe.checkout.Session.create.return_value = MagicMock(
            url="http://checkout.url"
        )

        # Mock customer create
        self.mock_stripe.Customer.create.return_value = {"id": "cus_test_123"}

        # BE-MARKETING-03: simula vagas Founder esgotadas para não bloquear
        # os testes de trial, que usam plan="basic" sem relação com Founder.
        self.founder_patcher = patch(
            "users.services.FounderService.get_availability",
            return_value={"total_limit": 500, "used_count": 500, "remaining_count": 0},
        )
        self.founder_patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.founder_patcher.stop()

    def _assert_no_trial_granted(self):
        _, kwargs = self.mock_stripe.checkout.Session.create.call_args
        subscription_data = kwargs.get("subscription_data", {})
        self.assertNotIn("trial_period_days", subscription_data)
        self.assertFalse(subscription_data.get("trial_from_plan", True))

    def test_new_customer_without_subscription_history_gets_no_trial(self):
        """Primeiro checkout de todos (sem checkout no registro) -- cobrança
        imediata, sem trial_period_days do Stripe."""
        response = self.client.post(self.url, {"plan": "basic"})
        self.assertEqual(response.status_code, 200)
        self._assert_no_trial_granted()

    def test_active_subscription_no_trial(self):
        Subscription.objects.create(
            user=self.user, stripe_subscription_id="sub_active", status="active"
        )

        response = self.client.post(self.url, {"plan": "basic"})
        self.assertEqual(response.status_code, 200)
        self._assert_no_trial_granted()

    def test_canceled_subscription_no_trial(self):
        Subscription.objects.create(
            user=self.user, stripe_subscription_id="sub_canceled", status="canceled"
        )

        response = self.client.post(self.url, {"plan": "basic"})
        self.assertEqual(response.status_code, 200)
        self._assert_no_trial_granted()

    def test_incomplete_subscription_no_trial(self):
        """Checkout abandonado (incomplete) também não deve gerar trial --
        antes era o único caso que ainda concedia; agora nenhum caso concede."""
        Subscription.objects.create(
            user=self.user, stripe_subscription_id="sub_incomplete", status="incomplete"
        )

        response = self.client.post(self.url, {"plan": "basic"})
        self.assertEqual(response.status_code, 200)
        self._assert_no_trial_granted()
