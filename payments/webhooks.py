import logging
import stripe
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator
from django.views import View
from django.utils import timezone
from decimal import Decimal

from .models import CreditPayment, StripeWebhookEvent, PaymentCustomer, Subscription
from users.services import CreditService
from . import stripe_utils

logger = logging.getLogger(__name__)

# Configurar Stripe
stripe.api_key = settings.STRIPE_API_KEY


@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(require_POST, name="dispatch")
class StripeWebhookView(View):
    """
    View para processar webhooks do Stripe.
    Processa eventos de pagamento e aplica créditos automaticamente.
    """

    def post(self, request):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

        try:
            # Verificar assinatura do webhook
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        except ValueError:
            logger.error("Invalid payload in Stripe webhook")
            return HttpResponseBadRequest("Invalid payload")
        except stripe.error.SignatureVerificationError:
            logger.error("Invalid signature in Stripe webhook")
            return HttpResponseBadRequest("Invalid signature")

        # Verificar se já processamos este evento
        webhook_event, created = StripeWebhookEvent.objects.get_or_create(
            stripe_event_id=event["id"],
            defaults={
                "event_type": event["type"],
                "event_data": event["data"],
            },
        )

        if not created and webhook_event.processed:
            logger.info(f"Event {event['id']} already processed")
            return HttpResponse("Event already processed", status=200)

        try:
            # Processar o evento
            if event["type"] == "payment_intent.succeeded":
                self._handle_payment_succeeded(event["data"]["object"])
            elif event["type"] == "payment_intent.payment_failed":
                self._handle_payment_failed(event["data"]["object"])
            elif event["type"] in (
                "customer.subscription.created",
                "customer.subscription.updated",
            ):
                self._handle_subscription_upsert(event["data"]["object"])
            elif event["type"] == "checkout.session.completed":
                self._handle_checkout_session_completed(event["data"]["object"])
            else:
                logger.info(f"Unhandled event type: {event['type']}")

            # Marcar como processado
            webhook_event.processed = True
            webhook_event.processed_at = timezone.now()
            webhook_event.save()

        except Exception as e:
            logger.error(f"Error processing webhook {event['id']}: {str(e)}")
            webhook_event.processing_error = str(e)
            webhook_event.save()
            return HttpResponseBadRequest(f"Error processing webhook: {str(e)}")

        return HttpResponse("Webhook processed successfully", status=200)

    def _handle_checkout_session_completed(self, session):
        """Processa checkout session completed e cria/atualiza subscription."""
        try:
            # Buscar o customer
            customer_id = session.get("customer")
            subscription_id = session.get("subscription")

            if not customer_id or not subscription_id:
                logger.warning(
                    f"Missing customer or subscription in session: {session}"
                )
                return

            # Buscar PaymentCustomer
            payment_customer = PaymentCustomer.objects.filter(
                stripe_customer_id=customer_id
            ).first()

            if not payment_customer:
                logger.warning(
                    f"PaymentCustomer not found for customer_id: {customer_id}"
                )
                return

            # Buscar subscription no Stripe
            subscription = stripe.Subscription.retrieve(
                subscription_id, expand=["items.data.price"]
            )
            price_id = subscription["items"]["data"][0]["price"]["id"]

            # Criar ou atualizar subscription principal para o usuário
            sub_obj, _ = Subscription.objects.update_or_create(
                user=payment_customer.user,
                defaults={
                    "stripe_subscription_id": subscription_id,
                    "price_id": price_id,
                    "status": subscription["status"],
                },
            )

            # Cancelar quaisquer outras assinaturas ativas do mesmo tenant
            if payment_customer.user and payment_customer.user.tenant:
                tenant = payment_customer.user.tenant
                others = Subscription.objects.filter(
                    user__tenant=tenant,
                    status__in=["active", "trialing", "past_due"],
                ).exclude(stripe_subscription_id=subscription_id)

                for old in others:
                    try:
                        stripe.Subscription.cancel(old.stripe_subscription_id)
                        old.status = "canceled"
                        old.cancel_at_period_end = False
                        old.save(update_fields=["status", "cancel_at_period_end"])
                        logger.info(
                            f"Cancelled previous subscription {old.stripe_subscription_id} for tenant {tenant.id}"
                        )
                    except Exception as ce:
                        logger.error(
                            f"Failed to cancel previous subscription {old.stripe_subscription_id}: {ce}"
                        )

            # Cancelar no Stripe todas as assinaturas ativas do mesmo customer, exceto a atual
            try:
                subs = stripe.Subscription.list(customer=customer_id)
                for item in subs.get("data", []):
                    sid = item.get("id")
                    status = item.get("status")
                    if (
                        sid
                        and sid != subscription_id
                        and status
                        in [
                            "active",
                            "trialing",
                            "past_due",
                        ]
                    ):
                        try:
                            stripe.Subscription.delete(sid)
                            logger.info(
                                f"Cancelled previous Stripe subscription {sid} for customer {customer_id}"
                            )
                        except Exception as ce:
                            logger.error(
                                f"Failed to cancel Stripe subscription {sid}: {ce}"
                            )
            except Exception:
                # Ignorar falha de list/cancel para manter fluxo principal
                pass

            # Atualizar feature flags do usuário
            plan_code = stripe_utils.get_plan_code_from_price(price_id)
            if plan_code:
                flags = payment_customer.user.featureflags
                if plan_code == "pro":
                    flags.is_pro = True
                    flags.pro_plan = "pro"
                elif plan_code == "basic":
                    flags.is_basic = True
                    flags.basic_plan = "basic"
                elif plan_code == "standard":
                    flags.is_standard = True
                    flags.standard_plan = "standard"
                elif plan_code == "enterprise":
                    flags.is_enterprise = True
                    flags.enterprise_plan = "enterprise"
                flags.save()

                # Atualizar tenant plan_tier
                tenant = payment_customer.user.tenant
                if tenant:
                    tenant.plan_tier = plan_code
                    tenant.save()

            logger.info(
                f"Subscription created/updated for user {payment_customer.user.id}"
            )

        except Exception as e:
            logger.error(f"Error handling checkout session completed: {str(e)}")
            raise

    def _handle_subscription_upsert(self, subscription_obj):
        try:
            customer_id = subscription_obj.get("customer")
            subscription_id = subscription_obj.get("id")
            items = subscription_obj.get("items", {}).get("data", [])
            price_id = None
            if items:
                price = items[0].get("price")
                price_id = price.get("id") if isinstance(price, dict) else price

            if not customer_id or not subscription_id or not price_id:
                logger.warning(
                    f"Missing fields in subscription update: {subscription_obj}"
                )
                return

            payment_customer = PaymentCustomer.objects.filter(
                stripe_customer_id=customer_id
            ).first()
            if not payment_customer:
                logger.warning(
                    f"PaymentCustomer not found for customer_id: {customer_id}"
                )
                return

            Subscription.objects.update_or_create(
                user=payment_customer.user,
                defaults={
                    "stripe_subscription_id": subscription_id,
                    "price_id": price_id,
                    "status": subscription_obj.get("status", "active"),
                },
            )

            plan_code = stripe_utils.get_plan_code_from_price(price_id)
            if plan_code:
                flags = payment_customer.user.featureflags
                flags.is_basic = plan_code == "basic"
                flags.is_standard = plan_code == "standard"
                flags.is_pro = plan_code == "pro"
                flags.is_enterprise = plan_code == "enterprise"
                flags.basic_plan = "basic" if flags.is_basic else None
                flags.standard_plan = "standard" if flags.is_standard else None
                flags.pro_plan = "pro" if flags.is_pro else None
                flags.enterprise_plan = "enterprise" if flags.is_enterprise else None
                flags.save()

                tenant = payment_customer.user.tenant
                if tenant:
                    tenant.plan_tier = plan_code
                    tenant.save()

            # Cancelar outras assinaturas do tenant
            if payment_customer.user and payment_customer.user.tenant:
                tenant = payment_customer.user.tenant
                others = Subscription.objects.filter(
                    user__tenant=tenant,
                    status__in=["active", "trialing", "past_due"],
                ).exclude(stripe_subscription_id=subscription_id)
                for old in others:
                    try:
                        stripe.Subscription.delete(old.stripe_subscription_id)
                        old.status = "canceled"
                        old.cancel_at_period_end = False
                        old.save(update_fields=["status", "cancel_at_period_end"])
                    except Exception as ce:
                        logger.error(
                            f"Failed to cancel previous subscription {old.stripe_subscription_id}: {ce}"
                        )

            # Cancelar diretamente no Stripe todas as assinaturas do customer, exceto a atual
            subs = stripe.Subscription.list(customer=customer_id)
            for item in subs.get("data", []):
                sid = item.get("id")
                status = item.get("status")
                if (
                    sid
                    and sid != subscription_id
                    and status
                    in [
                        "active",
                        "trialing",
                        "past_due",
                    ]
                ):
                    try:
                        stripe.Subscription.delete(sid)
                    except Exception as ce:
                        logger.error(
                            f"Failed to cancel Stripe subscription {sid}: {ce}"
                        )

        except Exception as e:
            logger.error(f"Error handling subscription upsert: {str(e)}")
            raise

    def _handle_payment_succeeded(self, payment_intent):
        """Processa pagamento bem-sucedido e aplica créditos."""
        try:
            # Buscar o pagamento no banco
            credit_payment = CreditPayment.objects.get(
                stripe_payment_intent_id=payment_intent["id"]
            )

            # Atualizar status do pagamento
            credit_payment.status = "succeeded"
            credit_payment.completed_at = timezone.now()

            # Aplicar créditos se ainda não foram aplicados
            if not credit_payment.credits_applied:
                tenant = credit_payment.tenant

                # Usar CreditService para registrar ledger e atualizar saldo
                cs = CreditService(tenant)
                cs.add_credits(
                    amount=credit_payment.credits_purchased,
                    transaction_type="purchase",
                    description="Compra de créditos via Stripe",
                    reference_id=payment_intent["id"],
                    created_by=credit_payment.user,
                )

                # Marcar créditos como aplicados
                credit_payment.credits_applied = True

                logger.info(
                    f"Applied {credit_payment.credits_purchased} credits to tenant {tenant.name} "
                    f"(Payment: {payment_intent['id']})"
                )

            credit_payment.save()

        except CreditPayment.DoesNotExist:
            logger.error(
                f"CreditPayment not found for payment_intent: {payment_intent['id']}"
            )
            raise Exception(f"Payment not found: {payment_intent['id']}")

    def _handle_payment_failed(self, payment_intent):
        """Processa pagamento falhado."""
        try:
            credit_payment = CreditPayment.objects.get(
                stripe_payment_intent_id=payment_intent["id"]
            )

            credit_payment.status = "failed"
            credit_payment.completed_at = timezone.now()
            credit_payment.save()

            logger.info(f"Payment failed: {payment_intent['id']}")

        except CreditPayment.DoesNotExist:
            logger.error(
                f"CreditPayment not found for failed payment: {payment_intent['id']}"
            )
            raise Exception(f"Payment not found: {payment_intent['id']}")


# Função auxiliar para mapear price_id para créditos
def get_credits_from_price_id(price_id: str) -> Decimal:
    """Mapeia price_id do Stripe para quantidade de créditos."""
    price_mapping = {
        settings.STRIPE_PRICE_CREDITS_5_ID: Decimal("5.00"),
        settings.STRIPE_PRICE_CREDITS_10_ID: Decimal("10.00"),
        settings.STRIPE_PRICE_CREDITS_25_ID: Decimal("25.00"),
        settings.STRIPE_PRICE_CREDITS_50_ID: Decimal("50.00"),
        settings.STRIPE_PRICE_CREDITS_100_ID: Decimal("100.00"),
    }

    return price_mapping.get(price_id, Decimal("0.00"))
