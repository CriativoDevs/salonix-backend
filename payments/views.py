from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

import stripe

from . import stripe_utils
from .models import Subscription, PaymentCustomer


class CreateCheckoutSession(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Cria uma Checkout Session para assinatura (mensal/anual).
        Body opcional:
          - plan: "monthly" | "yearly" (default: "monthly")
        """
        s = stripe_utils.get_stripe()

        # 1) Plano + validação
        plan = (request.data.get("plan") or "monthly").lower()
        if plan not in ("monthly", "yearly"):
            return Response({"detail": "Plano inválido."}, status=400)

        # 2) Fallback para nomes de settings com/sem sufixo _ID
        monthly = getattr(settings, "STRIPE_PRICE_MONTHLY_ID", None) or getattr(
            settings, "STRIPE_PRICE_MONTHLY", None
        )
        yearly = getattr(settings, "STRIPE_PRICE_YEARLY_ID", None) or getattr(
            settings, "STRIPE_PRICE_YEARLY", None
        )
        price_id = yearly if plan == "yearly" else monthly
        if not price_id:
            return Response(
                {"detail": "Price ID não configurado no backend."},
                status=500,
            )

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
        params = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "allow_promotion_codes": True,
            "metadata": {"user_id": str(request.user.id)},
        }

        session = s.checkout.Session.create(**params)
        return Response({"checkout_url": session.url}, status=200)


class CreatePortalSession(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Cria uma sessão do Billing Portal para o salão gerenciar a assinatura:
        trocar plano, cancelar, reativar, atualizar cartão, ver faturas.
        """
        s = stripe_utils.get_stripe()
        try:
            customer_id = stripe_utils.get_or_create_customer(request.user)
            return_url = getattr(
                settings, "STRIPE_PORTAL_RETURN_URL", "http://localhost:3000/billing"
            )
            portal = s.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            return Response({"portal_url": portal.url}, status=200)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)


class StripeWebhookView(APIView):
    permission_classes = [AllowAny]  # Stripe não envia credenciais

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
        s = stripe_utils.get_stripe()
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        secret = settings.STRIPE_WEBHOOK_SECRET

        try:
            event = stripe.Webhook.construct_event(
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
                timezone.datetime.fromtimestamp(current_period_end, tz=timezone.utc)
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

            # Detecta plano via interval
            interval = None
            items = stripe_sub.get("items", {}).get("data", [])
            if items:
                price = items[0].get("price")
                if isinstance(price, dict):
                    recurring = price.get("recurring") or {}
                    interval = recurring.get("interval")
            detected_plan = "yearly" if interval == "year" else "monthly"

            # trial_end
            trial_end_ts = stripe_sub.get("trial_end")
            trial_end_dt = (
                timezone.datetime.fromtimestamp(trial_end_ts, tz=timezone.utc)
                if trial_end_ts
                else None
            )

            # start_date (quando o Stripe enviar)
            start_ts = stripe_sub.get("start_date")
            start_dt = (
                timezone.datetime.fromtimestamp(start_ts, tz=timezone.utc)
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

        except Exception:
            # Não derruba o webhook por falhas pontuais
            return HttpResponse(status=200)

        return HttpResponse(status=200)
