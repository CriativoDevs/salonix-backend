import logging
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema

import stripe
import json

from . import stripe_utils
from .models import Subscription, PaymentCustomer, CreditPayment, StripeWebhookEvent
from users.services import CreditService
from .services import (
    CreditPurchaseService,
    SubscriptionService,
    BillingService,
)
from .serializers import (
    CheckoutSessionRequestSerializer,
    CheckoutSessionResponseSerializer,
    PortalSessionResponseSerializer,
    CreditPurchaseRequestSerializer,
    CheckoutSessionResponseSerializer as CreditCheckoutSessionResponseSerializer,
    CreditPurchaseResponseSerializer,
    AvailableCreditPackagesResponseSerializer,
    AvailablePlansSerializer,
    CurrentSubscriptionSerializer,
    PaymentHistorySerializer,
    BillingOverviewSerializer,
    SubscriptionActionSerializer,
    StripeSettingsUpdateRequestSerializer,
    StripeSettingsResponseSerializer,
)
from .observability import PAYMENTS_SETTINGS_UPDATED_TOTAL
from users.models import Tenant, TenantStaffMember

logger = logging.getLogger(__name__)


class CreateCheckoutSession(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CheckoutSessionRequestSerializer,
        responses={200: CheckoutSessionResponseSerializer},
    )
    def post(self, request):
        """Cria uma Checkout Session apontando para o plano escolhido."""
        stripe_utils.get_stripe()

        requested_plan = (request.data.get("plan") or "basic").lower()
        allowed_plans = {
            "basic",
            "standard",
            "pro",
            "enterprise",
        }

        if requested_plan not in allowed_plans:
            return Response({"detail": "Plano inválido."}, status=400)

        price_id = stripe_utils.get_price_id_for_plan(requested_plan)
        if not price_id:
            return Response(
                {"detail": "Price ID não configurado para o plano informado."},
                status=500,
            )

        canonical_plan = requested_plan

        # 3) Permissão: somente OWNER ativo do tenant pode criar checkout
        staff = getattr(request.user, "staff_member", None)
        tenant = getattr(request.user, "tenant", None)
        if not tenant:
            return Response({"detail": "Tenant não associado."}, status=403)
        if (
            not staff
            or staff.role != TenantStaffMember.Role.OWNER
            or staff.status != TenantStaffMember.Status.ACTIVE
        ):
            return Response(
                {"detail": "Somente OWNER ativo do tenant pode criar checkout."},
                status=403,
            )

        # 4) Customer
        customer_id = stripe_utils.get_or_create_customer(request.user)

        # 5) URLs (com FRONTEND_BASE_URL como fallback)
        base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173").rstrip(
            "/"
        )
        success_url = getattr(
            settings,
            "STRIPE_SUCCESS_URL",
            f"{base}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        )
        cancel_url = getattr(
            settings,
            "STRIPE_CANCEL_URL",
            f"{base}/billing/cancel",
        )

        # 6) Params da Checkout Session
        metadata = {"user_id": str(request.user.id), "plan_code": canonical_plan}

        params = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "allow_promotion_codes": True,
            "metadata": metadata,
        }

        subscription_data = {}

        has_existing_subscription = Subscription.objects.filter(
            user__tenant=request.user.tenant,
        ).exists()

        trial_days = getattr(settings, "STRIPE_TRIAL_PERIOD_DAYS", 0)
        if trial_days and not has_existing_subscription:
            subscription_data["trial_period_days"] = trial_days
        else:
            subscription_data["trial_from_plan"] = False

        subscription_data["metadata"] = metadata
        params["subscription_data"] = subscription_data

        params["client_reference_id"] = str(request.user.tenant_id or request.user.id)

        stripe_client = stripe_utils.get_stripe()
        try:
            session = stripe_client.checkout.Session.create(**params)

            # Log checkout creation success
            logger.info(
                "Stripe checkout session created",
                extra={
                    "user_id": request.user.id,
                    "tenant_id": getattr(tenant, "id", None),
                    "plan_code": canonical_plan,
                    "checkout_url": session.url,
                },
            )

            return Response({"checkout_url": session.url}, status=200)
        except stripe.error.StripeError as e:
            logger.error(
                f"Stripe error creating subscription session: {e}",
                extra={
                    "user_id": request.user.id,
                    "plan": canonical_plan,
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                },
            )
            return Response(
                {
                    "detail": "Erro ao comunicar com provedor de pagamento. Verifique a configuração ou tente novamente."
                },
                status=503,
            )
        except Exception as e:
            logger.exception("Unexpected error creating subscription session")
            return Response({"detail": "Erro interno ao processar pedido."}, status=500)


class CreatePortalSession(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: PortalSessionResponseSerializer},
    )
    def post(self, request):
        """
        Cria uma sessão do Billing Portal para o salão gerenciar a assinatura:
        trocar plano, cancelar, reativar, atualizar cartão, ver faturas.
        """
        stripe_client = stripe_utils.get_stripe()
        try:
            customer_id = stripe_utils.get_or_create_customer(request.user)
            return_url = getattr(
                settings, "STRIPE_PORTAL_RETURN_URL", "http://localhost:3000/billing"
            )
            portal = stripe_client.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            return Response({"portal_url": portal.url}, status=200)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)


