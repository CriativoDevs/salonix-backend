import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _
from django.contrib.auth import get_user_model
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from typing import Any, Dict, cast
from rest_framework.views import APIView
from core.mixins import TenantIsolatedMixin
from drf_spectacular.utils import extend_schema
from users.permissions import RequiresMobileAccess
from users.models import TenantStaffMember
from .models import (
    Notification,
    NotificationDevice,
    NotificationLog,
    EmailMarketingCampaign,
)
from core.models import CustomerCommunicationConsent, SalonCustomer
from .serializers import (
    NotificationSerializer,
    NotificationDeviceSerializer,
    NotificationMarkReadSerializer,
    NotificationTestSerializer,
    TestPushNotificationSerializer,
    NotificationLogSerializer,
    NotificationMarkAllReadResponseSerializer,
    NotificationTestResponseSerializer,
    NotificationStatsResponseSerializer,
    CommunicationConsentSerializer,
    CommunicationConsentCreateSerializer,
    CommunicationConsentWithdrawSerializer,
    MarketingCampaignCreateSerializer,
    EmailMarketingCampaignSerializer,
)
from .services import (
    notification_service,
    MobilePushDriver,
    get_eligible_marketing_email_customers,
)
from .credit_service import credit_service
from .tasks import send_marketing_campaign_task

