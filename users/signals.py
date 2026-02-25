from decimal import Decimal
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from .models import Tenant, CommLedger

@receiver(post_save, sender=Tenant)
def assign_initial_credits(sender, instance, created, **kwargs):
    """
    Atribui créditos iniciais de comunicação ao criar um novo tenant,
    baseado no plano escolhido.
    """
    if not created:
        return

    # Define créditos por plano
    credits_map = {
        Tenant.PLAN_BASIC: Decimal("5.00"),
        Tenant.PLAN_PRO: Decimal("15.00"),
    }

    amount = credits_map.get(instance.plan_tier)
    description = f"Crédito inicial do plano {instance.get_plan_tier_display()}"

    # Founder tem garantia de 5.00 EUR (equivalente ao Basic)
    if instance.is_founder:
        founder_amount = Decimal("5.00")
        # Se o plano atual der menos que o Founder (ex: None ou futuro plano menor), garante 5.00
        # Se o plano der mais (ex: Pro), mantém o do plano.
        if not amount or amount < founder_amount:
            amount = founder_amount
        description = "Crédito inicial Plano Founder"
    
    if amount and amount > 0:
        # Usa transação atômica para garantir consistência entre Ledger e Tenant
        with transaction.atomic():
            # Cria registro no Ledger
            CommLedger.objects.create(
                tenant=instance,
                transaction_type=CommLedger.TransactionType.BONUS,
                amount_eur=amount,
                balance_before=Decimal("0.00"), # Tenant novo começa com 0
                balance_after=amount,
                status=CommLedger.Status.COMPLETED,
                description=description
            )
            
            # Atualiza saldo do Tenant
            # Usa update() para evitar recursão de signals e race conditions
            Tenant.objects.filter(pk=instance.pk).update(comm_credit_eur=amount)