class StripeWebhookView(APIView):
    permission_classes = [AllowAny]  # Stripe não envia credenciais

    @extend_schema(
        request=OpenApiTypes.BINARY,
        responses={200: OpenApiResponse(description="Event processed")},
    )
    def post(self, request):
        """
        Webhook em /api/payments/stripe/webhook/
        Eventos considerados:
          - checkout.session.completed
          - customer.subscription.created
          - customer.subscription.updated
          - customer.subscription.deleted
          - invoice.payment_succeeded
          - invoice.payment_failed
        """
        stripe_client = stripe
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        secret = settings.STRIPE_WEBHOOK_SECRET

        try:
            event = stripe_client.Webhook.construct_event(
                payload=payload, sig_header=sig_header, secret=secret
            )
        except Exception:
            try:
                event = json.loads(
                    payload.decode()
                    if isinstance(payload, (bytes, bytearray))
                    else payload
                )
            except Exception:
                return HttpResponse(status=400)

        etype = event["type"]
        data = event["data"]["object"]

        # Deduplicação de eventos
        webhook_event, created = StripeWebhookEvent.objects.get_or_create(
            stripe_event_id=event["id"],
            defaults={
                "event_type": etype,
                "event_data": event.get("data", {}),
            },
        )
        if not created and webhook_event.processed:
            return HttpResponse("Event already processed", status=200)

        # Util helpers
        def upsert_subscription(user, stripe_sub):
            sub_id = stripe_sub["id"]
            status = stripe_sub.get("status")
            cancel_at_period_end = bool(stripe_sub.get("cancel_at_period_end"))
            current_period_end = stripe_sub.get("current_period_end")
            cpe_dt = (
                datetime.fromtimestamp(current_period_end, tz=dt_timezone.utc)
                if current_period_end
                else None
            )
            items = stripe_sub.get("items", {}).get("data", [])
            price_id = None
            if items:
                # quando expand=["items.data.price"], vem o objeto price completo;
                # caso contrário, pode vir só o id
                price = items[0].get("price")
                price_id = price.get("id") if isinstance(price, dict) else price

            prev = Subscription.objects.filter(stripe_subscription_id=sub_id).first()
            prev_price_id = prev.price_id if prev else None

            logger.info(
                f"Webhook upsert_subscription: id={sub_id} status={status} "
                f"cancel_at_period_end_payload={cancel_at_period_end} "
                f"prev_cancel_at={prev.cancel_at_period_end if prev else 'None'}"
            )

            sub, _ = Subscription.objects.update_or_create(
                stripe_subscription_id=sub_id,
                defaults={
                    "user": user,
                    "status": status,
                    "price_id": price_id,
                    "cancel_at_period_end": cancel_at_period_end,
                    "current_period_end": cpe_dt,
                },
            )
            return sub, cpe_dt, prev_price_id

        def update_feature_flags(user, stripe_sub, current_period_end_dt):
            from users.models import UserFeatureFlags

            status = stripe_sub.get("status")

            metadata = stripe_sub.get("metadata") or {}
            detected_plan = metadata.get("plan_code")

            items = stripe_sub.get("items", {}).get("data", [])
            price_id = None
            if items:
                price = items[0].get("price")
                price_id = price.get("id") if isinstance(price, dict) else price

            if not detected_plan:
                detected_plan = stripe_utils.get_plan_code_from_price(price_id)

            if detected_plan:
                detected_plan = detected_plan.lower()

            logger.info(
                f"update_feature_flags: user={user.id}, status={status}, "
                f"detected_plan={detected_plan}, price_id={price_id}"
            )

            if detected_plan not in {"basic", "standard", "pro", "enterprise"}:
                # Se não for um plano conhecido, assumimos basic apenas se não conseguirmos identificar
                # Mas se o detected_plan veio como None, mantemos None para logica abaixo
                if not detected_plan:
                    detected_plan = "basic"

            # trial_end
            trial_end_ts = stripe_sub.get("trial_end")
            trial_end_dt = (
                datetime.fromtimestamp(trial_end_ts, tz=dt_timezone.utc)
                if trial_end_ts
                else None
            )

            # start_date (quando o Stripe enviar)
            start_ts = stripe_sub.get("start_date")
            start_dt = (
                datetime.fromtimestamp(start_ts, tz=dt_timezone.utc)
                if start_ts
                else None
            )

            ff, _ = UserFeatureFlags.objects.get_or_create(user=user)

            is_pro = status in ("active", "trialing")
            ff.is_pro = is_pro
            ff.pro_status = status
            ff.pro_plan = detected_plan
            # mantém o valor existente se já houver; senão usa start_dt; fallback agora
            ff.pro_since = ff.pro_since or start_dt or timezone.now()
            ff.pro_until = current_period_end_dt
            ff.trial_until = trial_end_dt

            ff.save(
                update_fields=[
                    "is_pro",
                    "pro_status",
                    "pro_plan",
                    "pro_since",
                    "pro_until",
                    "trial_until",
                    "updated_at",
                ]
            )

            tenant = getattr(user, "tenant", None)
            if tenant:
                # Se estiver incomplete, permitimos que o tenant reflita o plano escolhido (UX),
                # embora as feature flags (is_pro) permaneçam restritas até 'active'.
                use_detected = is_pro or (status == "incomplete" and detected_plan)
                # Fallback seguro para basic se não houver detected_plan ou se não for 'pro' elegível
                desired_plan = (
                    detected_plan
                    if use_detected
                    else getattr(tenant, "PLAN_BASIC", "basic")
                )

                if desired_plan and tenant.plan_tier != desired_plan:
                    old_plan = tenant.plan_tier
                    tenant.plan_tier = desired_plan
                    tenant.save(update_fields=["plan_tier", "updated_at"])
                    logger.info(
                        f"Updated tenant {tenant.slug} plan_tier: {old_plan} -> {desired_plan} (status: {status})"
                    )
                else:
                    logger.info(
                        f"Tenant {tenant.slug} plan_tier remains {tenant.plan_tier} (status: {status}, desired: {desired_plan})"
                    )
            else:
                logger.warning(
                    f"No tenant found for user {user.id} to update plan_tier"
                )

        # Roteamento de eventos
        try:
            if etype == "checkout.session.completed":
                customer_id = data.get("customer")
                subscription_id = data.get("subscription")

                # Problema 1: Recuperar subscription_id de metadata se estiver faltando no root (comum em alguns fluxos)
                if not subscription_id:
                    subscription_id = data.get("metadata", {}).get("subscription_id")

                logger.info(
                    f"Processing checkout.session.completed: customer={customer_id}, subscription={subscription_id}"
                )

                if customer_id and subscription_id:
                    pc = (
                        PaymentCustomer.objects.filter(stripe_customer_id=customer_id)
                        .select_related("user", "user__tenant")
                        .first()
                    )
                    if pc:
                        # Log de diagnóstico inicial
                        logger.info(
                            f"[WEBHOOK] Processing checkout for user {pc.user.email} (Tenant: {pc.user.tenant.slug})"
                        )

                        # tenta obter detalhes da assinatura; se falhar, não prossegue
                        try:
                            sub = stripe.Subscription.retrieve(
                                subscription_id, expand=["items.data.price"]
                            )
                            # garantir dict, não objeto custom
                            if hasattr(sub, "to_dict"):
                                sub = sub.to_dict()
                        except Exception as e:
                            logger.error(
                                f"[WEBHOOK] Failed to retrieve subscription {subscription_id}: {str(e)}"
                            )
                            return HttpResponse(status=200)

                        saved_sub, cpe_dt, _prev_price_id = upsert_subscription(
                            pc.user, sub
                        )
                        update_feature_flags(pc.user, sub, cpe_dt)

                        # =========================================================================
                        # CORREÇÃO BE-STAGING-FIX-02: Atribuição de Créditos Iniciais do Plano
                        # =========================================================================
                        try:
                            status = sub.get("status")
                            items = sub.get("items", {}).get("data", [])
                            price_id = None
                            if items:
                                price = items[0].get("price")
                                price_id = (
                                    price.get("id")
                                    if isinstance(price, dict)
                                    else price
                                )
                            md = sub.get("metadata") or {}
                            plan_code = md.get("plan_code") or md.get("plan")
                            if not plan_code:
                                plan_code = stripe_utils.get_plan_code_from_price(
                                    price_id
                                )
                            plan_info = SubscriptionService.AVAILABLE_PLANS.get(
                                plan_code or ""
                            )
                            credits_included = (
                                Decimal(str(plan_info.get("credits_included")))
                                if plan_info
                                else Decimal("0.00")
                            )
                            trial_end_ts = sub.get("trial_end")

                            # DIAGNOSTICO STAGING: Logar detalhes do trial/créditos
                            logger.info(
                                f"[WEBHOOK] Checkout Session Completed: status={status}, "
                                f"plan={plan_code}, credits={credits_included}, "
                                f"trial_end={trial_end_ts}, sub_id={subscription_id}"
                            )

                            # Aceita 'trialing' ou 'active' para conceder os créditos iniciais
                            if (
                                status in ("trialing", "active")
                                and credits_included > 0
                            ):
                                from users.models import CommLedger

                                # Referência única para evitar duplicação (id da assinatura + timestamp do trial ou start)
                                ref_suffix = (
                                    trial_end_ts
                                    if trial_end_ts
                                    else sub.get("start_date")
                                )
                                ref = f"plan_bonus:{subscription_id}:{ref_suffix}"

                                exists = CommLedger.objects.filter(
                                    tenant=pc.user.tenant,
                                    transaction_type=CommLedger.TransactionType.BONUS,
                                    reference_id=ref,
                                ).exists()

                                if not exists:
                                    cs = CreditService(pc.user.tenant)
                                    cs.add_credits(
                                        amount=credits_included,
                                        transaction_type="bonus",
                                        description=f"Créditos incluídos do plano {plan_code} ({status})",
                                        reference_id=ref,
                                        created_by=pc.user,
                                    )
                                    logger.info(
                                        f"[WEBHOOK] Credits granted: {credits_included} EUR for tenant {pc.user.tenant.slug}"
                                    )
                                else:
                                    logger.info(
                                        f"[WEBHOOK] Credits already granted for ref {ref}"
                                    )
                        except Exception as e:
                            logger.exception(
                                f"Plan bonus grant failed on checkout.session.completed: {e}"
                            )
                        # =========================================================================

                        # FORÇAR SINCRONIZAÇÃO DO TENANT PLAN
                        try:
                            # Tenta extrair o plano dos metadados ou do preço
                            meta_plan = sub.get("metadata", {}).get("plan_code")
                            if not meta_plan:
                                items = sub.get("items", {}).get("data", [])
                                if items:
                                    price = items[0].get("price")
                                    p_id = (
                                        price.get("id")
                                        if isinstance(price, dict)
                                        else price
                                    )
                                    meta_plan = stripe_utils.get_plan_code_from_price(
                                        p_id
                                    )

                            if meta_plan and meta_plan in {
                                "basic",
                                "standard",
                                "pro",
                                "enterprise",
                            }:
                                tenant = pc.user.tenant
                                if tenant.plan_tier != meta_plan:
                                    logger.info(
                                        f"[WEBHOOK] Forcing tenant plan update: {tenant.plan_tier} -> {meta_plan}"
                                    )
                                    tenant.plan_tier = meta_plan
                                    tenant.save(
                                        update_fields=["plan_tier", "updated_at"]
                                    )
                                else:
                                    logger.info(
                                        f"[WEBHOOK] Tenant plan already synced: {meta_plan}"
                                    )
                        except Exception as e:
                            logger.error(f"[WEBHOOK] Failed to force tenant sync: {e}")

                        # Cancelar assinaturas anteriores ativas do mesmo tenant (apenas se nova estiver ativa/trial)
                        try:
                            if sub.get("status") in ("active", "trialing"):
                                tenant = getattr(pc.user, "tenant", None)
                                if tenant:
                                    previous_active = (
                                        Subscription.objects.filter(
                                            user__tenant=tenant,
                                            status__in=[
                                                "active",
                                                "trialing",
                                                "past_due",
                                            ],
                                        )
                                        .exclude(stripe_subscription_id=subscription_id)
                                        .all()
                                    )

                                    for prev in previous_active:
                                        try:
                                            stripe.Subscription.cancel(
                                                prev.stripe_subscription_id
                                            )
                                        except Exception:
                                            logger.exception(
                                                "stripe.subscription.cancel failed",
                                                extra={
                                                    "prev_sub_id": prev.stripe_subscription_id,
                                                    "tenant_id": getattr(
                                                        tenant, "id", None
                                                    ),
                                                },
                                            )
                                        prev.status = "canceled"
                                        prev.cancel_at_period_end = False
                                        prev.current_period_end = timezone.now()
                                        prev.save(
                                            update_fields=[
                                                "status",
                                                "cancel_at_period_end",
                                                "current_period_end",
                                                "updated_at",
                                            ]
                                        )
                        except Exception as exc:
                            logger.exception(
                                "previous subscription cancellation failed",
                                exc_info=exc,
                            )

                    else:
                        logger.error(
                            f"[WEBHOOK] PaymentCustomer not found for stripe_customer_id={customer_id}"
                        )
                else:
                    # Fluxo de compra de créditos via Checkout (mode=payment)
                    meta = data.get("metadata") or {}
                    if meta.get("type") == "credit_purchase" and customer_id:
                        payment_intent_id = data.get("payment_intent")
                        price_id = meta.get("price_id")
                        credits_amount = meta.get("credits_amount")
                        pc = (
                            PaymentCustomer.objects.filter(
                                stripe_customer_id=customer_id
                            )
                            .select_related("user")
                            .first()
                        )
                        if pc and payment_intent_id and price_id:
                            cp, created = CreditPayment.objects.get_or_create(
                                stripe_payment_intent_id=payment_intent_id,
                                defaults={
                                    "user": pc.user,
                                    "tenant": pc.user.tenant,
                                    "stripe_customer_id": customer_id,
                                    "stripe_price_id": price_id,
                                    "amount": Decimal(str(credits_amount or "0")),
                                    "currency": "EUR",
                                    "status": "pending",
                                    "credits_purchased": Decimal(
                                        str(credits_amount or "0")
                                    ),
                                    "metadata": {"created_via": "checkout_session"},
                                },
                            )
                            if data.get("payment_status") == "paid":
                                try:
                                    cs = CreditService(pc.user.tenant)
                                    cs.add_credits(
                                        amount=cp.credits_purchased,
                                        transaction_type="purchase",
                                        description="Compra de créditos via Stripe Checkout",
                                        reference_id=payment_intent_id,
                                        created_by=pc.user,
                                    )
                                    cp.status = "succeeded"
                                    cp.completed_at = timezone.now()
                                    cp.credits_applied = True
                                    cp.save()
                                except Exception:
                                    logger.exception(
                                        "Failed to apply credits for checkout session",
                                        extra={
                                            "session_id": data.get("id"),
                                            "payment_intent_id": payment_intent_id,
                                            "customer_id": customer_id,
                                        },
                                    )
                    else:
                        logger.warning(
                            f"checkout.session.completed received without subscription_id or credit_purchase metadata. Session ID: {data.get('id')}"
                        )

            elif etype in {
                "customer.subscription.created",
                "customer.subscription.updated",
                "customer.subscription.deleted",
            }:
                customer_id = data.get("customer")
                pc = (
                    PaymentCustomer.objects.filter(stripe_customer_id=customer_id)
                    .select_related("user")
                    .first()
                )
                if pc:
                    saved_sub, cpe_dt, prev_price_id = upsert_subscription(
                        pc.user, data
                    )
                    update_feature_flags(pc.user, data, cpe_dt)

                    try:
                        status = data.get("status")
                        items = data.get("items", {}).get("data", [])
                        price_id = None
                        if items:
                            price = items[0].get("price")
                            price_id = (
                                price.get("id") if isinstance(price, dict) else price
                            )
                        md = data.get("metadata") or {}
                        plan_code = md.get("plan_code") or md.get("plan")
                        if not plan_code:
                            plan_code = stripe_utils.get_plan_code_from_price(price_id)
                        plan_info = SubscriptionService.AVAILABLE_PLANS.get(
                            plan_code or ""
                        )
                        credits_included = (
                            Decimal(str(plan_info.get("credits_included")))
                            if plan_info
                            else Decimal("0.00")
                        )
                        trial_end_ts = data.get("trial_end")
                        subscription_id = data.get("id")
                        if (
                            etype == "customer.subscription.updated"
                            and credits_included > 0
                            and subscription_id
                            and prev_price_id != price_id
                        ):
                            from users.models import CommLedger

                            ref = f"plan_change_bonus:{subscription_id}:{price_id}"
                            exists = CommLedger.objects.filter(
                                tenant=pc.user.tenant,
                                transaction_type=CommLedger.TransactionType.BONUS,
                                reference_id=ref,
                            ).exists()
                            if not exists and status in (
                                "active",
                                "trialing",
                                "past_due",
                            ):
                                cs = CreditService(pc.user.tenant)
                                cs.add_credits(
                                    amount=credits_included,
                                    transaction_type="bonus",
                                    description=f"Créditos incluídos do plano {plan_code} (mudança de plano)",
                                    reference_id=ref,
                                    created_by=pc.user,
                                )
                        if (
                            status == "trialing"
                            and credits_included > 0
                            and trial_end_ts
                            and subscription_id
                        ):
                            from users.models import CommLedger

                            ref = f"trial_bonus:{subscription_id}:{trial_end_ts}"
                            exists = CommLedger.objects.filter(
                                tenant=pc.user.tenant,
                                transaction_type=CommLedger.TransactionType.BONUS,
                                reference_id=ref,
                            ).exists()
                            if not exists:
                                cs = CreditService(pc.user.tenant)
                                cs.add_credits(
                                    amount=credits_included,
                                    transaction_type="bonus",
                                    description=f"Créditos incluídos do plano {plan_code} (trial)",
                                    reference_id=ref,
                                    created_by=pc.user,
                                )
                        if etype == "customer.subscription.deleted" and subscription_id:
                            from users.models import CommLedger

                            tenant = pc.user.tenant
                            ref_prefix = f"trial_bonus:{subscription_id}:"
                            bonus_entries = CommLedger.objects.filter(
                                tenant=tenant,
                                transaction_type=CommLedger.TransactionType.BONUS,
                                reference_id__startswith=ref_prefix,
                            )
                            bonus_total = sum(
                                (be.amount_eur for be in bonus_entries), Decimal("0.00")
                            )
                            if bonus_total > 0:
                                cs = CreditService(tenant)
                                current_balance = cs.get_credit_balance()
                                expire_amount = min(bonus_total, current_balance)
                                if expire_amount > 0:
                                    try:
                                        cs.expire_credits(
                                            amount=expire_amount,
                                            description="Expiração de créditos de trial ao cancelar assinatura",
                                            reference_id=f"trial_expire:{subscription_id}:{trial_end_ts or ''}",
                                            created_by=pc.user,
                                        )
                                    except Exception:
                                        logger.exception(
                                            "failed to expire trial bonus on cancellation"
                                        )
                                consumed_amount = bonus_total - expire_amount
                                if consumed_amount > 0:
                                    try:
                                        amount_cents = int(
                                            (consumed_amount * 100).to_integral_value()
                                        )
                                        if amount_cents > 0:
                                            stripe.InvoiceItem.create(
                                                customer=customer_id,
                                                currency="eur",
                                                amount=amount_cents,
                                                description="Créditos consumidos durante o trial",
                                            )
                                            inv = stripe.Invoice.create(
                                                customer=customer_id, auto_advance=True
                                            )
                                            stripe.Invoice.finalize_invoice(inv["id"])
                                    except Exception:
                                        logger.exception(
                                            "failed to invoice consumed trial credits on cancellation"
                                        )
                    except Exception:
                        logger.exception(
                            "trial bonus/cleanup handling failed on subscription event"
                        )
                else:
                    logger.error(
                        f"PaymentCustomer not found for stripe_customer_id={customer_id} in {etype}"
                    )

            elif etype in {"invoice.payment_succeeded", "invoice.payment_failed"}:
                if etype == "invoice.payment_succeeded":
                    customer_id = data.get("customer")
                    subscription_id = data.get("subscription")
                    amount_paid = data.get("amount_paid") or data.get("total") or 0
                    if customer_id and subscription_id and amount_paid:
                        pc = (
                            PaymentCustomer.objects.filter(
                                stripe_customer_id=customer_id
                            )
                            .select_related("user")
                            .first()
                        )
                        if pc:
                            try:
                                sub = stripe.Subscription.retrieve(
                                    subscription_id, expand=["items.data.price"]
                                )
                                if hasattr(sub, "to_dict"):
                                    sub = sub.to_dict()
                            except Exception:
                                sub = None
                            price_id = None
                            current_period_end = None
                            status = None
                            if isinstance(sub, dict):
                                status = sub.get("status")
                                current_period_end = sub.get("current_period_end")
                                items = sub.get("items", {}).get("data", [])
                                if items:
                                    price = items[0].get("price")
                                    price_id = (
                                        price.get("id")
                                        if isinstance(price, dict)
                                        else price
                                    )
                            plan_code = None
                            if isinstance(sub, dict):
                                md = sub.get("metadata") or {}
                                plan_code = md.get("plan_code") or md.get("plan")
                            if not plan_code:
                                plan_code = stripe_utils.get_plan_code_from_price(
                                    price_id
                                )
                            plan_info = SubscriptionService.AVAILABLE_PLANS.get(
                                plan_code or ""
                            )
                            credits_included = (
                                Decimal(str(plan_info.get("credits_included")))
                                if plan_info
                                else Decimal("0.00")
                            )
                            if credits_included > 0 and current_period_end:
                                from users.models import CommLedger

                                ref = (
                                    f"plan_bonus:{subscription_id}:{current_period_end}"
                                )
                                exists = CommLedger.objects.filter(
                                    tenant=pc.user.tenant,
                                    transaction_type=CommLedger.TransactionType.BONUS,
                                    reference_id=ref,
                                ).exists()
                                if not exists and status in ("active", "past_due"):
                                    cs = CreditService(pc.user.tenant)
                                    cs.add_credits(
                                        amount=credits_included,
                                        transaction_type="bonus",
                                        description=f"Créditos incluídos do plano {plan_code}",
                                        reference_id=ref,
                                        created_by=pc.user,
                                    )
            elif etype == "payment_intent.succeeded":
                try:
                    cp = CreditPayment.objects.get(
                        stripe_payment_intent_id=data.get("id")
                    )
                    cp.status = "succeeded"
                    cp.completed_at = timezone.now()
                    if not cp.credits_applied:
                        cs = CreditService(cp.tenant)
                        cs.add_credits(
                            amount=cp.credits_purchased,
                            transaction_type="purchase",
                            description="Compra de créditos via Stripe",
                            reference_id=data.get("id"),
                            created_by=cp.user,
                        )
                        cp.credits_applied = True
                    cp.save()
                except CreditPayment.DoesNotExist:
                    raise Exception(f"Payment not found: {data.get('id')}")
            elif etype == "payment_intent.payment_failed":
                try:
                    cp = CreditPayment.objects.get(
                        stripe_payment_intent_id=data.get("id")
                    )
                    cp.status = "failed"
                    cp.completed_at = timezone.now()
                    cp.save()
                except CreditPayment.DoesNotExist:
                    raise Exception(f"Payment not found: {data.get('id')}")

            # Marcar como processado
            webhook_event.processed = True
            webhook_event.processed_at = timezone.now()
            webhook_event.save()

        except Exception as exc:  # pragma: no cover - log e segue fluxo
            logger.exception("Stripe webhook processing failed", exc_info=exc)
            webhook_event.processing_error = str(exc)
            webhook_event.save()
            return HttpResponse(f"Error processing webhook: {str(exc)}", status=400)

        return HttpResponse("Webhook processed successfully", status=200)


