import stripe
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Any

from django.conf import settings

from .models import PaymentCustomer, Subscription, CreditPayment
from users.models import Tenant
from .stripe_utils import (
    get_or_create_customer,
    get_price_id_for_plan,
    get_plan_code_from_price,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser as UserType
else:
    UserType = Any

logger = logging.getLogger(__name__)

# Configurar Stripe
stripe.api_key = settings.STRIPE_API_KEY


class StripePaymentService:
    """Serviço para gerenciar pagamentos com Stripe."""

    @staticmethod
    def get_or_create_customer(user: UserType) -> str:
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
                    "user_id": user.id,
                    "tenant_id": user.tenant.id if user.tenant else None,
                },
            )

            # Salvar no banco
            payment_customer = PaymentCustomer.objects.create(
                user=user, stripe_customer_id=stripe_customer.id
            )

            logger.info(
                f"Created Stripe customer {stripe_customer.id} for user {user.id}"
            )
            return stripe_customer.id

    @staticmethod
    def create_credit_payment_intent(
        user: UserType, tenant: Tenant, credits_amount: Decimal, price_id: str
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
            Decimal("5.00"): 500,  # 5 EUR = 500 centavos
            Decimal("10.00"): 1000,  # 10 EUR = 1000 centavos
            Decimal("25.00"): 2500,  # 25 EUR = 2500 centavos
            Decimal("50.00"): 5000,  # 50 EUR = 5000 centavos
            Decimal("100.00"): 10000,  # 100 EUR = 10000 centavos
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
                currency="eur",
                customer=customer_id,
                metadata={
                    "user_id": user.id,
                    "tenant_id": tenant.id,
                    "credits_amount": str(credits_amount),
                    "price_id": price_id,
                    "type": "credit_purchase",
                },
                automatic_payment_methods={
                    "enabled": True,
                },
            )

            # Criar registro no banco
            CreditPayment.objects.create(
                user=user,
                tenant=tenant,
                stripe_payment_intent_id=payment_intent.id,
                stripe_customer_id=customer_id,
                stripe_price_id=price_id,
                amount=credits_amount,  # Valor em EUR
                currency="EUR",
                status="pending",
                credits_purchased=credits_amount,
                metadata={
                    "stripe_payment_intent": payment_intent.id,
                    "created_via": "api",
                },
            )

            logger.info(
                f"Created PaymentIntent {payment_intent.id} for {credits_amount} credits "
                f"(User: {user.id}, Tenant: {tenant.id})"
            )

            return {
                "client_secret": payment_intent.client_secret,
                "payment_intent_id": payment_intent.id,
                "amount": credits_amount,
                "currency": "EUR",
                "credits": credits_amount,
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
        settings.STRIPE_PRICE_CREDITS_5_ID: Decimal("5.00"),
        settings.STRIPE_PRICE_CREDITS_10_ID: Decimal("10.00"),
        settings.STRIPE_PRICE_CREDITS_25_ID: Decimal("25.00"),
        settings.STRIPE_PRICE_CREDITS_50_ID: Decimal("50.00"),
        settings.STRIPE_PRICE_CREDITS_100_ID: Decimal("100.00"),
    }

    @classmethod
    def get_credits_from_price_id(cls, price_id: str) -> Decimal:
        """Retorna a quantidade de créditos para um price_id."""
        return cls.PRICE_TO_CREDITS.get(price_id, Decimal("0.00"))

    @classmethod
    def get_available_credit_packages(cls) -> list:
        """Retorna os pacotes de créditos disponíveis."""
        return [
            {
                "credits": Decimal("5.00"),
                "price_eur": Decimal("5.00"),
                "price_id": settings.STRIPE_PRICE_CREDITS_5_ID,
                "description": "Créditos de 5 EUR",
            },
            {
                "credits": Decimal("10.00"),
                "price_eur": Decimal("10.00"),
                "price_id": settings.STRIPE_PRICE_CREDITS_10_ID,
                "description": "Créditos de 10 EUR",
            },
            {
                "credits": Decimal("25.00"),
                "price_eur": Decimal("25.00"),
                "price_id": settings.STRIPE_PRICE_CREDITS_25_ID,
                "description": "Créditos de 25 EUR",
            },
            {
                "credits": Decimal("50.00"),
                "price_eur": Decimal("50.00"),
                "price_id": settings.STRIPE_PRICE_CREDITS_50_ID,
                "description": "Créditos de 50 EUR",
            },
            {
                "credits": Decimal("100.00"),
                "price_eur": Decimal("100.00"),
                "price_id": settings.STRIPE_PRICE_CREDITS_100_ID,
                "description": "Créditos de 100 EUR",
            },
        ]

    @classmethod
    def create_payment_intent(
        cls, user: UserType, tenant: Tenant, price_id: str
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

        if credits_amount == Decimal("0.00"):
            raise ValueError(f"Invalid price_id: {price_id}")

        return StripePaymentService.create_credit_payment_intent(
            user=user, tenant=tenant, credits_amount=credits_amount, price_id=price_id
        )


class SubscriptionService:
    """Serviço para gerenciar assinaturas Stripe."""

    # Definição dos planos disponíveis
    # BE-PLANS-01 (#481): o Basic absorveu as features que eram exclusivas do Pro
    # (preço e créditos inalterados). O Pro permanece definido apenas como
    # referência histórica/reativação futura — está em Tenant.BLOCKED_PLANS e não
    # aparece em listagens públicas nem pode ser contratado.
    AVAILABLE_PLANS = {
        "basic": {
            "name": "Basic",
            "price_monthly": Decimal("29.00"),
            "features": [
                "PWA Admin/Manager/Staff/Client",
                "Apps Nativos (Admin/Staff/Client)",
                "Relatórios completos (Overview + Business + Insights)",
                "White‑label e Domínio personalizado",
                "Email, web push e notificações avançadas (SMS/WhatsApp)",
            ],
            "credits_included": Decimal("5.00"),
            "comm_extra_allowed": True,
            "comm_auto_renew": False,
        },
        "pro": {
            "name": "Pro",
            "price_monthly": Decimal("55.00"),
            "features": [
                "Tudo do Basic",
                "Apps Nativos (Admin/Staff/Client)",
                "Relatórios Avançados (Business + Insights)",
                "White‑label e Domínio personalizado",
            ],
            "credits_included": Decimal("15.00"),
            "comm_extra_allowed": True,
            "comm_auto_renew": True,
        },
    }

    @classmethod
    def get_available_plans(
        cls, current_plan: Optional[str] = None, tenant: Optional["Tenant"] = None
    ) -> List[Dict[str, Any]]:
        """
        Retorna lista de planos disponíveis com informações de upgrade.

        Args:
            current_plan: Código do plano atual do usuário
            tenant: Tenant do usuário para verificar elegibilidade (esp. para Founder)

        Returns:
            Lista de planos com informações de disponibilidade
        """
        from users.services import FounderService

        plans = []
        # BE-PLANS-01 (#481): planos bloqueados não aparecem na listagem pública.
        plan_order = [
            code for code in ["basic", "pro"] if not Tenant.is_plan_blocked(code)
        ]
        current_index = (
            plan_order.index(current_plan) if current_plan in plan_order else -1
        )

        for i, (plan_code, plan_info) in enumerate(
            [(code, cls.AVAILABLE_PLANS[code]) for code in plan_order]
        ):
            plans.append(
                {
                    "plan_code": plan_code,
                    "name": plan_info["name"],
                    "price_monthly": plan_info["price_monthly"],
                    "features": plan_info["features"],
                    "credits_included": int(plan_info["credits_included"]),
                    "comm_extra_allowed": bool(
                        plan_info.get("comm_extra_allowed", True)
                    ),
                    "comm_auto_renew": bool(plan_info.get("comm_auto_renew", False)),
                    "is_current": plan_code == current_plan,
                    "can_upgrade": i > current_index,
                    "is_available": True,  # Planos padrão sempre disponíveis
                }
            )

        # Adicionar plano Founder se disponível globalmente
        founder_available = FounderService.can_assign_founder(tenant=tenant)
        if founder_available:
            plans.insert(
                0,
                {
                    "plan_code": "founder",
                    "name": "Founder",
                    "price_monthly": Decimal("15.00"),
                    "features": [
                        "Preço Vitalício",
                        "PWA Admin, Staff e Client",
                        "Relatórios: Visão Geral",
                        "€2 de crédito para comunicações",
                    ],
                    "credits_included": int(Decimal("2.00")),
                    "comm_extra_allowed": True,
                    "comm_auto_renew": False,
                    "is_current": current_plan == "founder",
                    "can_upgrade": False,  # Founder não é upgrade, é uma oferta única
                    "is_available": founder_available,
                },
            )

        logger.debug(
            "get_available_plans resolved",
            extra={
                "tenant_id": getattr(tenant, "id", None),
                "founder_available": founder_available,
                "plans": [p["plan_code"] for p in plans],
            },
        )
        return plans

    @classmethod
    def create_checkout_session(
        cls,
        user: UserType,
        plan: str,
        success_url: str,
        cancel_url: str,
        interval: str = "monthly",
    ) -> Dict[str, Any]:
        """Cria uma sessão de checkout para assinatura."""
        if plan not in cls.AVAILABLE_PLANS:
            raise ValueError(f"Plano inválido: {plan}")

        # Obter price_id do Stripe
        price_id = get_price_id_for_plan(plan, interval=interval)
        if not price_id:
            raise ValueError(
                f"Price ID não encontrado para o plano: {plan} ({interval})"
            )

        # Obter ou criar customer
        customer_id = get_or_create_customer(user)

        try:
            # BE-PLANS-02: subscrições `incomplete` (checkout abandonado) não consomem
            # o trial — alinhado com o checkout legado (payments/views.py) e a overview.
            has_existing = (
                Subscription.objects.filter(user__tenant=user.tenant)
                .exclude(status__in=["incomplete", "incomplete_expired"])
                .exists()
            )
            trial_days = getattr(settings, "STRIPE_TRIAL_PERIOD_DAYS", None)
            if trial_days is None:
                trial_days = getattr(settings, "STRIPE_TRIAL_DAYS", 0)

            subscription_data: Dict[str, Any] = {
                "metadata": {
                    "user_id": user.id,
                    "tenant_id": user.tenant.id if user.tenant else None,
                    "plan_code": plan,
                    "interval": interval,
                },
            }
            if trial_days and not has_existing:
                subscription_data["trial_period_days"] = trial_days
            else:
                subscription_data["trial_from_plan"] = False

            # Criar checkout session
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[
                    {
                        "price": price_id,
                        "quantity": 1,
                    }
                ],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": user.id,
                    "tenant_id": user.tenant.id if user.tenant else None,
                    "plan_code": plan,
                    "interval": interval,
                },
                subscription_data=subscription_data,
            )

            logger.info(
                f"Created checkout session {session.id} for user {user.id}, plan {plan}"
            )

            return {"checkout_url": session.url, "session_id": session.id}

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating checkout session: {str(e)}")
            raise Exception(f"Erro ao criar sessão de checkout: {str(e)}")

    @classmethod
    def create_portal_session(cls, user: UserType, return_url: str) -> Dict[str, Any]:
        """Cria uma sessão do portal de billing."""
        customer_id = get_or_create_customer(user)

        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )

            logger.info(f"Created portal session for user {user.id}")

            return {"portal_url": session.url}

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating portal session: {str(e)}")
            raise Exception(f"Erro ao criar sessão do portal: {str(e)}")

    @classmethod
    def get_current_subscription(cls, user: UserType) -> Optional[Dict[str, Any]]:
        tenant = getattr(user, "tenant", None)
        if tenant and hasattr(tenant, "is_promotional_billing"):
            if tenant.is_promotional_billing():
                # Conta promocional não deve reconciliar com Stripe.
                return None

        subscription = None
        try:
            subscription = (
                Subscription.objects.filter(
                    user__tenant=user.tenant,
                    status__in=["active", "trialing", "past_due"],
                )
                .order_by("-updated_at", "-created_at")
                .first()
            )

            if not subscription:
                return None

            if not subscription.stripe_subscription_id:
                logger.info(
                    "No Stripe subscription id for tenant; treating as no active subscription",
                    extra={
                        "user_id": getattr(user, "id", None),
                        "tenant_id": getattr(getattr(user, "tenant", None), "id", None),
                    },
                )
                return None

            stripe_sub = stripe.Subscription.retrieve(
                subscription.stripe_subscription_id
            )

            price_id = None
            interval = "month"
            try:
                price_obj = stripe_sub.items.data[0].price
                price_id = price_obj.id
                if hasattr(price_obj, "recurring") and hasattr(
                    price_obj.recurring, "interval"
                ):
                    interval = price_obj.recurring.interval
            except Exception:
                price_id = None
                interval = "month"

            plan_code = None
            try:
                metadata: Dict[str, Any] = getattr(stripe_sub, "metadata", {}) or {}
                plan_code = metadata.get("plan_code") or metadata.get("plan")
                if plan_code:
                    plan_code = plan_code.lower()
            except Exception:
                plan_code = None
            if not plan_code:
                plan_code = get_plan_code_from_price(price_id)

            plan_info = cls.AVAILABLE_PLANS.get(plan_code or "", {})

            # Campos tolerantes a ausência no Stripe
            status = getattr(stripe_sub, "status", None)
            cancel_at_period_end = bool(
                getattr(stripe_sub, "cancel_at_period_end", False)
            )
            cpe_ts = getattr(stripe_sub, "current_period_end", None)
            cpe_dt = None
            try:
                if cpe_ts:
                    cpe_dt = datetime.fromtimestamp(cpe_ts, tz=timezone.utc)
            except Exception:
                cpe_dt = None

            # Atualizar cache local para garantir sincronia com Admin
            try:
                if status:
                    subscription.status = status
                subscription.cancel_at_period_end = cancel_at_period_end
                if cpe_dt:
                    subscription.current_period_end = cpe_dt
                subscription.save(
                    update_fields=[
                        "status",
                        "cancel_at_period_end",
                        "current_period_end",
                    ]
                )
            except Exception as e:
                logger.error(f"Error updating local subscription cache: {e}")

            next_billing = None
            try:
                if cpe_ts and not cancel_at_period_end:
                    next_billing = datetime.fromtimestamp(cpe_ts, tz=timezone.utc)
            except Exception:
                next_billing = None

            # Tradução de status
            STATUS_TRANSLATIONS = {
                "active": "Ativo",
                "trialing": "Em teste",
                "past_due": "Pagamento Pendente",
                "canceled": "Cancelado",
                "unpaid": "Não pago",
                "incomplete": "Incompleto",
                "incomplete_expired": "Expirado",
            }
            status_label = STATUS_TRANSLATIONS.get(status, status)

            return {
                "plan_code": plan_code,
                "plan_name": plan_info.get("name", (plan_code or "").title()),
                "status": status,
                "status_label": status_label,
                "current_period_end": cpe_dt,
                "cancel_at_period_end": cancel_at_period_end,
                "next_billing_date": next_billing,
                "price_monthly": plan_info.get("price_monthly", Decimal("0.00")),
                "interval": interval,
            }

        except Subscription.DoesNotExist:
            return None
        except Exception as e:
            msg = str(e)
            lower_msg = msg.lower()
            if "no such subscription" in lower_msg or "resource_missing" in lower_msg:
                logger.info(
                    "Stripe subscription missing; using local subscription state",
                    extra={
                        "user_id": getattr(user, "id", None),
                        "tenant_id": getattr(getattr(user, "tenant", None), "id", None),
                        "stripe_subscription_id": getattr(
                            subscription, "stripe_subscription_id", None
                        ),
                    },
                )

                try:
                    sub = (
                        Subscription.objects.filter(
                            user__tenant=user.tenant,
                            status__in=["active", "trialing", "past_due"],
                        )
                        .order_by("-updated_at", "-created_at")
                        .first()
                    )
                    if not sub:
                        return None
                    plan_code = get_plan_code_from_price(sub.price_id)
                    plan_info = cls.AVAILABLE_PLANS.get(plan_code or "", {})

                    STATUS_TRANSLATIONS = {
                        "active": "Ativo",
                        "trialing": "Em teste",
                        "past_due": "Pagamento Pendente",
                        "canceled": "Cancelado",
                        "unpaid": "Não pago",
                        "incomplete": "Incompleto",
                        "incomplete_expired": "Expirado",
                    }
                    status_label = STATUS_TRANSLATIONS.get(sub.status, sub.status)

                    return {
                        "plan_code": plan_code,
                        "plan_name": plan_info.get("name", (plan_code or "").title()),
                        "status": sub.status,
                        "status_label": status_label,
                        "current_period_end": sub.current_period_end,
                        "cancel_at_period_end": sub.cancel_at_period_end,
                        "next_billing_date": sub.current_period_end,
                        "price_monthly": plan_info.get(
                            "price_monthly", Decimal("0.00")
                        ),
                    }
                except Exception:
                    return None

            logger.error(f"Stripe error getting subscription: {msg}")
            # Ainda retornar mínima info usando registro local
            try:
                sub = (
                    Subscription.objects.filter(
                        user__tenant=user.tenant,
                        status__in=["active", "trialing", "past_due"],
                    )
                    .order_by("-updated_at", "-created_at")
                    .first()
                )
                if not sub:
                    return None
                plan_code = get_plan_code_from_price(sub.price_id)
                plan_info = cls.AVAILABLE_PLANS.get(plan_code or "", {})

                STATUS_TRANSLATIONS = {
                    "active": "Ativo",
                    "trialing": "Em teste",
                    "past_due": "Pagamento Pendente",
                    "canceled": "Cancelado",
                    "unpaid": "Não pago",
                    "incomplete": "Incompleto",
                    "incomplete_expired": "Expirado",
                }
                status_label = STATUS_TRANSLATIONS.get(sub.status, sub.status)

                return {
                    "plan_code": plan_code,
                    "plan_name": plan_info.get("name", (plan_code or "").title()),
                    "status": sub.status,
                    "status_label": status_label,
                    "current_period_end": sub.current_period_end,
                    "cancel_at_period_end": sub.cancel_at_period_end,
                    "next_billing_date": sub.current_period_end,
                    "price_monthly": plan_info.get("price_monthly", Decimal("0.00")),
                }
            except Exception:
                return None

    @classmethod
    def cancel_subscription(
        cls, user: UserType, cancel_at_period_end: bool = True
    ) -> bool:
        """Cancela a assinatura do usuário."""
        try:
            subscription = Subscription.objects.get(
                user=user, status__in=["active", "trialing", "past_due"]
            )

            # Cancelar no Stripe
            if cancel_at_period_end:
                stripe.Subscription.modify(
                    subscription.stripe_subscription_id, cancel_at_period_end=True
                )
                # Atualizar estado local imediatamente para refletir na UI
                subscription.cancel_at_period_end = True
                subscription.save(update_fields=["cancel_at_period_end"])
            else:
                stripe.Subscription.cancel(subscription.stripe_subscription_id)
                # Atualizar estado local
                subscription.status = "canceled"
                subscription.save(update_fields=["status"])

            logger.info(
                f"Cancelled subscription {subscription.stripe_subscription_id} for user {user.id}"
            )
            return True

        except Subscription.DoesNotExist:
            logger.warning(f"No active subscription found for user {user.id}")
            return False
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error cancelling subscription: {str(e)}")
            return False

    @classmethod
    def reactivate_subscription(cls, user: UserType) -> bool:
        """Reativa uma assinatura cancelada."""
        try:
            subscription = Subscription.objects.get(
                user=user, status__in=["active", "trialing", "past_due"]
            )

            # Reativar no Stripe
            stripe.Subscription.modify(
                subscription.stripe_subscription_id, cancel_at_period_end=False
            )
            # Atualizar estado local imediatamente para refletir na UI
            subscription.cancel_at_period_end = False
            subscription.save(update_fields=["cancel_at_period_end"])

            logger.info(
                f"Reactivated subscription {subscription.stripe_subscription_id} for user {user.id}"
            )
            return True

        except Subscription.DoesNotExist:
            logger.warning(f"No subscription found for user {user.id}")
            return False
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error reactivating subscription: {str(e)}")
            return False

    @classmethod
    def cancel_tenant_subscriptions(cls, tenant) -> Dict[str, Any]:
        """
        Cancela todas as assinaturas ativas de um tenant (BE-ACCOUNT-CANCEL #396).

        Args:
            tenant: Instância do Tenant cujas subscriptions devem ser canceladas

        Returns:
            Dict com estatísticas: {
                "success": bool,
                "cancelled_count": int,
                "failed_count": int,
                "errors": List[str]
            }
        """
        from users.models import CustomUser

        result = {
            "success": True,
            "cancelled_count": 0,
            "failed_count": 0,
            "errors": [],
        }

        try:
            # Buscar todos os usuários do tenant com subscriptions ativas
            tenant_users = CustomUser.objects.filter(tenant=tenant)
            active_subscriptions = Subscription.objects.filter(
                user__in=tenant_users, status__in=["active", "trialing", "past_due"]
            )

            for subscription in active_subscriptions:
                try:
                    # Cancelar imediatamente no Stripe (não aguardar fim do período)
                    stripe.Subscription.cancel(subscription.stripe_subscription_id)

                    # Atualizar estado local
                    subscription.status = "canceled"
                    subscription.cancel_at_period_end = False
                    subscription.save(update_fields=["status", "cancel_at_period_end"])

                    result["cancelled_count"] += 1
                    logger.info(
                        f"Cancelled subscription {subscription.stripe_subscription_id} "
                        f"for tenant {tenant.id} (user {subscription.user.id})"
                    )

                except stripe.error.StripeError as e:
                    result["failed_count"] += 1
                    result["success"] = False
                    error_msg = f"Stripe error cancelling {subscription.stripe_subscription_id}: {str(e)}"
                    result["errors"].append(error_msg)
                    logger.error(error_msg)

                except Exception as e:
                    result["failed_count"] += 1
                    result["success"] = False
                    error_msg = f"Unexpected error cancelling {subscription.stripe_subscription_id}: {str(e)}"
                    result["errors"].append(error_msg)
                    logger.error(error_msg)

            if result["cancelled_count"] == 0 and result["failed_count"] == 0:
                logger.info(f"No active subscriptions found for tenant {tenant.id}")

            return result

        except Exception as e:
            result["success"] = False
            result["errors"].append(f"Failed to query subscriptions: {str(e)}")
            logger.error(
                f"Error in cancel_tenant_subscriptions for tenant {tenant.id}: {str(e)}"
            )
            return result


