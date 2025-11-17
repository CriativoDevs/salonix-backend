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

from . import stripe_utils
from .models import Subscription, PaymentCustomer
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
from users.models import Tenant


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
            "monthly",
            "yearly",
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
        if requested_plan in {"monthly", "yearly"}:
            canonical_plan = "pro"

        # 3) Customer
        customer_id = stripe_utils.get_or_create_customer(request.user)

        # 4) URLs (com FRONTEND_BASE_URL como fallback)
        base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000").rstrip(
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

        # 5) Params da Checkout Session
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

        trial_days = getattr(settings, "STRIPE_TRIAL_PERIOD_DAYS", 0)
        if trial_days:
            subscription_data["trial_period_days"] = trial_days

        subscription_data["metadata"] = metadata
        params["subscription_data"] = subscription_data

        params["client_reference_id"] = str(request.user.tenant_id or request.user.id)

        stripe_client = stripe_utils.get_stripe()
        session = stripe_client.checkout.Session.create(**params)
        return Response({"checkout_url": session.url}, status=200)


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
        stripe_client = stripe_utils.get_stripe()
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        secret = settings.STRIPE_WEBHOOK_SECRET

        try:
            event = stripe_client.Webhook.construct_event(
                payload=payload, sig_header=sig_header, secret=secret
            )
        except ValueError:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError:
            return HttpResponse(status=400)

        etype = event["type"]
        data = event["data"]["object"]

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
            return sub, cpe_dt

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

            if detected_plan in {"monthly", "yearly"}:
                detected_plan = "pro"

            if detected_plan not in {"basic", "standard", "pro", "enterprise"}:
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

            ff.is_pro = status in ("active", "trialing")
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
                desired_plan = detected_plan if ff.is_pro else tenant.PLAN_BASIC
                if desired_plan and tenant.plan_tier != desired_plan:
                    tenant.plan_tier = desired_plan
                    tenant.save(update_fields=["plan_tier", "updated_at"])

        # Roteamento de eventos
        try:
            if etype == "checkout.session.completed":
                customer_id = data.get("customer")
                subscription_id = data.get("subscription")
                if customer_id and subscription_id:
                    pc = (
                        PaymentCustomer.objects.filter(stripe_customer_id=customer_id)
                        .select_related("user")
                        .first()
                    )
                    if pc:
                        # tenta obter detalhes da assinatura; se falhar, usa um payload mínimo
                        try:
                            sub = stripe.Subscription.retrieve(
                                subscription_id, expand=["items.data.price"]
                            )
                            # garantir dict, não objeto custom
                            if hasattr(sub, "to_dict"):
                                sub = sub.to_dict()
                        except Exception:
                            sub = {
                                "id": subscription_id,
                                "status": "active",  # fallback seguro para criar o registro
                                "cancel_at_period_end": False,
                                "current_period_end": None,
                                "items": {"data": []},
                            }
                        saved_sub, cpe_dt = upsert_subscription(pc.user, sub)
                        update_feature_flags(pc.user, sub, cpe_dt)

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
                    # aqui 'data' já é o objeto de assinatura enviado pelo webhook
                    saved_sub, cpe_dt = upsert_subscription(pc.user, data)
                    update_feature_flags(pc.user, data, cpe_dt)

            elif etype in {"invoice.payment_succeeded", "invoice.payment_failed"}:
                # opcional: logs/telemetria; assinatura atualiza via customer.subscription.updated
                pass

        except Exception as exc:  # pragma: no cover - log e segue fluxo
            logger.exception("Stripe webhook processing failed", exc_info=exc)
            return HttpResponse(status=200)


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
            return Response(
                {"detail": f"Erro ao criar checkout session: {str(e)}"}, status=500
            )


class ImprovedPortalSessionView(APIView):
    """View melhorada para criar portal sessions."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PortalSessionResponseSerializer})
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
            return Response(
                {"detail": f"Erro ao criar portal session: {str(e)}"}, status=500
            )


logger = logging.getLogger(__name__)


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