class AvailableCreditPackagesView(APIView):
    """Lista os pacotes de créditos disponíveis para compra."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: AvailableCreditPackagesResponseSerializer})
    def get(self, request):
        """Retorna os pacotes de créditos disponíveis."""
        packages = CreditPurchaseService.get_available_credit_packages()
        return Response({"packages": packages}, status=200)


class CreateCreditPaymentIntentView(APIView):
    """Cria um PaymentIntent para compra de créditos."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CreditPurchaseRequestSerializer,
        responses={200: CreditPurchaseResponseSerializer},
    )
    def post(self, request):
        """
        Cria um PaymentIntent para compra de créditos.
        O valor em EUR será convertido para o price_id correspondente.
        """
        # Validar usuário e tenant
        user = request.user
        tenant = getattr(user, "tenant", None)
        request_tenant = getattr(request, "tenant", None)

        if tenant is None:
            return Response(
                {"detail": "Operação não permitida: usuário sem tenant."},
                status=403,
            )

        if request_tenant is not None and request_tenant != tenant:
            return Response(
                {
                    "detail": "Operação não permitida: tenant de requisição não corresponde ao usuário."
                },
                status=403,
            )

        # Somente OWNER ativo pode comprar
        staff_member = getattr(user, "staff_member", None)
        from users.models import TenantStaffMember

        if (
            staff_member is None
            or staff_member.role != TenantStaffMember.Role.OWNER
            or staff_member.status != TenantStaffMember.Status.ACTIVE
        ):
            return Response(
                {
                    "detail": "Operação não permitida: apenas OWNER ativo pode comprar créditos."
                },
                status=403,
            )

        # Validar se o tenant pode comprar créditos extras
        if not tenant.can_purchase_extra_credits():
            return Response(
                {"detail": "Compra de créditos extras não permitida para este plano"},
                status=403,
            )

        serializer = CreditPurchaseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        amount_eur = serializer.validated_data["amount_eur"]

        # Mapear valor para price_id
        amount_to_price_id = {
            Decimal("5.00"): settings.STRIPE_PRICE_CREDITS_5_ID,
            Decimal("10.00"): settings.STRIPE_PRICE_CREDITS_10_ID,
            Decimal("25.00"): settings.STRIPE_PRICE_CREDITS_25_ID,
            Decimal("50.00"): settings.STRIPE_PRICE_CREDITS_50_ID,
            Decimal("100.00"): settings.STRIPE_PRICE_CREDITS_100_ID,
        }

        price_id = amount_to_price_id.get(amount_eur)
        if not price_id:
            return Response(
                {
                    "detail": f"Valor não suportado: {amount_eur}. Valores disponíveis: 5, 10, 25, 50, 100"
                },
                status=400,
            )

        try:
            result = CreditPurchaseService.create_payment_intent(
                user=request.user, tenant=request.user.tenant, price_id=price_id
            )

            return Response(
                {
                    "client_secret": result["client_secret"],
                    "payment_intent_id": result["payment_intent_id"],
                    "amount_eur": result["amount"],
                },
                status=200,
            )

        except Exception as e:
            logger.error(f"Error creating credit payment intent: {str(e)}")
            return Response({"detail": str(e)}, status=400)


