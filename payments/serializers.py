from rest_framework import serializers
from decimal import Decimal


class CheckoutSessionRequestSerializer(serializers.Serializer):
    plan = serializers.ChoiceField(
        choices=["basic", "pro", "founder"],
        required=False,
        help_text="Plano desejado",
    )
    interval = serializers.ChoiceField(
        choices=["monthly", "annual"],
        required=False,
        default="monthly",
        help_text="Ciclo de faturamento (monthly/annual)",
    )


class CheckoutSessionResponseSerializer(serializers.Serializer):
    checkout_url = serializers.URLField()
    session_id = serializers.CharField(help_text="ID da sessão de checkout")


class PortalSessionResponseSerializer(serializers.Serializer):
    portal_url = serializers.URLField()


class CreditPurchaseRequestSerializer(serializers.Serializer):
    amount_eur = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("5.00"),
        max_value=Decimal("100.00"),
        help_text="Valor em euros para compra de créditos (mínimo €5, máximo €100)",
    )


class CreditPurchaseResponseSerializer(serializers.Serializer):
    client_secret = serializers.CharField(help_text="Client secret do PaymentIntent")
    payment_intent_id = serializers.CharField(help_text="ID do PaymentIntent")
    amount_eur = serializers.DecimalField(max_digits=10, decimal_places=2)


class AvailableCreditPackagesResponseSerializer(serializers.Serializer):
    packages = serializers.ListField(
        child=serializers.DictField(),
        help_text="Lista de pacotes de créditos disponíveis",
    )


class AvailablePlansSerializer(serializers.Serializer):
    """Serializer para planos disponíveis."""

    plan_code = serializers.CharField(help_text="Código do plano")
    name = serializers.CharField(help_text="Nome do plano")
    price_monthly = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="Preço mensal em euros"
    )
    features = serializers.ListField(
        child=serializers.CharField(), help_text="Lista de funcionalidades do plano"
    )
    credits_included = serializers.IntegerField(
        help_text="Créditos de comunicação inclusos"
    )
    is_current = serializers.BooleanField(help_text="Se é o plano atual do usuário")
    can_upgrade = serializers.BooleanField(
        help_text="Se pode fazer upgrade para este plano"
    )
    is_available = serializers.BooleanField(
        help_text="Se o plano está disponível para o usuário (false = oferta encerrada ou já utilizada)"
    )


class CurrentSubscriptionSerializer(serializers.Serializer):
    """Serializer para assinatura atual."""

    plan_code = serializers.CharField(help_text="Código do plano atual")
    plan_name = serializers.CharField(help_text="Nome do plano atual")
    status = serializers.CharField(help_text="Status da assinatura")
    status_label = serializers.CharField(help_text="Status da assinatura (Traduzido)")
    current_period_end = serializers.DateTimeField(help_text="Fim do período atual")
    cancel_at_period_end = serializers.BooleanField(
        help_text="Se será cancelada no fim do período"
    )
    next_billing_date = serializers.DateTimeField(
        help_text="Próxima data de cobrança", allow_null=True
    )
    price_monthly = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="Preço mensal"
    )
    interval = serializers.CharField(
        help_text="Ciclo de cobrança (month/year)", default="month"
    )


class PaymentHistoryItemSerializer(serializers.Serializer):
    """Serializer para item do histórico de pagamentos."""

    id = serializers.CharField(help_text="ID da transação")
    date = serializers.DateTimeField(help_text="Data da transação")
    type = serializers.ChoiceField(
        choices=["subscription", "credit_purchase"], help_text="Tipo de transação"
    )
    description = serializers.CharField(help_text="Descrição da transação")
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="Valor em euros"
    )
    status = serializers.CharField(help_text="Status da transação")
    invoice_url = serializers.URLField(help_text="URL da fatura", allow_null=True)


class PaymentHistorySerializer(serializers.Serializer):
    """Serializer para histórico de pagamentos."""

    transactions = PaymentHistoryItemSerializer(
        many=True, help_text="Lista de transações"
    )
    total_spent = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="Total gasto"
    )
    subscription_total = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="Total em assinaturas"
    )
    credits_total = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="Total em créditos"
    )


class BillingOverviewSerializer(serializers.Serializer):
    """Serializer para visão geral do billing."""

    current_subscription = CurrentSubscriptionSerializer(allow_null=True)
    available_plans = AvailablePlansSerializer(many=True)
    credit_balance = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="Saldo atual de créditos"
    )
    can_purchase_credits = serializers.BooleanField(
        help_text="Se pode comprar créditos extras"
    )
    has_auto_renewal = serializers.BooleanField(
        help_text="Se tem renovação automática de créditos"
    )
    next_billing_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Próximo valor a ser cobrado",
        allow_null=True,
    )
    trial_eligible = serializers.BooleanField(
        help_text="Se é elegível ao período de teste"
    )
    trial_days = serializers.IntegerField(
        help_text="Dias de teste configurados", default=0
    )
    trial_exhausted = serializers.BooleanField(
        help_text="Se o período de teste já foi utilizado"
    )


class SubscriptionActionSerializer(serializers.Serializer):
    """Serializer para ações de assinatura (cancelar, reativar)."""

    action = serializers.ChoiceField(
        choices=["cancel", "reactivate"], help_text="Ação a ser executada na assinatura"
    )
    cancel_at_period_end = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Se deve cancelar no fim do período (apenas para cancel)",
    )


class StripeSettingsUpdateRequestSerializer(serializers.Serializer):
    """Payload para atualizar configurações de billing (Stripe)."""

    auto_renewal = serializers.BooleanField(
        help_text="Ativa/desativa renovação automática de créditos de comunicação"
    )


class StripeSettingsResponseSerializer(serializers.Serializer):
    """Resposta simplificada para configurações de billing (Stripe)."""

    auto_renewal = serializers.BooleanField(
        help_text="Estado atual da renovação automática de créditos de comunicação"
    )
