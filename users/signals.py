from decimal import Decimal
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction

from payments.services import SubscriptionService
from .models import Tenant, CommLedger


@receiver(post_save, sender=Tenant)
def assign_initial_credits(sender, instance, created, **kwargs):
    """
    Atribui créditos iniciais de comunicação ao criar um novo tenant,
    baseado no plano escolhido. A fonte da verdade para os valores é
    SubscriptionService.get_available_plans().
    """
    if not created:
        return

    plan_code_to_find = "founder" if instance.is_founder else instance.plan_tier

    # Utiliza o método que já consolida a lógica de planos, incluindo o Founder
    available_plans = SubscriptionService.get_available_plans(tenant=instance)

    plan_info = next(
        (p for p in available_plans if p["plan_code"] == plan_code_to_find), None
    )

    if plan_info:
        # O valor em get_available_plans já é um int, convertemos para Decimal
        amount = Decimal(str(plan_info.get("credits_included", 0)))
        description = (
            f"Crédito inicial do plano {plan_info.get('name', plan_code_to_find)}"
        )
    else:
        amount = Decimal("0.00")
        description = "Nenhum crédito inicial para o plano."

    if amount and amount > 0:
        # Usa transação atômica para garantir consistência entre Ledger e Tenant
        with transaction.atomic():
            # Cria registro no Ledger
            CommLedger.objects.create(
                tenant=instance,
                transaction_type=CommLedger.TransactionType.BONUS,
                amount_eur=amount,
                balance_before=Decimal("0.00"),  # Tenant novo começa com 0
                balance_after=amount,
                status=CommLedger.Status.COMPLETED,
                description=description,
            )

            # Atualiza saldo do Tenant
            # Usa update() para evitar recursão de signals e race conditions
            Tenant.objects.filter(pk=instance.pk).update(comm_credit_eur=amount)