class AvailablePlansView(APIView):
    """View para listar planos disponíveis."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: AvailablePlansSerializer(many=True)})
    def get(self, request):
        """Retorna lista de planos disponíveis com informações de upgrade."""
        try:
            current_subscription = SubscriptionService.get_current_subscription(
                request.user
            )
            current_plan = (
                current_subscription["plan_code"] if current_subscription else None
            )

            plans = SubscriptionService.get_available_plans(current_plan)

            return Response(plans, status=200)

        except Exception as e:
            return Response({"detail": f"Erro ao buscar planos: {str(e)}"}, status=500)


class CreateCreditCheckoutSessionView(APIView):
    """Cria uma Stripe Checkout Session (mode=payment) para compra de créditos."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CreditPurchaseRequestSerializer,
        responses={200: CreditCheckoutSessionResponseSerializer},
    )
    def post(self, request):
        user = request.user
        tenant = getattr(user, "tenant", None)

        if tenant is None:
            return Response({"detail": "Usuário sem tenant"}, status=403)

        staff_member = getattr(user, "staff_member", None)
        if (
            staff_member is None
            or staff_member.role != TenantStaffMember.Role.OWNER
            or staff_member.status != TenantStaffMember.Status.ACTIVE
        ):
            return Response(
                {"detail": "Apenas OWNER ativo pode comprar créditos."}, status=403
            )

        serializer = CreditPurchaseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        amount_eur = serializer.validated_data["amount_eur"]
        amount_to_price_id = {
            Decimal("5.00"): settings.STRIPE_PRICE_CREDITS_5_ID,
            Decimal("10.00"): settings.STRIPE_PRICE_CREDITS_10_ID,
            Decimal("25.00"): settings.STRIPE_PRICE_CREDITS_25_ID,
            Decimal("50.00"): settings.STRIPE_PRICE_CREDITS_50_ID,
            Decimal("100.00"): settings.STRIPE_PRICE_CREDITS_100_ID,
        }

        price_id = amount_to_price_id.get(amount_eur)
        if not price_id:
            return Response(
                {"detail": f"Valor não suportado: {amount_eur}"}, status=400
            )

        stripe_client = stripe_utils.get_stripe()
        customer_id = stripe_utils.get_or_create_customer(user)

        base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173").rstrip(
            "/"
        )
        # success_url = getattr(settings, "STRIPE_SUCCESS_URL", f"{base}/billing/success")
        success_url = f"{base}/billing/success?type=credits"
        cancel_url = getattr(settings, "STRIPE_CANCEL_URL", f"{base}/billing/cancel")

        metadata = {
            "type": "credit_purchase",
            "user_id": str(user.id),
            "tenant_id": str(getattr(tenant, "id", "")),
            "price_id": price_id,
            "credits_amount": str(amount_eur),
        }

        params = {
            "mode": "payment",
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "allow_promotion_codes": True,
            "metadata": metadata,
        }

        try:
            session = stripe_client.checkout.Session.create(**params)
            logger.info(
                "Stripe credit checkout session created",
                extra={
                    "user_id": user.id,
                    "tenant_id": getattr(tenant, "id", None),
                    "amount_eur": str(amount_eur),
                    "checkout_url": session.url,
                },
            )
            return Response(
                {"checkout_url": session.url, "session_id": session.id}, status=200
            )
        except stripe.error.StripeError as e:
            logger.error(
                f"Stripe error creating credit checkout session: {e}",
                extra={
                    "user_id": user.id,
                    "amount": str(amount_eur),
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                },
            )
            return Response(
                {
                    "detail": "Erro ao comunicar com provedor de pagamento. Verifique a configuração ou tente novamente."
                },
                status=503,
            )
        except Exception as e:
            logger.exception("Unexpected error creating credit checkout session")
            return Response({"detail": "Erro interno ao processar pedido."}, status=500)


