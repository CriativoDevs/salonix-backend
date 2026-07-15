"""
Serviços para gerenciamento de créditos de comunicação.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
from django.db import transaction, models
from django.utils import timezone
from django.core.cache import cache

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
        expires_at: Optional[datetime] = None,
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
    """
    Serviço para gerenciamento do plano Founder.
    Nota: O plano Founder tecnicamente herda todas as características do plano Basic
    (Tenant.plan_tier = 'basic'), mas possui a flag is_founder=True para
    identificação e benefícios futuros/exclusivos.
    """

    FOUNDER_LIMIT = 500

    @classmethod
    def get_availability(cls) -> Dict[str, int]:
        """
        Retorna a disponibilidade do plano Founder.

        Returns:
            Dict com 'total_limit', 'used_count' e 'remaining_count'.
        """
        # Contar HISTÓRICO de quantos tenants JÁ USARAM Founder (não apenas os ativos)
        # Busca em subscriptions para pegar histórico, não apenas is_founder atual
        try:
            from payments.models import Subscription
            from payments.stripe_utils import get_plan_code_from_price

            # Pega todos os tenants que já tiveram subscription Founder alguma vez
            founder_subscriptions = Subscription.objects.filter(
                price_id__isnull=False
            ).select_related("user__tenant")

            founder_tenant_ids = set()
            for sub in founder_subscriptions:
                if sub.price_id:
                    plan = get_plan_code_from_price(sub.price_id)
                    if plan == "founder" and sub.user and sub.user.tenant:
                        founder_tenant_ids.add(sub.user.tenant.id)

            used_count = len(founder_tenant_ids)
        except (ImportError, Exception) as e:
            # Fallback: se erro ao importar ou buscar subscriptions, usa o método antigo
            print(f"[FounderService] Erro ao buscar histórico: {e}. Usando fallback.")
            used_count = Tenant.objects.filter(is_founder=True, is_active=True).count()

        remaining_count = max(0, cls.FOUNDER_LIMIT - used_count)

        print(
            f"[FounderService] Limit: {cls.FOUNDER_LIMIT}, Used: {used_count}, Remaining: {remaining_count}"
        )

        return {
            "total_limit": cls.FOUNDER_LIMIT,
            "used_count": used_count,
            "remaining_count": remaining_count,
        }

    @classmethod
    def can_assign_founder(cls, tenant: Optional[Tenant] = None) -> bool:
        """
        Verifica se ainda há vagas para o plano Founder e se o tenant pode ser atribuído.

        Args:
            tenant: Tenant opcional. Se fornecido, verifica se o tenant já teve Founder.

        Returns:
            bool: True se há vagas E (sem tenant ou tenant é elegível)
        """
        availability = cls.get_availability()

        if availability["remaining_count"] <= 0:
            print("[FounderService.can_assign_founder] Limite de Founders atingido")
            return False

        if tenant:
            print(
                f"[FounderService.can_assign_founder] Validando tenant: {tenant.slug}, is_founder={tenant.is_founder}"
            )

            # Se já é founder ativo, mantém elegibilidade para renovação
            if tenant.is_founder:
                print(
                    f"[FounderService.can_assign_founder] {tenant.slug} é Founder ativo - mantém elegibilidade"
                )
                return True

            # Verificar se já teve assinatura Founder no passado
            # Se sim, nega o direito de volta (oferta única por tenant)
            try:
                from payments.models import Subscription
                from payments.stripe_utils import get_plan_code_from_price

                # Busca ALL assinaturas históricas do tenant (via users)
                subs = Subscription.objects.filter(user__tenant=tenant)
                print(
                    f"[FounderService.can_assign_founder] {tenant.slug} possui {subs.count()} subscriptions no histórico"
                )

                for sub in subs:
                    print(
                        f"[FounderService.can_assign_founder]   Subscription: price_id={sub.price_id}, status={sub.status}"
                    )
                    if sub.price_id:
                        plan = get_plan_code_from_price(sub.price_id)
                        print(
                            f"[FounderService.can_assign_founder]   -> Plano detectado: {plan}"
                        )
                        if plan == "founder":
                            # Já teve founder no passado => perdeu o direito para sempre
                            print(
                                f"[FounderService.can_assign_founder] {tenant.slug} JÁ TEVE FOUNDER NO PASSADO - NEGANDO"
                            )
                            return False
            except ImportError:
                print(
                    f"[FounderService.can_assign_founder] Erro ao importar - assumindo elegível"
                )
                # Se erro ao importar, assume que pode (fail-open para não bloquear checkout)
                pass

            print(
                f"[FounderService.can_assign_founder] {tenant.slug} é elegível para Founder"
            )

            return True

        # Sem tenant: apenas validação de limite global
        return True

    @classmethod
    def is_basic_blocked(cls, tenant: Optional[Tenant] = None) -> bool:
        """
        Retorna True se o plano Basic NÃO deve estar disponível porque ainda
        há vagas Founder (das 500) e o tenant nunca teve Founder (nem é
        Founder atualmente).

        Regra de negócio: enquanto houver vagas Founder, só Founder é
        oferecido a tenants novos; Basic só aparece depois de esgotar as
        vagas. Um tenant que já é (ou já foi) Founder pode sempre escolher
        Basic livremente — essa transição nunca é bloqueada.
        """
        availability = cls.get_availability()
        if availability["remaining_count"] <= 0:
            return False

        if tenant is None:
            return True

        if tenant.is_founder:
            return False

        return cls.can_assign_founder(tenant=tenant)


class SMSRateLimiter:

    PLAN_LIMITS = {
        "founder": {"minute": 3, "hour": 30, "day": 150, "month": 4500},
        "basic": {"minute": 3, "hour": 30, "day": 150, "month": 4500},
        "pro": {"minute": 10, "hour": 120, "day": 800, "month": 24000},
    }

    WINDOW_TTLS = {
        "minute": 60,
        "hour": 60 * 60,
        "day": 60 * 60 * 24,
        "month": 60 * 60 * 24 * 31,  # aprox.
    }

    def _keys_for_tenant(self, tenant: Tenant, now: Optional[datetime] = None) -> Dict[str, str]:
        now = now or timezone.now()
        ym = now.strftime("%Y-%m")
        ymd = now.strftime("%Y-%m-%d")
        hm = now.strftime("%Y-%m-%dT%H:%M")
        hh = now.strftime("%Y-%m-%dT%H")
        base = f"sms:{tenant.id}"
        return {
            "minute": f"{base}:min:{hm}",
            "hour": f"{base}:hour:{hh}",
            "day": f"{base}:day:{ymd}",
            "month": f"{base}:month:{ym}",
        }

    def _get_limits(self, tenant: Tenant) -> Dict[str, int]:
        plan = tenant.plan_tier or "basic"
        limits = self.PLAN_LIMITS.get(plan, self.PLAN_LIMITS["basic"])
        return limits

    def check_and_increment(self, tenant: Tenant) -> Dict[str, int]:
        from salonix_backend.error_handling import BusinessError, ErrorCodes

        limits = self._get_limits(tenant)
        keys = self._keys_for_tenant(tenant)

        counts_after: Dict[str, int] = {}

        for scope in ("minute", "hour", "day", "month"):
            key = keys[scope]
            ttl = self.WINDOW_TTLS[scope]
            limit = limits[scope]

            try:
                cache.add(key, 0, timeout=ttl)
            except Exception:
                continue

            try:
                current = cache.get(key) or 0
            except Exception:
                current = 0

            if current >= limit:
                raise BusinessError(
                    message=f"Limite de SMS atingido para janela: {scope}",
                    code=ErrorCodes.SYSTEM_RATE_LIMIT_EXCEEDED,
                    details={"scope": scope, "limit": limit, "count": current, "tenant_id": tenant.id},
                )

            try:
                counts_after[scope] = cache.incr(key)
            except Exception:
                try:
                    cache.set(key, current + 1, timeout=ttl)
                    counts_after[scope] = current + 1
                except Exception:
                    counts_after[scope] = current + 1

        return counts_after


sms_rate_limiter = SMSRateLimiter()