class BillingService:
    """Serviço para gerenciar informações de billing."""

    @classmethod
    def get_billing_overview(cls, user: UserType) -> Dict[str, Any]:
        """Retorna visão geral completa do billing do usuário."""
        current_subscription = SubscriptionService.get_current_subscription(user)
        available_plans = SubscriptionService.get_available_plans(
            current_subscription["plan_code"] if current_subscription else None
        )

        # Obter saldo de créditos
        credit_balance = user.tenant.comm_credit_eur if user.tenant else Decimal("0.00")

        # Verificar se pode comprar créditos extras (método => bool)
        can_purchase_credits = (
            user.tenant.can_purchase_extra_credits() if user.tenant else False
        )

        # Verificar renovação automática de créditos (usar regra correta do Tenant)
        # NOTA: O frontend espera 'has_auto_renewal' como status da assinatura, mas aqui
        # estamos retornando a renovação automática de créditos.
        # Vamos ajustar para retornar também o status da assinatura se existir.
        has_auto_renewal = False
        if current_subscription:
            has_auto_renewal = not current_subscription.get(
                "cancel_at_period_end", False
            )
        elif user.tenant:
            # Fallback para créditos se não houver assinatura ativa
            has_auto_renewal = user.tenant.has_auto_credit_renewal()

        # Próximo valor de cobrança
        next_billing_amount = None
        if current_subscription and not current_subscription.get(
            "cancel_at_period_end"
        ):
            next_billing_amount = current_subscription.get("price_monthly")

        # Elegibilidade de trial
        trial_days_cfg = getattr(settings, "STRIPE_TRIAL_PERIOD_DAYS", None)
        if trial_days_cfg is None:
            trial_days_cfg = getattr(settings, "STRIPE_TRIAL_DAYS", 0)
        # BE-PLANS-02: subscrições `incomplete` (checkout abandonado) não consomem o
        # trial — alinhado com o checkout legado e o checkout v2.
        has_any_subscription = (
            Subscription.objects.filter(user__tenant=user.tenant)
            .exclude(status__in=["incomplete", "incomplete_expired"])
            .exists()
        )
        trial_eligible = bool(trial_days_cfg) and not has_any_subscription
        trial_exhausted = bool(has_any_subscription) and not (
            current_subscription and current_subscription.get("status") == "trialing"
        )

        return {
            "current_subscription": current_subscription,
            "available_plans": available_plans,
            "credit_balance": credit_balance,
            "can_purchase_credits": can_purchase_credits,
            "has_auto_renewal": has_auto_renewal,
            "next_billing_amount": next_billing_amount,
            "trial_eligible": trial_eligible,
            "trial_days": int(trial_days_cfg or 0),
            "trial_exhausted": trial_exhausted,
        }

    @classmethod
    def get_payment_history(cls, user: UserType, limit: int = 50) -> Dict[str, Any]:
        """Retorna histórico de pagamentos do usuário."""
        transactions = []
        total_spent = Decimal("0.00")
        subscription_total = Decimal("0.00")
        credits_total = Decimal("0.00")

        # Buscar pagamentos de créditos
        credit_payments = CreditPayment.objects.filter(
            user=user, status="completed"
        ).order_by("-created_at")[:limit]

        for payment in credit_payments:
            transactions.append(
                {
                    "id": payment.stripe_payment_intent_id,
                    "date": payment.created_at,
                    "type": "credit_purchase",
                    "description": f"Compra de {payment.credits_purchased} EUR em créditos",
                    "amount": payment.amount,
                    "status": payment.status,
                    "invoice_url": None,
                }
            )
            credits_total += payment.amount
            total_spent += payment.amount

        # Buscar faturas de assinatura do Stripe
        try:
            customer_id = get_or_create_customer(user)
            invoices = stripe.Invoice.list(
                customer=customer_id, limit=limit, status="paid"
            )

            for invoice in invoices.data:
                if invoice.subscription:
                    transactions.append(
                        {
                            "id": invoice.id,
                            "date": datetime.fromtimestamp(
                                invoice.created, tz=timezone.utc
                            ),
                            "type": "subscription",
                            "description": f"Assinatura - {invoice.lines.data[0].description if invoice.lines.data else 'Plano'}",
                            "amount": Decimal(
                                str(invoice.amount_paid / 100)
                            ),  # Converter de centavos
                            "status": "paid",
                            "invoice_url": invoice.hosted_invoice_url,
                        }
                    )
                    subscription_total += Decimal(str(invoice.amount_paid / 100))
                    total_spent += Decimal(str(invoice.amount_paid / 100))

        except stripe.error.StripeError as e:
            logger.error(f"Error fetching Stripe invoices: {str(e)}")

        # Ordenar por data (mais recente primeiro)
        transactions.sort(key=lambda x: x["date"], reverse=True)

        return {
            "transactions": transactions[:limit],
            "total_spent": total_spent,
            "subscription_total": subscription_total,
            "credits_total": credits_total,
        }