class CurrentSubscriptionView(APIView):
    """View para obter informações da assinatura atual."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CurrentSubscriptionSerializer})
    def get(self, request):
        """Retorna informações da assinatura atual do usuário."""
        try:
            subscription = SubscriptionService.get_current_subscription(request.user)

            if not subscription:
                return Response(
                    {"detail": "Nenhuma assinatura ativa encontrada"}, status=404
                )

            return Response(subscription, status=200)

        except Exception as e:
            return Response(
                {"detail": f"Erro ao buscar assinatura: {str(e)}"}, status=500
            )


class SubscriptionActionView(APIView):
    """View para ações de assinatura (cancelar, reativar)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SubscriptionActionSerializer,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "message": {"type": "string"},
                },
            }
        },
    )
    def post(self, request):
        """Executa ações na assinatura (cancelar ou reativar)."""
        serializer = SubscriptionActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data["action"]
        cancel_at_period_end = serializer.validated_data.get(
            "cancel_at_period_end", True
        )

        try:
            if action == "cancel":
                success = SubscriptionService.cancel_subscription(
                    request.user, cancel_at_period_end=cancel_at_period_end
                )
                message = (
                    "Assinatura cancelada com sucesso"
                    if success
                    else "Erro ao cancelar assinatura"
                )

            elif action == "reactivate":
                success = SubscriptionService.reactivate_subscription(request.user)
                message = (
                    "Assinatura reativada com sucesso"
                    if success
                    else "Erro ao reativar assinatura"
                )

            else:
                return Response({"detail": "Ação inválida"}, status=400)

            return Response(
                {"success": success, "message": message}, status=200 if success else 400
            )

        except Exception as e:
            return Response({"detail": f"Erro ao executar ação: {str(e)}"}, status=500)