#: Cota mensal grátis de emails de marketing por tenant (BE-MARKETING-04, #522).
MARKETING_EMAIL_FREE_MONTHLY_LIMIT = 50

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationListView(TenantIsolatedMixin, generics.ListAPIView):
    """
    GET /api/notifications/

    Lista notificações in-app do usuário autenticado.
    Suporta filtros: ?is_read=false&limit=20
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, RequiresMobileAccess]
    queryset = Notification.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtrar por usuário autenticado
        queryset = queryset.filter(user=self.request.user)

        # Filtro por status de leitura
        is_read = self.request.query_params.get("is_read")
        if is_read is not None:
            is_read_bool = is_read.lower() in ["true", "1"]
            queryset = queryset.filter(is_read=is_read_bool)

        # Filtro por tipo
        notification_type = self.request.query_params.get("type")
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)

        return queryset.order_by("-created_at")


class NotificationMarkReadView(TenantIsolatedMixin, generics.UpdateAPIView):
    """
    PATCH /api/notifications/{id}/read/

    Marca uma notificação como lida/não lida.
    """

    serializer_class = NotificationMarkReadSerializer
    permission_classes = [IsAuthenticated, RequiresMobileAccess]
    queryset = Notification.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        # Só pode marcar suas próprias notificações
        return queryset.filter(user=self.request.user)

    def patch(self, request, *args, **kwargs):
        notification = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        is_read = serializer.validated_data.get("is_read", True)

        notification.is_read = is_read
        notification.read_at = timezone.now() if is_read else None
        notification.save()

        return Response(
            {
                "id": notification.id,
                "is_read": notification.is_read,
                "read_at": notification.read_at,
            }
        )


class NotificationMarkAllReadView(TenantIsolatedMixin, APIView):
    """
    POST /api/notifications/mark-all-read/

    Marca todas as notificações não lidas do usuário como lidas.
    """

    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(request=None, responses=NotificationMarkAllReadResponseSerializer)
    def post(self, request):
        # Buscar notificações não lidas do usuário no tenant
        queryset = Notification.objects.filter(
            tenant=request.tenant, user=request.user, is_read=False
        )

        # Marcar todas como lidas
        updated_count = queryset.update(is_read=True, read_at=timezone.now())

        logger.info(
            f"Marcadas {updated_count} notificações como lidas",
            extra={
                "tenant_id": request.tenant.id,
                "user_id": request.user.id,
                "updated_count": updated_count,
            },
        )

        return Response(
            {
                "message": f"{updated_count} notificações marcadas como lidas",
                "updated_count": updated_count,
            }
        )


class NotificationDeviceRegisterView(TenantIsolatedMixin, generics.CreateAPIView):
    """
    POST /api/notifications/register_device

    Registra ou atualiza um device token para push notifications.
    """

    serializer_class = NotificationDeviceSerializer
    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    def perform_create(self, serializer):
        # Verificar se já existe device com mesmo token
        existing_device = NotificationDevice.objects.filter(
            tenant=self.request.tenant,
            user=self.request.user,
            device_type=cast(Dict[str, Any], serializer.validated_data)["device_type"],
            token=cast(Dict[str, Any], serializer.validated_data)["token"],
        ).first()

        if existing_device:
            # Atualizar device existente
            existing_device.is_active = cast(
                Dict[str, Any], serializer.validated_data
            ).get("is_active", True)
            existing_device.save()

            logger.info(
                f"Device {existing_device.device_type} atualizado para {self.request.user.username}",
                extra={
                    "tenant_id": self.request.tenant.id,
                    "user_id": self.request.user.id,
                    "device_type": existing_device.device_type,
                },
            )

            # Retornar o device existente
            self.instance = existing_device
        else:
            # Criar novo device - tenant/user são resolvidos no serializer
            device = serializer.save()

            logger.info(
                f"Novo device {device.device_type} registrado para {self.request.user.username}",
                extra={
                    "tenant_id": device.tenant_id,
                    "user_id": device.user_id,
                    "device_type": device.device_type,
                },
            )

            self.instance = device

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # Serializar o device (existente ou novo)
        response_serializer = self.get_serializer(self.instance)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class NotificationTestView(TenantIsolatedMixin, APIView):
    """
    POST /api/notifications/test

    Testa um canal específico de notificação.
    """

    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(
        request=NotificationTestSerializer,
        responses=NotificationTestResponseSerializer,
    )
    def post(self, request):
        serializer = NotificationTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        v = cast(Dict[str, Any], serializer.validated_data)
        channel = v["channel"]
        message = v["message"]

        # Testar o canal
        success = notification_service.test_channel(
            tenant=request.tenant, user=request.user, channel=channel, message=message
        )

        logger.info(
            f"Teste de canal {channel} para {request.user.username}: {'sucesso' if success else 'falha'}",
            extra={
                "tenant_id": request.tenant.id,
                "user_id": request.user.id,
                "channel": channel,
                "success": success,
            },
        )

        return Response(
            {
                "channel": channel,
                "success": success,
                "message": (
                    "Notificação de teste enviada com sucesso"
                    if success
                    else "Falha ao enviar notificação de teste"
                ),
            }
        )


class TestPushNotificationView(TenantIsolatedMixin, APIView):
    """
    POST /api/notifications/test-push/

    Testa envio de push notification mobile (Expo) para um usuário específico.
    Apenas para admins/staff.
    """

    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(
        request=TestPushNotificationSerializer,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "message": {"type": "string"},
                    "user_id": {"type": "integer"},
                    "has_device": {"type": "boolean"},
                },
            }
        },
    )
    def post(self, request):
        # Apenas admins/staff podem usar este endpoint
        if not request.user.is_staff:
            return Response(
                {"error": "Apenas administradores podem testar push notifications"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TestPushNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        v = cast(Dict[str, Any], serializer.validated_data)
        user_id = v["user_id"]
        title = v["title"]
        message = v["message"]
        appointment_id = v.get("appointment_id")

        # Buscar usuário no tenant
        try:
            user = User.objects.get(id=user_id, tenant=request.tenant)
        except User.DoesNotExist:
            return Response(
                {"error": f"Usuário {user_id} não encontrado no tenant"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Verificar se tem device registrado
        has_device = NotificationDevice.objects.filter(
            tenant=request.tenant, user=user, device_type="mobile", is_active=True
        ).exists()

        if not has_device:
            return Response(
                {
                    "success": False,
                    "message": f"Usuário {user.username} não tem dispositivo mobile registrado",
                    "user_id": user_id,
                    "has_device": False,
                }
            )

        # Preparar metadata com deep link se houver appointment_id
        metadata = {}
        if appointment_id:
            metadata["appointment_id"] = appointment_id

        # Enviar push
        driver = MobilePushDriver()
        success = driver.send(
            tenant=request.tenant,
            user=user,
            notification_type="test",
            title=title,
            message=message,
            metadata=metadata,
        )

        logger.info(
            f"Teste de push para {user.username}: {'sucesso' if success else 'falha'}",
            extra={
                "tenant_id": request.tenant.id,
                "user_id": user.id,
                "requester_id": request.user.id,
                "success": success,
            },
        )

        return Response(
            {
                "success": success,
                "message": (
                    f"Push enviado com sucesso para {user.username}"
                    if success
                    else f"Falha ao enviar push para {user.username}"
                ),
                "user_id": user_id,
                "has_device": True,
            }
        )


class NotificationStatsView(TenantIsolatedMixin, APIView):
    """
    GET /api/notifications/stats

    Estatísticas de notificações do usuário.
    """

    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(responses=NotificationStatsResponseSerializer)
    def get(self, request):
        # Contar notificações do usuário no tenant
        total_notifications = Notification.objects.filter(
            tenant=request.tenant, user=request.user
        ).count()

        unread_notifications = Notification.objects.filter(
            tenant=request.tenant, user=request.user, is_read=False
        ).count()

        # Contar devices registrados
        registered_devices = NotificationDevice.objects.filter(
            tenant=request.tenant, user=request.user, is_active=True
        ).count()

        return Response(
            {
                "total_notifications": total_notifications,
                "unread_notifications": unread_notifications,
                "read_notifications": total_notifications - unread_notifications,
                "registered_devices": registered_devices,
            }
        )


class NotificationLogListView(TenantIsolatedMixin, generics.ListAPIView):
    """
    GET /api/notifications/logs/

    Lista logs de notificações (apenas para debug/admin).
    Endpoint privado para debugging.
    """

    serializer_class = NotificationLogSerializer
    permission_classes = [IsAuthenticated, RequiresMobileAccess]
    queryset = NotificationLog.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()

        # Apenas superusers podem ver todos os logs
        if not self.request.user.is_superuser:
            queryset = queryset.filter(user=self.request.user)

        # Filtros opcionais
        channel = self.request.query_params.get("channel")
        if channel:
            queryset = queryset.filter(channel=channel)

        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by("-created_at")


class CommunicationConsentListView(TenantIsolatedMixin, generics.ListAPIView):
    """
    GET /api/notifications/consent/

    Lista consents de comunicação por cliente (e filtros opcionais).
    Retorno: 200 com lista de consentimentos.
    Erros: 400 para parâmetros inválidos.
    """

    serializer_class = CommunicationConsentSerializer
    permission_classes = [IsAuthenticated, RequiresMobileAccess]
    queryset = CustomerCommunicationConsent.objects.all()

    @extend_schema(parameters=[])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        customer_id = self.request.query_params.get("customer_id")
        if customer_id:
            qs = qs.filter(customer_id=int(customer_id))
        channel = self.request.query_params.get("channel")
        if channel:
            qs = qs.filter(channel=channel)
        purpose = self.request.query_params.get("purpose")
        if purpose:
            qs = qs.filter(purpose=purpose)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs.order_by("customer_id", "channel", "purpose")


class CommunicationConsentCreateView(TenantIsolatedMixin, APIView):
    """
    POST /api/notifications/consent/

    Cria/atualiza consentimento: status=consented e consented_at=agora.
    Retorno: 201 com consentimento atualizado/criado.
    Erros: 400 (validação de campos), 404 (cliente não encontrado).
    """

    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(
        request=CommunicationConsentCreateSerializer,
        responses=CommunicationConsentSerializer,
    )
    def post(self, request):
        s = CommunicationConsentCreateSerializer(
            data=request.data, context={"request": request}
        )
        s.is_valid(raise_exception=True)
        v = s.validated_data
        tenant = getattr(request, "tenant", None) or getattr(
            request.user, "tenant", None
        )
        customer_id = v.get("customer_id") or request.data.get("customer_id")
        channel = v.get("channel") or request.data.get("channel")
        purpose = v.get("purpose") or request.data.get("purpose")

        instance = CustomerCommunicationConsent.objects.filter(
            tenant=tenant, customer_id=customer_id, channel=channel, purpose=purpose
        ).first()

        now = timezone.now()
        payload = {
            "source": v.get("source"),
            "ip_address": v.get("ip_address"),
            "user_agent": v.get("user_agent"),
            "version": v.get("version"),
            "locale": v.get("locale"),
        }

        if instance:
            instance.status = "consented"
            instance.consented_at = now
            instance.withdrawn_at = None
            for k, val in payload.items():
                setattr(instance, k, val)
            instance.save()
        else:
            customer = SalonCustomer.objects.get(id=customer_id)
            instance = CustomerCommunicationConsent.objects.create(
                tenant=tenant,
                customer=customer,
                channel=channel,
                purpose=purpose,
                status="consented",
                consented_at=now,
                **payload,
            )

        return Response(
            CommunicationConsentSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )


class CommunicationConsentWithdrawView(TenantIsolatedMixin, APIView):
    """
    POST /api/notifications/consent/withdraw/

    Registra retirada de consentimento: status=withdrawn e withdrawn_at=agora.
    Retorno: 200 com consentimento atualizado/criado.
    Erros: 400 (validação de campos), 404 (cliente não encontrado).
    """

    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(
        request=CommunicationConsentWithdrawSerializer,
        responses=CommunicationConsentSerializer,
    )
    def post(self, request):
        s = CommunicationConsentWithdrawSerializer(
            data=request.data, context={"request": request}
        )
        s.is_valid(raise_exception=True)
        v = s.validated_data
        tenant = getattr(request, "tenant", None) or getattr(
            request.user, "tenant", None
        )
        customer_id = v.get("customer_id") or request.data.get("customer_id")
        channel = v.get("channel") or request.data.get("channel")
        purpose = v.get("purpose") or request.data.get("purpose")

        instance = CustomerCommunicationConsent.objects.filter(
            tenant=tenant, customer_id=customer_id, channel=channel, purpose=purpose
        ).first()

        now = timezone.now()
        payload = {
            "source": v.get("source"),
            "ip_address": v.get("ip_address"),
            "user_agent": v.get("user_agent"),
        }

        if instance:
            instance.status = "withdrawn"
            instance.withdrawn_at = now
            for k, val in payload.items():
                setattr(instance, k, val)
            instance.save()
        else:
            customer = SalonCustomer.objects.get(id=customer_id)
            instance = CustomerCommunicationConsent.objects.create(
                tenant=tenant,
                customer=customer,
                channel=channel,
                purpose=purpose,
                status="withdrawn",
                withdrawn_at=now,
                **payload,
            )

        return Response(CommunicationConsentSerializer(instance).data)


class MarketingCampaignListCreateView(TenantIsolatedMixin, generics.ListCreateAPIView):
    """
    GET  /api/notifications/marketing-campaigns/  — histórico de campanhas do tenant.
    POST /api/notifications/marketing-campaigns/  — compõe e dispara uma campanha
                                                      (BE-MARKETING-04, #522).

    Restrito a owner/manager (mesmo critério de `VoucherViewSet` — envolve
    comunicação com toda a base de clientes e consumo de crédito).

    A criação resolve, de forma síncrona e atômica, quem entra em cada
    balde: elegíveis (consentimento ativo + email), pulados por falta de
    consentimento/unsubscribe, cobertos pela cota mensal grátis (50/mês),
    cobrados do crédito de comunicação (mesmo pool do SMS/WhatsApp) e
    bloqueados por falta de crédito. O envio de fato é sempre assíncrono
    (`send_marketing_campaign_task`), nunca síncrono na view.
    """

    serializer_class = EmailMarketingCampaignSerializer
    permission_classes = [IsAuthenticated]
    queryset = EmailMarketingCampaign.objects.all()

    def _resolve_tenant(self):
        return getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )

    def _require_owner_or_manager(self):
        if not (
            self.request.user.is_superuser
            or self.request.user.has_staff_role(
                TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
            )
        ):
            raise PermissionDenied(
                "Apenas owner ou manager podem disparar campanhas de email marketing."
            )

    def get_queryset(self):
        return super().get_queryset().order_by("-created_at")

    def _already_sent_this_month(self, tenant) -> int:
        now = timezone.now()
        aggregate = EmailMarketingCampaign.objects.filter(
            tenant=tenant,
            created_at__year=now.year,
            created_at__month=now.month,
        ).aggregate(
            free=Sum("free_sent_count"), credit=Sum("credit_sent_count")
        )
        return (aggregate["free"] or 0) + (aggregate["credit"] or 0)

    def create(self, request, *args, **kwargs):
        self._require_owner_or_manager()

        tenant = self._resolve_tenant()
        if tenant is None:
            raise PermissionDenied("Tenant não encontrado para o usuário.")

        input_serializer = MarketingCampaignCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        v = input_serializer.validated_data
        subject = v["subject"]
        body = v["body"]
        reply_to = v.get("reply_to") or None

        with transaction.atomic():
            # select_for_update evita duas campanhas concorrentes lerem o
            # mesmo saldo de crédito e ambas acharem que "cabe" o excedente.
            tenant = type(tenant).objects.select_for_update().get(pk=tenant.pk)

            eligible_qs = get_eligible_marketing_email_customers(tenant)
            eligible_customers = list(eligible_qs)
            eligible_count = len(eligible_customers)

            total_with_email = (
                SalonCustomer.objects.filter(tenant=tenant)
                .exclude(email__isnull=True)
                .exclude(email="")
                .count()
            )
            skipped_no_consent_count = max(0, total_with_email - eligible_count)

            already_sent = self._already_sent_this_month(tenant)
            free_remaining = max(0, MARKETING_EMAIL_FREE_MONTHLY_LIMIT - already_sent)

            to_send_free = eligible_customers[:free_remaining]
            remaining = eligible_customers[free_remaining:]

            to_send_credit = []
            blocked = []
            credit_exhausted = False
            for customer in remaining:
                if credit_exhausted:
                    blocked.append(customer)
                    continue
                charge_result = credit_service.charge_for_message(
                    tenant=tenant,
                    communication_type="email",
                    description=f"Email marketing - campanha '{subject}'",
                    user=request.user,
                )
                if charge_result["success"]:
                    to_send_credit.append(customer)
                else:
                    credit_exhausted = True
                    blocked.append(customer)

            to_send = to_send_free + to_send_credit
            credit_charged_eur = Decimal(len(to_send_credit)) * credit_service.get_cost(
                tenant, "email"
            )

            campaign = EmailMarketingCampaign.objects.create(
                tenant=tenant,
                created_by=request.user if request.user.is_authenticated else None,
                subject=subject,
                body=body,
                reply_to=reply_to,
                status=(
                    EmailMarketingCampaign.Status.COMPLETED
                    if not to_send
                    else EmailMarketingCampaign.Status.QUEUED
                ),
                eligible_count=eligible_count,
                skipped_no_consent_count=skipped_no_consent_count,
                free_sent_count=len(to_send_free),
                credit_sent_count=len(to_send_credit),
                credit_charged_eur=credit_charged_eur,
                blocked_credit_count=len(blocked),
                completed_at=timezone.now() if not to_send else None,
            )

        if to_send:
            send_marketing_campaign_task.delay(
                campaign.id, [c.id for c in to_send]
            )

        logger.info(
            "marketing_campaign_created",
            extra={
                "campaign_id": campaign.id,
                "tenant_id": tenant.id,
                "eligible_count": eligible_count,
                "free_sent_count": campaign.free_sent_count,
                "credit_sent_count": campaign.credit_sent_count,
                "blocked_credit_count": campaign.blocked_credit_count,
                "skipped_no_consent_count": campaign.skipped_no_consent_count,
            },
        )

        return Response(
            EmailMarketingCampaignSerializer(campaign).data,
            status=status.HTTP_201_CREATED,
        )


UNSUBSCRIBE_TOKEN_SALT = "comm-consent-unsub"


class PublicUnsubscribeView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(parameters=[], responses=CommunicationConsentSerializer)
    def get(self, request):
        token = request.query_params.get("token")
        if not token:
            return Response(
                {"error": _("token ausente")}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            payload = signing.loads(token, salt=UNSUBSCRIBE_TOKEN_SALT)
        except Exception:
            return Response(
                {"error": _("token inválido")}, status=status.HTTP_400_BAD_REQUEST
            )

        tenant_id = payload.get("tenant_id")
        customer_id = payload.get("customer_id")
        channel = payload.get("channel")
        purpose = payload.get("purpose")
        if not all([tenant_id, customer_id, channel, purpose]):
            return Response(
                {"error": _("token incompleto")}, status=status.HTTP_400_BAD_REQUEST
            )

        instance = CustomerCommunicationConsent.objects.filter(
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel=channel,
            purpose=purpose,
        ).first()

        now = timezone.now()
        if instance:
            instance.status = "withdrawn"
            instance.withdrawn_at = now
            instance.save()
        else:
            customer = SalonCustomer.objects.get(id=customer_id)
            instance = CustomerCommunicationConsent.objects.create(
                tenant_id=tenant_id,
                customer=customer,
                channel=channel,
                purpose=purpose,
                status="withdrawn",
                withdrawn_at=now,
            )

        return Response(CommunicationConsentSerializer(instance).data)
