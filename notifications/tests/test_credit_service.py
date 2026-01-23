from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from users.models import Tenant, CommLedger
from notifications.credit_service import CommunicationCreditService

User = get_user_model()


class CommunicationCreditServiceTest(TestCase):
    def setUp(self):
        """Configurar dados de teste"""
        self.tenant = Tenant.objects.create(
            name="Salão Teste",
            slug="salao-teste",
            # comm_credit_eur=Decimal("10.00"),  # Removido pois o signal sobrescreve
            sms_enabled=True,
            whatsapp_enabled=True,
        )
        # Forçar saldo para 10.00 para os testes, ignorando o signal
        Tenant.objects.filter(pk=self.tenant.pk).update(
            comm_credit_eur=Decimal("10.00")
        )
        self.tenant.comm_ledger.all().delete()  # Limpar ledger do signal
        self.tenant.refresh_from_db()

        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            phone_number="+351912345678",
            tenant=self.tenant,
        )

        self.credit_service = CommunicationCreditService()

    def test_get_cost_sms(self):
        """Testar cálculo de custo para SMS"""
        cost = self.credit_service.get_cost("sms")
        self.assertEqual(cost, Decimal("0.05"))  # Ajustado para 2 casas decimais

    def test_get_cost_whatsapp_utility(self):
        """Testar cálculo de custo para WhatsApp utility"""
        cost = self.credit_service.get_cost("whatsapp", "utility")
        self.assertEqual(cost, Decimal("0.03"))

    def test_get_cost_whatsapp_marketing(self):
        """Testar cálculo de custo para WhatsApp marketing"""
        cost = self.credit_service.get_cost("whatsapp", "marketing")
        self.assertEqual(cost, Decimal("0.04"))

    def test_get_cost_invalid_type(self):
        """Testar retorno para tipo de comunicação inválido"""
        cost = self.credit_service.get_cost("invalid_type")
        self.assertEqual(cost, Decimal("0.00"))

    def test_can_send_message_sufficient_balance(self):
        """Testar verificação com saldo suficiente"""
        result = self.credit_service.can_send_message(self.tenant, "sms")

        self.assertTrue(result["can_send"])
        self.assertEqual(
            result["cost"], Decimal("0.05")
        )  # Ajustado para 2 casas decimais
        self.assertEqual(result["balance"], Decimal("10.00"))
        self.assertEqual(result["reason"], "Saldo suficiente")

    def test_can_send_message_insufficient_balance(self):
        """Testar verificação com saldo insuficiente"""
        # Reduzir saldo para menos que o custo do SMS
        self.tenant.comm_credit_eur = Decimal("0.01")
        self.tenant.save()

        result = self.credit_service.can_send_message(self.tenant, "sms")

        self.assertFalse(result["can_send"])
        self.assertEqual(
            result["cost"], Decimal("0.05")
        )  # Ajustado para 2 casas decimais
        self.assertEqual(result["balance"], Decimal("0.01"))
        self.assertIn("Saldo insuficiente", result["reason"])

    def test_can_send_message_sms_disabled(self):
        """Testar verificação com SMS desabilitado"""
        self.tenant.sms_enabled = False
        self.tenant.save()

        result = self.credit_service.can_send_message(self.tenant, "sms")

        self.assertFalse(result["can_send"])
        self.assertEqual(result["reason"], "SMS não habilitado para este tenant")

    def test_can_send_message_whatsapp_disabled(self):
        """Testar verificação com WhatsApp desabilitado"""
        self.tenant.whatsapp_enabled = False
        self.tenant.save()

        result = self.credit_service.can_send_message(self.tenant, "whatsapp")

        self.assertFalse(result["can_send"])
        self.assertEqual(result["reason"], "WhatsApp não habilitado para este tenant")

    def test_charge_for_message_success(self):
        """Testar cobrança bem-sucedida de crédito"""
        initial_balance = self.tenant.comm_credit_eur

        result = self.credit_service.charge_for_message(
            tenant=self.tenant,
            communication_type="sms",
            description="Teste de SMS",
            user=self.user,
        )

        # Verificar resultado - usar valor com 2 casas decimais
        self.assertTrue(result["success"])
        self.assertEqual(
            result["cost"], Decimal("0.05")
        )  # Ajustado para 2 casas decimais
        expected_balance = Decimal("9.95")  # 10.00 - 0.05 = 9.95
        self.assertEqual(result["new_balance"], expected_balance)

        # Verificar se o tenant foi atualizado
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, expected_balance)

        # Verificar entrada no ledger
        ledger_entry = result["ledger_entry"]
        self.assertEqual(ledger_entry.tenant, self.tenant)
        self.assertEqual(
            ledger_entry.transaction_type, CommLedger.TransactionType.CONSUMPTION
        )
        self.assertEqual(
            ledger_entry.amount_eur, Decimal("0.05")
        )  # Ajustado para 2 casas decimais
        self.assertEqual(ledger_entry.balance_before, initial_balance)
        self.assertEqual(ledger_entry.balance_after, expected_balance)
        self.assertEqual(ledger_entry.status, CommLedger.Status.COMPLETED)
        self.assertEqual(ledger_entry.created_by, self.user)
        self.assertIn("Teste de SMS", ledger_entry.description)

    def test_charge_for_message_insufficient_balance(self):
        """Testar cobrança com saldo insuficiente"""
        # Reduzir saldo
        self.tenant.comm_credit_eur = Decimal("0.01")
        self.tenant.save()

        result = self.credit_service.charge_for_message(
            tenant=self.tenant, communication_type="sms", user=self.user
        )

        # Verificar falha
        self.assertFalse(result["success"])
        self.assertIn("Saldo insuficiente", result["error"])

        # Verificar que o saldo não foi alterado
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.comm_credit_eur, Decimal("0.01"))

        # Verificar que não foi criada entrada no ledger
        self.assertEqual(CommLedger.objects.filter(tenant=self.tenant).count(), 0)

    def test_charge_for_whatsapp_marketing(self):
        """Testar cobrança para WhatsApp marketing (custo maior)"""
        initial_balance = self.tenant.comm_credit_eur

        result = self.credit_service.charge_for_message(
            tenant=self.tenant,
            communication_type="whatsapp",
            message_category="marketing",
            user=self.user,
        )

        # Verificar resultado
        self.assertTrue(result["success"])
        self.assertEqual(result["cost"], Decimal("0.04"))  # Custo marketing
        self.assertEqual(result["new_balance"], initial_balance - Decimal("0.04"))

        # Verificar entrada no ledger
        ledger_entry = result["ledger_entry"]
        self.assertEqual(ledger_entry.amount_eur, Decimal("0.04"))
        self.assertIn("marketing", ledger_entry.description)

    def test_get_balance(self):
        """Testar obtenção do saldo atual"""
        balance = self.credit_service.get_balance(self.tenant)
        self.assertEqual(balance, Decimal("10.00"))

    def test_get_recent_transactions(self):
        """Testar obtenção de transações recentes"""
        # Criar algumas transações
        self.credit_service.charge_for_message(self.tenant, "sms", user=self.user)
        self.credit_service.charge_for_message(self.tenant, "whatsapp", user=self.user)

        transactions = self.credit_service.get_recent_transactions(self.tenant, limit=5)

        # Verificar que retornou as transações ordenadas por data (mais recente primeiro)
        self.assertEqual(len(transactions), 2)
        self.assertTrue(transactions[0].created_at >= transactions[1].created_at)

        # Verificar que todas são do tenant correto
        for transaction in transactions:
            self.assertEqual(transaction.tenant, self.tenant)
            self.assertEqual(
                transaction.transaction_type, CommLedger.TransactionType.CONSUMPTION
            )