class PaymentHistoryView(APIView):
    """View para histórico de pagamentos."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PaymentHistorySerializer})
    def get(self, request):
        """Retorna histórico de pagamentos do usuário."""
        try:
            limit = int(request.query_params.get("limit", 50))
            limit = min(limit, 100)  # Máximo de 100 registros

            history = BillingService.get_payment_history(request.user, limit=limit)

            return Response(history, status=200)

        except Exception as e:
            return Response(
                {"detail": f"Erro ao buscar histórico: {str(e)}"}, status=500
            )


class BillingOverviewView(APIView):
    """View para visão geral do billing."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: BillingOverviewSerializer})
    def get(self, request):
        """Retorna visão geral completa do billing do usuário."""
        try:
            overview = BillingService.get_billing_overview(request.user)

            try:
                tenant = getattr(request.user, "tenant", None)
                current = overview.get("current_subscription") or {}
                plan_code = current.get("plan_code")
                if tenant and plan_code and tenant.plan_tier != plan_code:
                    old = tenant.plan_tier
                    tenant.plan_tier = plan_code
                    tenant.save(update_fields=["plan_tier", "updated_at"])
                    logger.info(
                        "billing.overview.plan_sync",
                        extra={
                            "user_id": request.user.id,
                            "tenant_id": getattr(tenant, "id", None),
                            "old_plan": old,
                            "new_plan": plan_code,
                        },
                    )
            except Exception:
                # não bloquear resposta de overview por erro de sync
                pass

            return Response(overview, status=200)

        except Exception as e:
            return Response(
                {"detail": f"Erro ao buscar visão geral: {str(e)}"}, status=500
            )


