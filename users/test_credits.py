from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status

from .models import Tenant
from .services import CreditService

User = get_user_model()


class CreditServiceTestCase(TestCase):
    """Testes para o serviço de créditos."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
            plan_tier="standard",
            comm_credit_eur=Decimal("10.00"),
            comm_extra_allowed=True,
            comm_auto_renew=True,
        )
        self.user = User.objects.create_user(
            username="methoduser",
            email="method@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.credit_service = CreditService(self.tenant)

    def test_get_credit_balance(self):
        """Testa obtenção do saldo de créditos."""
        balance = self.credit_service.get_credit_balance()
        self.assertEqual(balance, Decimal("10.00"))

    def test_consume_credits_success(self):
        """Testa consumo de créditos com sucesso."""
        transaction = self.credit_service.consume_credits(
            amount=Decimal("5.00"), description="Test consumption", created_by=self.user
        )

        self.assertEqual(transaction.transaction_type, "consumption")
        self.assertEqual(transaction.amount_eur, Decimal("5.00"))
        self.assertEqual(transaction.balance_before, Decimal("10.00"))
        self.assertEqual(transaction.balance_after, Decimal("5.00"))
        self.assertEqual(transaction.status, "completed")

        # Verifica se o saldo foi atualizado
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, Decimal("5.00"))

    def test_consume_credits_insufficient_balance(self):
        """Testa consumo de créditos com saldo insuficiente."""
        with self.assertRaises(ValueError) as context:
            self.credit_service.consume_credits(
                amount=Decimal("15.00"),
                description="Test consumption",
                created_by=self.user,
            )

        self.assertIn("Saldo insuficiente", str(context.exception))

    def test_add_credits(self):
        """Testa adição de créditos."""
        transaction = self.credit_service.add_credits(
            amount=Decimal("5.00"),
            transaction_type="purchase",
            description="Test purchase",
            created_by=self.user,
        )

        self.assertEqual(transaction.transaction_type, "purchase")
        self.assertEqual(transaction.amount_eur, Decimal("5.00"))
        self.assertEqual(transaction.balance_before, Decimal("10.00"))
        self.assertEqual(transaction.balance_after, Decimal("15.00"))

        # Verifica se o saldo foi atualizado
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, Decimal("15.00"))

    def test_can_consume_credits(self):
        """Testa verificação de possibilidade de consumo."""
        self.assertTrue(self.credit_service.can_consume_credits(Decimal("5.00")))
        self.assertFalse(self.credit_service.can_consume_credits(Decimal("15.00")))

    def test_get_credit_history(self):
        """Testa obtenção do histórico de créditos."""
        # Cria algumas transações
        self.credit_service.consume_credits(
            amount=Decimal("2.00"), description="Test 1", created_by=self.user
        )
        self.credit_service.add_credits(
            amount=Decimal("5.00"),
            transaction_type="bonus",
            description="Test 2",
            created_by=self.user,
        )

        history = self.credit_service.get_credit_history()
        self.assertEqual(len(history), 2)

        # Verifica ordenação (mais recente primeiro)
        self.assertEqual(history[0].description, "Test 2")
        self.assertEqual(history[1].description, "Test 1")

    def test_get_credit_stats(self):
        """Testa obtenção de estatísticas de créditos."""
        # Cria transações de diferentes tipos
        self.credit_service.add_credits(
            amount=Decimal("10.00"),
            transaction_type="purchase",
            description="Purchase",
            created_by=self.user,
        )
        self.credit_service.add_credits(
            amount=Decimal("5.00"),
            transaction_type="bonus",
            description="Bonus",
            created_by=self.user,
        )
        self.credit_service.consume_credits(
            amount=Decimal("3.00"), description="Consumption", created_by=self.user
        )

        stats = self.credit_service.get_credit_stats()

        self.assertEqual(stats["total_purchased"], Decimal("10.00"))
        self.assertEqual(stats["total_consumed"], Decimal("3.00"))
        self.assertEqual(stats["total_bonus"], Decimal("5.00"))


class CreditEndpointsTestCase(APITestCase):
    """Testes para os endpoints de créditos."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant-endpoints",
            plan_tier="standard",
            comm_credit_eur=Decimal("10.00"),
            comm_extra_allowed=True,
            comm_auto_renew=True,
        )
        self.user = User.objects.create_user(
            username="endpointuser",
            email="endpoint@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.client.force_authenticate(user=self.user)

    def test_credit_balance_view(self):
        """Testa endpoint de saldo de créditos."""
        url = reverse("credit_balance")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["current_balance"], "10.00")
        self.assertTrue(data["can_purchase_extra"])
        self.assertTrue(data["has_auto_renewal"])
        self.assertIn("total_purchased", data)
        self.assertIn("total_consumed", data)
        self.assertIn("total_bonus", data)

    def test_credit_history_view(self):
        """Testa endpoint de histórico de créditos."""
        # Cria uma transação
        credit_service = CreditService(self.tenant)
        credit_service.consume_credits(
            amount=Decimal("2.00"), description="Test consumption", created_by=self.user
        )

        url = reverse("credit_history")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data["results"]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["transaction_type"], "consumption")
        self.assertEqual(results[0]["amount_eur"], "2.00")

    def test_consume_credits_view_success(self):
        """Testa endpoint de consumo de créditos com sucesso."""
        url = reverse("consume_credits")
        data = {"amount": "5.00", "description": "Test consumption"}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertEqual(response_data["status"], "success")
        self.assertEqual(response_data["new_balance"], 5.0)
        self.assertIn("transaction_id", response_data)

    def test_consume_credits_view_insufficient_balance(self):
        """Testa endpoint de consumo com saldo insuficiente."""
        url = reverse("consume_credits")
        data = {"amount": "15.00", "description": "Test consumption"}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Saldo insuficiente", response.json()["detail"])

    def test_purchase_credits_view_success(self):
        """Testa endpoint de compra de créditos com sucesso."""
        url = reverse("purchase_credits")
        data = {"amount": "10.00"}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertEqual(response_data["status"], "success")
        self.assertEqual(response_data["new_balance"], 20.0)
        self.assertIn("transaction_id", response_data)

    def test_purchase_credits_view_not_allowed(self):
        """Testa endpoint de compra quando não permitido."""
        # Atualiza tenant para não permitir compras extras
        self.tenant.comm_extra_allowed = False
        self.tenant.save()

        url = reverse("purchase_credits")
        data = {"amount": "20.00"}

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("não permitida", response.json()["detail"])

    def test_purchase_credits_view_invalid_amount(self):
        """Testa endpoint de compra com valor inválido."""
        url = reverse("purchase_credits")
        data = {"amount": "3.00"}  # Menor que o mínimo de 5€

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_endpoints_require_authentication(self):
        """Testa que todos os endpoints requerem autenticação."""
        self.client.force_authenticate(user=None)

        endpoints = [
            "credit_balance",
            "credit_history",
            "consume_credits",
            "purchase_credits",
        ]

        for endpoint_name in endpoints:
            url = reverse(endpoint_name)
            if endpoint_name in ["consume_credits", "purchase_credits"]:
                response = self.client.post(url, {})
            else:
                response = self.client.get(url)

            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TenantCreditMethodsTestCase(TestCase):
    """Testes para os novos métodos do modelo Tenant."""

    def setUp(self):
        self.tenant_basic = Tenant.objects.create(
            name="Basic Tenant",
            slug="basic-tenant",
            plan_tier="basic",
            comm_extra_allowed=False,
            comm_auto_renew=False,
            custom_domain_enabled=False,
        )

        self.tenant_pro = Tenant.objects.create(
            name="Pro Tenant",
            slug="pro-tenant",
            plan_tier="pro",
            comm_extra_allowed=True,
            comm_auto_renew=True,
            custom_domain_enabled=True,
            custom_domain="custom.example.com",
        )

    def test_can_purchase_extra_credits(self):
        """Testa método can_purchase_extra_credits."""
        self.assertFalse(self.tenant_basic.can_purchase_extra_credits())
        self.assertTrue(self.tenant_pro.can_purchase_extra_credits())

    def test_has_auto_credit_renewal(self):
        """Testa método has_auto_credit_renewal."""
        self.assertFalse(self.tenant_basic.has_auto_credit_renewal())
        self.assertTrue(self.tenant_pro.has_auto_credit_renewal())

    def test_can_use_custom_domain(self):
        """Testa método can_use_custom_domain."""
        self.assertFalse(self.tenant_basic.can_use_custom_domain())
        self.assertTrue(self.tenant_pro.can_use_custom_domain())

        # Mesmo com custom_domain_enabled=True, plano básico não deve permitir
        self.tenant_basic.custom_domain_enabled = True
        self.tenant_basic.save()
        self.assertFalse(self.tenant_basic.can_use_custom_domain())
