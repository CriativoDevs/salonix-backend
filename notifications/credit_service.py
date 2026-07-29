import logging
from decimal import Decimal
from typing import Dict
from django.db import transaction
from django.utils import timezone
from users.models import Tenant, CommLedger

logger = logging.getLogger(__name__)


class CommunicationCreditService:
    """
    Serviço para gerenciar créditos de comunicação (SMS/WhatsApp).
    Implementa cobrança, validação de saldo e registro de consumo.
    """

    def __init__(self):
        pass

    def get_cost(
        self, tenant: Tenant, communication_type: str, message_category: str = None
    ) -> Decimal:
        """
        Retorna o custo de uma comunicação baseado no tipo, plano do tenant e categoria

        Args:
            tenant: Instância do Tenant
            communication_type: 'sms' ou 'whatsapp'
            message_category: Para WhatsApp: 'utility', 'marketing', 'service'

        Returns:
            Decimal: Custo em euros
        """
        if communication_type == "sms":
            # Founder/Basic: 0,09€ | Pro: 0,08€
            if tenant.plan_tier == Tenant.PLAN_PRO:
                return Decimal("0.08")
            return Decimal("0.09")

        elif communication_type == "whatsapp":
            # Custos WhatsApp (atualmente fixos por categoria, independente do plano)
            whatsapp_costs = {
                "utility": Decimal("0.03"),
                "marketing": Decimal("0.04"),
                "service": Decimal("0.02"),
            }
            return whatsapp_costs.get(message_category, whatsapp_costs["utility"])

        return Decimal("0.00")

    def can_send_message(
        self, tenant: Tenant, communication_type: str, message_category: str = "utility"
    ) -> Dict[str, any]:
        """
        Verifica se o tenant pode enviar uma mensagem baseado no saldo de créditos.

        Args:
            tenant: Instância do Tenant
            communication_type: 'sms' ou 'whatsapp'
            message_category: Categoria da mensagem (para WhatsApp)

        Returns:
            Dict com 'can_send' (bool), 'cost' (Decimal), 'balance' (Decimal), 'reason' (str)
        """
        cost = self.get_cost(tenant, communication_type, message_category)
        current_balance = tenant.comm_credit_eur

        result = {
            "can_send": False,
            "cost": cost,
            "balance": current_balance,
            "reason": "",
        }

        # Verificar se o canal está habilitado
        if communication_type == "sms" and not tenant.sms_enabled:
            result["reason"] = "SMS não habilitado para este tenant"
            return result
        elif communication_type == "whatsapp" and not tenant.whatsapp_enabled:
            result["reason"] = "WhatsApp não habilitado para este tenant"
            return result

        # BE-PLANS-02 / BE-INFRA-01: SMS fica bloqueado durante o período de teste
        # (trial) e também fora dele para tenants sem subscrição Stripe paga
        # confirmada (ex.: billing_mode=promotional, ou qualquer conta sem pro_status
        # active/past_due) — evita custo de comunicação em contas que não pagam.
        # Apenas o canal SMS é afetado; Email e Web Push (que não passam por aqui) e
        # WhatsApp seguem livres. Liberação é automática assim que o owner tiver uma
        # subscrição Stripe active/past_due confirmada.
        if communication_type == "sms" and (
            tenant.is_in_trial() or not tenant.has_active_paid_subscription()
        ):
            result["reason"] = "SMS disponível após período de teste com subscrição paga ativa"
            return result

        # Verificar saldo suficiente
        if current_balance >= cost:
            result["can_send"] = True
            result["reason"] = "Saldo suficiente"
            return result

        # BE-CREDITS-02: saldo insuficiente + renovação automática ativa tenta
        # comprar mais crédito (cartão já salvo, sem interação do tenant) antes
        # de bloquear o envio. Limite de 1 tentativa/dia evita loop de cobrança
        # em caso de erro (cartão recusado etc.) — falha silenciosa nesta v1.
        if tenant.comm_auto_renew and tenant.comm_auto_renew_price_id:
            today = timezone.now().date()
            if tenant.comm_auto_renew_last_purchase_at != today:
                from payments.services import CreditPurchaseService

                CreditPurchaseService.charge_auto_renewal(tenant)

                tenant.comm_auto_renew_last_purchase_at = today
                tenant.save(update_fields=["comm_auto_renew_last_purchase_at"])

                current_balance = tenant.comm_credit_eur
                if current_balance >= cost:
                    result["can_send"] = True
                    result["reason"] = "Saldo suficiente"
                    result["balance"] = current_balance
                    return result

        result["reason"] = (
            f"Saldo insuficiente. Necessário: €{cost}, Disponível: €{current_balance}"
        )
        result["balance"] = current_balance

        return result

    @transaction.atomic
    def charge_for_message(
        self,
        tenant: Tenant,
        communication_type: str,
        message_category: str = "utility",
        description: str = "",
        user=None,
    ) -> Dict[str, any]:
        """
        Cobra o crédito por uma mensagem enviada.

        Args:
            tenant: Instância do Tenant
            communication_type: 'sms' ou 'whatsapp'
            message_category: Categoria da mensagem
            description: Descrição da transação
            user: Usuário que iniciou o envio (opcional)

        Returns:
            Dict com 'success' (bool), 'ledger_entry' (CommLedger), 'new_balance' (Decimal)
        """
        # Verificar se pode enviar
        check_result = self.can_send_message(
            tenant, communication_type, message_category
        )
        if not check_result["can_send"]:
            return {
                "success": False,
                "error": check_result["reason"],
                "cost": check_result["cost"],
                "balance": check_result["balance"],
            }

        cost = check_result["cost"]
        balance_before = tenant.comm_credit_eur

        # Atualizar saldo do tenant
        tenant.comm_credit_eur -= cost
        tenant.save(update_fields=["comm_credit_eur", "updated_at"])

        # Criar entrada no ledger
        ledger_entry = CommLedger.objects.create(
            tenant=tenant,
            transaction_type=CommLedger.TransactionType.CONSUMPTION,
            amount_eur=cost,
            balance_before=balance_before,
            balance_after=tenant.comm_credit_eur,
            status=CommLedger.Status.COMPLETED,
            description=description
            or f"Envio de {communication_type} - {message_category}",
            created_by=user,
        )

        logger.info(
            f"Crédito cobrado: {tenant.name} - {communication_type} - €{cost}",
            extra={
                "tenant_id": tenant.id,
                "communication_type": communication_type,
                "cost": str(cost),
                "balance_before": str(balance_before),
                "balance_after": str(tenant.comm_credit_eur),
                "ledger_id": ledger_entry.id,
            },
        )

        return {
            "success": True,
            "ledger_entry": ledger_entry,
            "new_balance": tenant.comm_credit_eur,
            "cost": cost,
        }

    def get_balance(self, tenant: Tenant) -> Decimal:
        """Retorna o saldo atual de créditos do tenant."""
        return tenant.comm_credit_eur

    def get_recent_transactions(self, tenant: Tenant, limit: int = 10) -> list:
        """
        Retorna as transações recentes de crédito do tenant.

        Args:
            tenant: Instância do Tenant
            limit: Número máximo de transações a retornar

        Returns:
            Lista de CommLedger ordenada por data (mais recente primeiro)
        """
        return list(
            CommLedger.objects.filter(tenant=tenant).order_by("-created_at")[:limit]
        )


# Instância global do serviço
credit_service = CommunicationCreditService()