class ImprovedCheckoutSessionView(APIView):
    """View melhorada para criar checkout sessions."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CheckoutSessionRequestSerializer,
        responses={200: CheckoutSessionResponseSerializer},
    )
    def post(self, request):
        """Cria uma sessão de checkout usando o novo SubscriptionService."""
        serializer = CheckoutSessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        plan = serializer.validated_data.get("plan", "basic")

        # URLs de sucesso e cancelamento
        base_url = getattr(
            settings, "FRONTEND_BASE_URL", "http://localhost:3000"
        ).rstrip("/")
        success_url = f"{base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_url}/billing/cancel"

        try:
            result = SubscriptionService.create_checkout_session(
                user=request.user,
                plan=plan,
                success_url=success_url,
                cancel_url=cancel_url,
            )

            return Response(result, status=200)

        except Exception as e:
            logger.exception("ImprovedCheckoutSessionView failed")
            return Response(
                {"detail": f"Erro ao criar checkout session: {str(e)}"}, status=500
            )


class ImprovedPortalSessionView(APIView):
    """View melhorada para criar portal sessions."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: PortalSessionResponseSerializer})
    def post(self, request):
        """Cria uma sessão do portal de billing usando o novo SubscriptionService."""
        base_url = getattr(
            settings, "FRONTEND_BASE_URL", "http://localhost:3000"
        ).rstrip("/")
        return_url = f"{base_url}/billing"

        try:
            result = SubscriptionService.create_portal_session(
                user=request.user, return_url=return_url
            )

            return Response(result, status=200)

        except Exception as e:
            logger.exception("ImprovedPortalSessionView failed")
            return Response(
                {"detail": f"Erro ao criar portal session: {str(e)}"}, status=500
            )


