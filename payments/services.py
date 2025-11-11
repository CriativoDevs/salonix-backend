import stripe
import logging
from decimal import Decimal
from datetime import datetime, timezone
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from typing import Dict, List, Optional, Any
from .models import PaymentCustomer, Subscription, CreditPayment
from users.models import Tenant
from .stripe_utils import get_stripe, get_or_create_customer, get_price_id_for_plan, get_plan_code_from_price

logger = logging.getLogger(__name__)

# Configurar Stripe
stripe.api_key = settings.STRIPE_API_KEY

User = get_user_model()


class StripePaymentService:
    """Serviço para gerenciar pagamentos com Stripe."""

    @staticmethod
    def get_or_create_customer(user: User) -> str:
        """Obtém ou cria um customer no Stripe para o usuário."""
        try:
            payment_customer = PaymentCustomer.objects.get(user=user)
            return payment_customer.stripe_customer_id
        except PaymentCustomer.DoesNotExist:
            # Criar customer no Stripe
            stripe_customer = stripe.Customer.create(
                email=user.email,
                name=f"{user.first_name} {user.last_name}".strip() or user.username,
                metadata={
                    'user_id': user.id,
                    'tenant_id': user.tenant.id if user.tenant else None,
                }
            )
            
            # Salvar no banco
            payment_customer = PaymentCustomer.objects.create(
                user=user,
                stripe_customer_id=stripe_customer.id
            )
            
            logger.info(f"Created Stripe customer {stripe_customer.id} for user {user.id}")
            return stripe_customer.id

    @staticmethod
    def create_credit_payment_intent(
        user: User,
        tenant: Tenant,
        credits_amount: Decimal,
        price_id: str
    ) -> Dict[str, Any]:
        """
        Cria um PaymentIntent no Stripe para compra de créditos.
        
        Args:
            user: Usuário que está comprando
            tenant: Tenant que receberá os créditos
            credits_amount: Quantidade de créditos (5, 10, 25, 50, 100)
            price_id: ID do preço no Stripe
            
        Returns:
            Dict com client_secret e payment_intent_id
        """
        
        # Mapear créditos para valores em EUR
        credit_prices = {
            Decimal('5.00'): 500,    # 5 EUR = 500 centavos
            Decimal('10.00'): 1000,  # 10 EUR = 1000 centavos
            Decimal('25.00'): 2500,  # 25 EUR = 2500 centavos
            Decimal('50.00'): 5000,  # 50 EUR = 5000 centavos
            Decimal('100.00'): 10000, # 100 EUR = 10000 centavos
        }
        
        if credits_amount not in credit_prices:
            raise ValueError(f"Invalid credits amount: {credits_amount}")
        
        amount_cents = credit_prices[credits_amount]
        
        # Obter ou criar customer no Stripe
        customer_id = get_or_create_customer(user)
        
        try:
            # Criar PaymentIntent no Stripe
            payment_intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency='eur',
                customer=customer_id,
                metadata={
                    'user_id': user.id,
                    'tenant_id': tenant.id,
                    'credits_amount': str(credits_amount),
                    'price_id': price_id,
                    'type': 'credit_purchase'
                },
                automatic_payment_methods={
                    'enabled': True,
                },
            )
            
            # Criar registro no banco
            credit_payment = CreditPayment.objects.create(
                user=user,
                tenant=tenant,
                stripe_payment_intent_id=payment_intent.id,
                stripe_customer_id=customer_id,
                stripe_price_id=price_id,
                amount=credits_amount,  # Valor em EUR
                currency='EUR',
                status='pending',
                credits_purchased=credits_amount,
                metadata={
                    'stripe_payment_intent': payment_intent.id,
                    'created_via': 'api'
                }
            )
            
            logger.info(
                f"Created PaymentIntent {payment_intent.id} for {credits_amount} credits "
                f"(User: {user.id}, Tenant: {tenant.id})"
            )
            
            return {
                'client_secret': payment_intent.client_secret,
                'payment_intent_id': payment_intent.id,
                'amount': credits_amount,
                'currency': 'EUR',
                'credits': credits_amount,
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating PaymentIntent: {str(e)}")
            raise Exception(f"Error creating payment: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating credit payment: {str(e)}")
            raise


class CreditPurchaseService:
    """Serviço para gerenciar compras de créditos."""
    
    # Mapeamento de price_id para créditos
    PRICE_TO_CREDITS = {
        settings.STRIPE_PRICE_CREDITS_5_ID: Decimal('5.00'),
        settings.STRIPE_PRICE_CREDITS_10_ID: Decimal('10.00'),
        settings.STRIPE_PRICE_CREDITS_25_ID: Decimal('25.00'),
        settings.STRIPE_PRICE_CREDITS_50_ID: Decimal('50.00'),
        settings.STRIPE_PRICE_CREDITS_100_ID: Decimal('100.00'),
    }
    
    @classmethod
    def get_credits_from_price_id(cls, price_id: str) -> Decimal:
        """Retorna a quantidade de créditos para um price_id."""
        return cls.PRICE_TO_CREDITS.get(price_id, Decimal('0.00'))
    
    @classmethod
    def get_available_credit_packages(cls) -> list:
        """Retorna os pacotes de créditos disponíveis."""
        return [
            {
                'credits': Decimal('5.00'),
                'price_eur': Decimal('5.00'),
                'price_id': settings.STRIPE_PRICE_CREDITS_5_ID,
                'description': '5 EUR Credits'
            },
            {
                'credits': Decimal('10.00'),
                'price_eur': Decimal('10.00'),
                'price_id': settings.STRIPE_PRICE_CREDITS_10_ID,
                'description': '10 EUR Credits'
            },
            {
                'credits': Decimal('25.00'),
                'price_eur': Decimal('25.00'),
                'price_id': settings.STRIPE_PRICE_CREDITS_25_ID,
                'description': '25 EUR Credits'
            },
            {
                'credits': Decimal('50.00'),
                'price_eur': Decimal('50.00'),
                'price_id': settings.STRIPE_PRICE_CREDITS_50_ID,
                'description': '50 EUR Credits'
            },
            {
                'credits': Decimal('100.00'),
                'price_eur': Decimal('100.00'),
                'price_id': settings.STRIPE_PRICE_CREDITS_100_ID,
                'description': '100 EUR Credits'
            },
        ]
    
    @classmethod
    def create_payment_intent(
        cls,
        user: User,
        tenant: Tenant,
        price_id: str
    ) -> Dict[str, Any]:
        """
        Cria um PaymentIntent para compra de créditos.
        
        Args:
            user: Usuário que está comprando
            tenant: Tenant que receberá os créditos
            price_id: ID do preço no Stripe
            
        Returns:
            Dict com informações do PaymentIntent
        """
        credits_amount = cls.get_credits_from_price_id(price_id)
        
        if credits_amount == Decimal('0.00'):
            raise ValueError(f"Invalid price_id: {price_id}")
        
        return StripePaymentService.create_credit_payment_intent(
            user=user,
            tenant=tenant,
            credits_amount=credits_amount,
            price_id=price_id
        )


class SubscriptionService:
    """Serviço para gerenciar assinaturas Stripe."""
    
    # Definição dos planos disponíveis
    AVAILABLE_PLANS = {
        'basic': {
            'name': 'Básico',
            'price_monthly': Decimal('29.00'),
            'features': [
                'Até 100 agendamentos/mês',
                'SMS e WhatsApp básico',
                '5 EUR créditos inclusos',
                'Suporte por email'
            ],
            'credits_included': Decimal('5.00')
        },
        'standard': {
            'name': 'Padrão',
            'price_monthly': Decimal('59.00'),
            'features': [
                'Até 500 agendamentos/mês',
                'SMS e WhatsApp avançado',
                '15 EUR créditos inclusos',
                'Relatórios básicos',
                'Suporte prioritário'
            ],
            'credits_included': Decimal('15.00')
        },
        'pro': {
            'name': 'Profissional',
            'price_monthly': Decimal('99.00'),
            'features': [
                'Agendamentos ilimitados',
                'SMS e WhatsApp premium',
                '30 EUR créditos inclusos',
                'Relatórios avançados',
                'API completa',
                'Suporte telefônico'
            ],
            'credits_included': Decimal('30.00')
        },
        'enterprise': {
            'name': 'Empresarial',
            'price_monthly': Decimal('199.00'),
            'features': [
                'Tudo do Profissional',
                '75 EUR créditos inclusos',
                'Integração personalizada',
                'Gerente de conta dedicado',
                'SLA garantido'
            ],
            'credits_included': Decimal('75.00')
        }
    }
    
    @classmethod
    def get_available_plans(cls, current_plan: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retorna lista de planos disponíveis com informações de upgrade."""
        plans = []
        plan_order = ['basic', 'standard', 'pro', 'enterprise']
        current_index = plan_order.index(current_plan) if current_plan in plan_order else -1
        
        for i, (plan_code, plan_info) in enumerate([(code, cls.AVAILABLE_PLANS[code]) for code in plan_order]):
            plans.append({
                'plan_code': plan_code,
                'name': plan_info['name'],
                'price_monthly': plan_info['price_monthly'],
                'features': plan_info['features'],
                'credits_included': int(plan_info['credits_included']),
                'is_current': plan_code == current_plan,
                'can_upgrade': i > current_index
            })
        
        return plans
    
    @classmethod
    def create_checkout_session(cls, user: User, plan: str, success_url: str, cancel_url: str) -> Dict[str, Any]:
        """Cria uma sessão de checkout para assinatura."""
        if plan not in cls.AVAILABLE_PLANS:
            raise ValueError(f"Plano inválido: {plan}")
        
        # Obter price_id do Stripe
        price_id = get_price_id_for_plan(plan)
        if not price_id:
            raise ValueError(f"Price ID não encontrado para o plano: {plan}")
        
        # Obter ou criar customer
        customer_id = get_or_create_customer(user)
        
        try:
            # Criar checkout session
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'user_id': user.id,
                    'tenant_id': user.tenant.id if user.tenant else None,
                    'plan': plan,
                },
                subscription_data={
                    'trial_period_days': getattr(settings, 'STRIPE_TRIAL_DAYS', 14),
                    'metadata': {
                        'user_id': user.id,
                        'tenant_id': user.tenant.id if user.tenant else None,
                        'plan': plan,
                    }
                }
            )
            
            logger.info(f"Created checkout session {session.id} for user {user.id}, plan {plan}")
            
            return {
                'checkout_url': session.url,
                'session_id': session.id
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating checkout session: {str(e)}")
            raise Exception(f"Erro ao criar sessão de checkout: {str(e)}")
    
    @classmethod
    def create_portal_session(cls, user: User, return_url: str) -> Dict[str, Any]:
        """Cria uma sessão do portal de billing."""
        customer_id = get_or_create_customer(user)
        
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            
            logger.info(f"Created portal session for user {user.id}")
            
            return {
                'portal_url': session.url
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating portal session: {str(e)}")
            raise Exception(f"Erro ao criar sessão do portal: {str(e)}")
    
    @classmethod
    def get_current_subscription(cls, user: User) -> Optional[Dict[str, Any]]:
        """Obtém informações da assinatura atual do usuário."""
        try:
            subscription = Subscription.objects.filter(
                user=user,
                status__in=['active', 'trialing', 'past_due']
            ).first()
            
            if not subscription:
                return None
            
            # Buscar dados atualizados no Stripe
            stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
            
            plan_info = cls.AVAILABLE_PLANS.get(subscription.plan, {})
            
            return {
                'plan_code': subscription.plan,
                'plan_name': plan_info.get('name', subscription.plan.title()),
                'status': stripe_sub.status,
                'current_period_end': datetime.fromtimestamp(stripe_sub.current_period_end, tz=timezone.utc),
                'cancel_at_period_end': stripe_sub.cancel_at_period_end,
                'next_billing_date': datetime.fromtimestamp(stripe_sub.current_period_end, tz=timezone.utc) if not stripe_sub.cancel_at_period_end else None,
                'price_monthly': plan_info.get('price_monthly', Decimal('0.00'))
            }
            
        except Subscription.DoesNotExist:
            return None
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error getting subscription: {str(e)}")
            return None
    
    @classmethod
    def cancel_subscription(cls, user: User, cancel_at_period_end: bool = True) -> bool:
        """Cancela a assinatura do usuário."""
        try:
            subscription = Subscription.objects.get(
                user=user,
                status__in=['active', 'trialing', 'past_due']
            )
            
            # Cancelar no Stripe
            if cancel_at_period_end:
                stripe.Subscription.modify(
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=True
                )
            else:
                stripe.Subscription.cancel(subscription.stripe_subscription_id)
            
            logger.info(f"Cancelled subscription {subscription.stripe_subscription_id} for user {user.id}")
            return True
            
        except Subscription.DoesNotExist:
            logger.warning(f"No active subscription found for user {user.id}")
            return False
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error cancelling subscription: {str(e)}")
            return False
    
    @classmethod
    def reactivate_subscription(cls, user: User) -> bool:
        """Reativa uma assinatura cancelada."""
        try:
            subscription = Subscription.objects.get(
                user=user,
                status__in=['active', 'trialing', 'past_due']
            )
            
            # Reativar no Stripe
            stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                cancel_at_period_end=False
            )
            
            logger.info(f"Reactivated subscription {subscription.stripe_subscription_id} for user {user.id}")
            return True
            
        except Subscription.DoesNotExist:
            logger.warning(f"No subscription found for user {user.id}")
            return False
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error reactivating subscription: {str(e)}")
            return False


class BillingService:
    """Serviço para gerenciar informações de billing."""
    
    @classmethod
    def get_billing_overview(cls, user: User) -> Dict[str, Any]:
        """Retorna visão geral completa do billing do usuário."""
        current_subscription = SubscriptionService.get_current_subscription(user)
        available_plans = SubscriptionService.get_available_plans(
            current_subscription['plan_code'] if current_subscription else None
        )
        
        # Obter saldo de créditos
        credit_balance = user.tenant.comm_credit_eur if user.tenant else Decimal('0.00')
        
        # Verificar se pode comprar créditos extras
        can_purchase_credits = (
            user.tenant.can_purchase_extra_credits() if user.tenant else False
        )
        
        # Verificar renovação automática de créditos (usar regra correta do Tenant)
        has_auto_renewal = (
            user.tenant.has_auto_credit_renewal() if user.tenant else False
        )
        
        # Próximo valor de cobrança
        next_billing_amount = None
        if current_subscription and not current_subscription.get('cancel_at_period_end'):
            next_billing_amount = current_subscription.get('price_monthly')
        
        return {
            'current_subscription': current_subscription,
            'available_plans': available_plans,
            'credit_balance': credit_balance,
            'can_purchase_credits': can_purchase_credits,
            'has_auto_renewal': has_auto_renewal,
            'next_billing_amount': next_billing_amount
        }
    
    @classmethod
    def get_payment_history(cls, user: User, limit: int = 50) -> Dict[str, Any]:
        """Retorna histórico de pagamentos do usuário."""
        transactions = []
        total_spent = Decimal('0.00')
        subscription_total = Decimal('0.00')
        credits_total = Decimal('0.00')
        
        # Buscar pagamentos de créditos
        credit_payments = CreditPayment.objects.filter(
            user=user,
            status='completed'
        ).order_by('-created_at')[:limit]
        
        for payment in credit_payments:
            transactions.append({
                'id': payment.stripe_payment_intent_id,
                'date': payment.created_at,
                'type': 'credit_purchase',
                'description': f'Compra de {payment.credits_purchased} EUR em créditos',
                'amount': payment.amount,
                'status': payment.status,
                'invoice_url': None
            })
            credits_total += payment.amount
            total_spent += payment.amount
        
        # Buscar faturas de assinatura do Stripe
        try:
            customer_id = get_or_create_customer(user)
            invoices = stripe.Invoice.list(
                customer=customer_id,
                limit=limit,
                status='paid'
            )
            
            for invoice in invoices.data:
                if invoice.subscription:
                    transactions.append({
                        'id': invoice.id,
                        'date': datetime.fromtimestamp(invoice.created, tz=timezone.utc),
                        'type': 'subscription',
                        'description': f'Assinatura - {invoice.lines.data[0].description if invoice.lines.data else "Plano"}',
                        'amount': Decimal(str(invoice.amount_paid / 100)),  # Converter de centavos
                        'status': 'paid',
                        'invoice_url': invoice.hosted_invoice_url
                    })
                    subscription_total += Decimal(str(invoice.amount_paid / 100))
                    total_spent += Decimal(str(invoice.amount_paid / 100))
        
        except stripe.error.StripeError as e:
            logger.error(f"Error fetching Stripe invoices: {str(e)}")
        
        # Ordenar por data (mais recente primeiro)
        transactions.sort(key=lambda x: x['date'], reverse=True)
        
        return {
            'transactions': transactions[:limit],
            'total_spent': total_spent,
            'subscription_total': subscription_total,
            'credits_total': credits_total
        }