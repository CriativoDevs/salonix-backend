"""
Serviços para gerenciamento de créditos de comunicação.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Dict, Any
from django.db import transaction, models
from django.utils import timezone

from .models import Tenant, CommLedger


class CreditService:
    """Serviço para gerenciar créditos de comunicação."""

    def __init__(self, tenant: Tenant):
        self.tenant = tenant

    def get_credit_balance(self) -> Decimal:
        """Retorna o saldo atual de créditos do tenant."""
        return self.tenant.comm_credit_eur or Decimal("0.00")

    def get_credit_history(self) -> models.QuerySet[CommLedger]:
        """Retorna o histórico de transações de créditos do tenant (QuerySet)."""
        return CommLedger.objects.filter(tenant=self.tenant).order_by("-created_at")

    @transaction.atomic
    def consume_credits(
        self,
        amount: Decimal,
        description: str,
        reference_id: Optional[str] = None,
        created_by: Optional[Any] = None,
    ) -> CommLedger:
        """
        Consome créditos do tenant.

        Args:
            amount: Valor em euros a ser consumido
            description: Descrição da transação
            reference_id: ID de referência externa (opcional)
            created_by: Usuário que criou a transação (opcional)

        Returns:
            CommLedger: Registro da transação criada

        Raises:
            ValueError: Se não houver saldo suficiente
        """
        if amount <= 0:
            raise ValueError("Valor deve ser maior que zero")

        current_balance = self.get_credit_balance()

        if current_balance < amount:
            raise ValueError(
                f"Saldo insuficiente. Saldo atual: {current_balance}€, tentativa de consumo: {amount}€"
            )

        new_balance = current_balance - amount

        # Cria o registro da transação
        transaction_record = CommLedger.objects.create(
            tenant=self.tenant,
            transaction_type="consumption",
            amount_eur=amount,
            balance_before=current_balance,
            balance_after=new_balance,
            status="completed",
            description=description,
            reference_id=reference_id,
            created_by=created_by,
        )

        # Atualiza o saldo do tenant
        self.tenant.comm_credit_eur = new_balance
        self.tenant.save(update_fields=["comm_credit_eur"])

        return transaction_record

    @transaction.atomic
    def add_credits(
        self,
        amount: Decimal,
        transaction_type: str,
        description: str,
        reference_id: Optional[str] = None,
        created_by: Optional[Any] = None,
        expires_at: Optional[timezone.datetime] = None,
    ) -> CommLedger:
        """
        Adiciona créditos ao tenant.

        Args:
            amount: Valor em euros a ser adicionado
            transaction_type: Tipo da transação (purchase, bonus, refund)
            description: Descrição da transação
            reference_id: ID de referência externa (opcional)
            created_by: Usuário que criou a transação (opcional)
            expires_at: Data de expiração dos créditos (opcional)

        Returns:
            CommLedger: Registro da transação criada
        """
        if amount <= 0:
            raise ValueError("Valor deve ser maior que zero")

        if transaction_type not in ["purchase", "bonus", "refund"]:
            raise ValueError("Tipo de transação inválido")

        current_balance = self.get_credit_balance()
        new_balance = current_balance + amount

        # Cria o registro da transação
        transaction_record = CommLedger.objects.create(
            tenant=self.tenant,
            transaction_type=transaction_type,
            amount_eur=amount,
            balance_before=current_balance,
            balance_after=new_balance,
            status="completed",
            description=description,
            reference_id=reference_id,
            expires_at=expires_at,
            created_by=created_by,
        )

        # Atualiza o saldo do tenant
        self.tenant.comm_credit_eur = new_balance
        self.tenant.save(update_fields=["comm_credit_eur"])

        return transaction_record

    def can_consume_credits(self, amount: Decimal) -> bool:
        """Verifica se é possível consumir a quantidade especificada de créditos."""
        return self.get_credit_balance() >= amount

    def get_credit_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de uso de créditos do tenant."""
        transactions = CommLedger.objects.filter(tenant=self.tenant, status="completed")

        total_purchased = transactions.filter(transaction_type="purchase").aggregate(
            total=models.Sum("amount_eur")
        )["total"] or Decimal("0.00")

        total_consumed = transactions.filter(transaction_type="consumption").aggregate(
            total=models.Sum("amount_eur")
        )["total"] or Decimal("0.00")

        total_bonus = transactions.filter(transaction_type="bonus").aggregate(
            total=models.Sum("amount_eur")
        )["total"] or Decimal("0.00")

        return {
            "total_purchased": total_purchased,
            "total_consumed": total_consumed,
            "total_bonus": total_bonus,
        }

    @transaction.atomic
    def expire_credits(
        self,
        amount: Decimal,
        description: str,
        reference_id: Optional[str] = None,
        created_by: Optional[Any] = None,
    ) -> CommLedger:
        """
        Expira créditos do tenant.

        Args:
            amount: Valor em euros a ser expirado
            description: Descrição da transação
            reference_id: ID de referência externa (opcional)
            created_by: Usuário que criou a transação (opcional)

        Returns:
            CommLedger: Registro da transação criada
        """
        if amount <= 0:
            raise ValueError("Valor deve ser maior que zero")

        current_balance = self.get_credit_balance()
        expire_amount = amount if amount <= current_balance else current_balance
        if expire_amount <= 0:
            raise ValueError("Saldo insuficiente para expiração")

        new_balance = current_balance - expire_amount

        transaction_record = CommLedger.objects.create(
            tenant=self.tenant,
            transaction_type="expiration",
            amount_eur=expire_amount,
            balance_before=current_balance,
            balance_after=new_balance,
            status="completed",
            description=description,
            reference_id=reference_id,
            created_by=created_by,
        )

        self.tenant.comm_credit_eur = new_balance
        self.tenant.save(update_fields=["comm_credit_eur"])

        return transaction_record


class TenantService:
    """Serviço para gerenciamento de Tenants."""

    @staticmethod
    @transaction.atomic
    def cancel_tenant(tenant: Tenant, user: Any) -> None:
        """
        Realiza o cancelamento (soft-delete) do tenant.

        Args:
            tenant: O tenant a ser cancelado.
            user: O usuário que solicitou o cancelamento (para logs/auditoria futura).
        """
        if not tenant.is_active:
            # Já está inativo, nada a fazer
            return

        tenant.is_active = False
        tenant.deleted_at = timezone.now()
        # Founder é perdido definitivamente no cancelamento
        if tenant.is_founder:
            tenant.is_founder = False
            update_fields = ["is_active", "deleted_at", "updated_at", "is_founder"]
        else:
            update_fields = ["is_active", "deleted_at", "updated_at"]
        
        tenant.save(update_fields=update_fields)

        # Aqui poderíamos adicionar logs de auditoria ou disparar e-mails de "Adeus"


class FounderService:
    """Serviço para gerenciamento do plano Founder."""

    FOUNDER_LIMIT = 500

    @classmethod
    def get_availability(cls) -> Dict[str, int]:
        """
        Retorna a disponibilidade do plano Founder.
        
        Returns:
            Dict com 'total_limit', 'used_count' e 'remaining_count'.
        """
        used_count = Tenant.objects.filter(is_founder=True, is_active=True).count()
        remaining_count = max(0, cls.FOUNDER_LIMIT - used_count)
        
        return {
            "total_limit": cls.FOUNDER_LIMIT,
            "used_count": used_count,
            "remaining_count": remaining_count,
        }

    @classmethod
    def can_assign_founder(cls) -> bool:
        """Verifica se ainda há vagas para o plano Founder."""
        availability = cls.get_availability()
        return availability["remaining_count"] > 0