class StripeSettingsView(APIView):
    """Atualiza configurações de billing (Stripe) do tenant (OWNER-only)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=StripeSettingsUpdateRequestSerializer,
        responses={200: StripeSettingsResponseSerializer},
    )
    def patch(self, request):
        user = request.user
        tenant = getattr(user, "tenant", None)

        if not tenant:
            PAYMENTS_SETTINGS_UPDATED_TOTAL.labels(result="forbidden").inc()
            return Response({"detail": "Usuário sem tenant"}, status=403)

        # OWNER-only
        try:
            attr = getattr(user, "is_owner", False)
            is_owner = attr() if callable(attr) else bool(attr)
        except Exception:
            is_owner = False

        if not is_owner:
            PAYMENTS_SETTINGS_UPDATED_TOTAL.labels(result="forbidden").inc()
            return Response({"detail": "Permissão negada"}, status=403)

        serializer = StripeSettingsUpdateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            PAYMENTS_SETTINGS_UPDATED_TOTAL.labels(result="invalid").inc()
            return Response(serializer.errors, status=400)

        auto_renewal = serializer.validated_data["auto_renewal"]
        old_value = bool(getattr(tenant, "comm_auto_renew", False))

        # Validar plano para habilitar auto-renovação (Standard+)
        if auto_renewal and tenant.plan_tier not in (
            Tenant.PLAN_STANDARD,
            Tenant.PLAN_PRO,
            Tenant.PLAN_ENTERPRISE,
        ):
            PAYMENTS_SETTINGS_UPDATED_TOTAL.labels(result="forbidden").inc()
            return Response(
                {
                    "detail": "Renovação automática disponível apenas em planos Standard+"
                },
                status=403,
            )

        try:
            setattr(tenant, "comm_auto_renew", auto_renewal)
            tenant.save(update_fields=["comm_auto_renew", "updated_at"])

            logger.info(
                "payments.settings.update",
                extra={
                    "actor_id": user.id,
                    "tenant_id": tenant.id,
                    "field": "comm_auto_renew",
                    "old_value": old_value,
                    "new_value": auto_renewal,
                },
            )
            PAYMENTS_SETTINGS_UPDATED_TOTAL.labels(result="success").inc()

            response = {"auto_renewal": bool(getattr(tenant, "comm_auto_renew", False))}
            return Response(response, status=200)
        except Exception as e:
            logger.error(
                "payments.settings.update_error",
                extra={
                    "actor_id": user.id,
                    "tenant_id": getattr(tenant, "id", None),
                    "error": str(e),
                },
            )
            PAYMENTS_SETTINGS_UPDATED_TOTAL.labels(result="error").inc()
            return Response({"detail": "Erro ao atualizar settings"}, status=500)
