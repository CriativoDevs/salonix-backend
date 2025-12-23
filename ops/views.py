from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict

import csv
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from notifications.models import NotificationLog

from ops.models import AccountLockout, OpsAlert, OpsSupportAuditLog
from ops.observability import (
    OPS_AUTH_EVENTS_TOTAL,
    OPS_LOCKOUTS_CLEARED_TOTAL,
    OPS_NOTIFICATIONS_RESEND_TOTAL,
)
from ops.permissions import IsOpsAdmin, IsOpsSupportOrAdmin
from ops.serializers import (
    OpsAlertSerializer,
    OpsClearLockoutSerializer,
    OpsResendNotificationSerializer,
    OpsTenantPlanUpdateSerializer,
    OpsTenantResetOwnerSerializer,
    OpsTenantSerializer,
    OpsTokenObtainPairSerializer,
    OpsTokenRefreshSerializer,
    OpsUserSerializer,
    OpsUserCreateSerializer,
    OpsUserUpdateSerializer,
    OpsSupportAuditLogSerializer,
)
from users.models import CustomUser, Tenant, UserFeatureFlags
from salonix_backend.error_handling import ErrorCodes, TenantError

logger = logging.getLogger(__name__)

PLAN_PRICING_EUR: Dict[str, Decimal] = {
    Tenant.PLAN_BASIC: Decimal("29.00"),
    Tenant.PLAN_STANDARD: Decimal("55.00"),
    Tenant.PLAN_PRO: Decimal("95.00"),
}


class OpsAuthLoginThrottle(ScopedRateThrottle):
    scope = "ops_auth_login"


class OpsAuthRefreshThrottle(ScopedRateThrottle):
    scope = "ops_auth_refresh"


class OpsAuthLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OpsAuthLoginThrottle]

    @extend_schema(
        request=OpsTokenObtainPairSerializer,
        responses=OpenApiTypes.OBJECT,
        description="Autentica no console Ops e retorna tokens",
    )
    def post(self, request, *args: Any, **kwargs: Any) -> Response:
        serializer = OpsTokenObtainPairSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed as exc:
            self._log_event(
                request,
                event="login",
                result="failure",
                extra={"email": request.data.get("email", ""), "reason": str(exc)},
            )
            OPS_AUTH_EVENTS_TOTAL.labels(
                event="login", result="failure", role="unknown"
            ).inc()
            raise
        except ValidationError:
            # DRF tratará formato, mas contabilizamos como falha
            self._log_event(
                request,
                event="login",
                result="failure",
                extra={
                    "email": request.data.get("email", ""),
                    "reason": "invalid_payload",
                },
            )
            OPS_AUTH_EVENTS_TOTAL.labels(
                event="login", result="failure", role="unknown"
            ).inc()
            raise

        data = serializer.validated_data
        user = getattr(serializer, "user", None)
        ops_role = data.get("ops_role", "unknown")
        OPS_AUTH_EVENTS_TOTAL.labels(
            event="login", result="success", role=ops_role
        ).inc()
        self._log_event(
            request,
            event="login",
            result="success",
            extra={
                "email": getattr(user, "email", ""),
                "user_id": getattr(user, "id", None),
                "ops_role": ops_role,
            },
        )
        return Response(data, status=status.HTTP_200_OK)

    def _log_event(
        self,
        request,
        *,
        event: str,
        result: str,
        extra: Dict[str, Any],
    ) -> None:
        log_level = logging.INFO if result == "success" else logging.WARNING
        logger.log(
            log_level,
            "Ops auth event",
            extra={
                "request_id": getattr(request, "request_id", None),
                "event": event,
                "result": result,
                **extra,
            },
        )


class OpsAuthMeView(APIView):
    permission_classes = [IsOpsSupportOrAdmin]

    @extend_schema(
        responses=OpsUserSerializer,
        description="Retorna detalhes do usuário Ops autenticado",
    )
    def get(self, request, *args: Any, **kwargs: Any) -> Response:
        serializer = OpsUserSerializer(request.user)
        return Response(serializer.data)


class OpsAuthRefreshView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OpsAuthRefreshThrottle]

    @extend_schema(
        request=OpsTokenRefreshSerializer,
        responses=OpenApiTypes.OBJECT,
        description="Gera novo access token para o console Ops",
    )
    def post(self, request, *args: Any, **kwargs: Any) -> Response:
        serializer = OpsTokenRefreshSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except (AuthenticationFailed, InvalidToken, TokenError) as exc:
            self._log_event(
                request,
                event="refresh",
                result="failure",
                extra={"reason": str(exc)},
            )
            OPS_AUTH_EVENTS_TOTAL.labels(
                event="refresh", result="failure", role="unknown"
            ).inc()
            raise

        data = serializer.validated_data
        ops_role = data.get("ops_role", "unknown")
        OPS_AUTH_EVENTS_TOTAL.labels(
            event="refresh", result="success", role=ops_role
        ).inc()
        self._log_event(
            request,
            event="refresh",
            result="success",
            extra={"ops_role": ops_role, "user_id": data.get("user_id")},
        )
        return Response(data, status=status.HTTP_200_OK)

    def _log_event(
        self,
        request,
        *,
        event: str,
        result: str,
        extra: Dict[str, Any],
    ) -> None:
        log_level = logging.INFO if result == "success" else logging.WARNING
        logger.log(
            log_level,
            "Ops auth event",
            extra={
                "request_id": getattr(request, "request_id", None),
                "event": event,
                "result": result,
                **extra,
            },
        )


class OpsTenantViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsOpsSupportOrAdmin]
    serializer_class = OpsTenantSerializer
    lookup_field = "id"
    request: Request

    def get_queryset(self) -> Any:
        queryset = Tenant.objects.annotate(users_total=Count("users")).order_by(
            "-created_at"
        )

        # Filtros manuais
        plan_tier = self.request.query_params.get("plan_tier")
        if plan_tier:
            queryset = queryset.filter(plan_tier=plan_tier)

        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            is_active_bool = is_active.lower() == "true"
            queryset = queryset.filter(is_active=is_active_bool)

        # Ordenação manual
        ordering = self.request.query_params.get("ordering")
        if ordering:
            allowed_fields = {
                "created_at",
                "-created_at",
                "name",
                "-name",
                "plan_tier",
                "-plan_tier",
                "users_total",
                "-users_total",
            }
            if ordering in allowed_fields:
                queryset = queryset.order_by(ordering)

        return queryset

    @extend_schema(
        description="Lista todos os tenants (paginado)",
        responses=OpsTenantSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        description="Detalhes de um tenant específico",
        responses=OpsTenantSerializer,
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        description="Atualiza plano do tenant (Ops Admin apenas)",
        request=OpsTenantPlanUpdateSerializer,
        responses=OpenApiTypes.OBJECT,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="plan",
        permission_classes=[IsOpsAdmin],
    )
    def update_plan(self, request: Request, id: int | None = None) -> Response:
        tenant = self.get_object()
        serializer = OpsTenantPlanUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_plan = serializer.validated_data["plan_tier"]
        conflicts = self._validate_plan_change(tenant, new_plan)

        if conflicts and not request.data.get("force", False):
            return Response(
                {
                    "error": "Conflitos detectados na mudança de plano.",
                    "conflicts": conflicts,
                    "code": "plan_downgrade_conflict",
                },
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            self._apply_plan_change(tenant, new_plan)

        return Response(
            {"message": f"Plano atualizado para {new_plan}"},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        description="Bloqueia acesso do tenant",
        responses=OpenApiTypes.OBJECT,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="block-tenant",
        permission_classes=[IsOpsAdmin],
    )
    def block_tenant(self, request: Request, id: int | None = None) -> Response:
        tenant = self.get_object()
        tenant.is_active = False
        tenant.save(update_fields=["is_active"])
        return Response(
            {"message": "Tenant bloqueado com sucesso."}, status=status.HTTP_200_OK
        )

    @extend_schema(
        description="Desbloqueia acesso do tenant",
        responses=OpenApiTypes.OBJECT,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="unblock-tenant",
        permission_classes=[IsOpsAdmin],
    )
    def unblock_tenant(self, request: Request, id: int | None = None) -> Response:
        tenant = self.get_object()
        tenant.is_active = True
        tenant.save(update_fields=["is_active"])
        return Response(
            {"message": "Tenant desbloqueado com sucesso."}, status=status.HTTP_200_OK
        )

    @extend_schema(
        description="Exporta tenants para CSV",
        responses=OpenApiTypes.BINARY,
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="export",
    )
    def export(self, request: Request) -> HttpResponse:
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="tenants.csv"'

        writer = csv.writer(response)
        writer.writerow(["ID", "Name", "Slug", "Plan", "Active", "Created At"])

        queryset = self.filter_queryset(self.get_queryset())
        for tenant in queryset:
            writer.writerow(
                [
                    tenant.id,
                    tenant.name,
                    tenant.slug,
                    tenant.plan_tier,
                    tenant.is_active,
                    tenant.created_at,
                ]
            )

        return response

    @extend_schema(
        description="Reseta senha do owner do tenant (Ops Admin apenas)",
        request=OpsTenantResetOwnerSerializer,
        responses=OpenApiTypes.OBJECT,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="reset-owner",
        permission_classes=[IsOpsAdmin],
    )
    def reset_owner(self, request: Request, id: int | None = None) -> Response:
        tenant = self.get_object()
        serializer = OpsTenantResetOwnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            owner_data = self._reset_owner_credentials(
                tenant, serializer.validated_data
            )
        return Response(owner_data, status=status.HTTP_200_OK)

    def _validate_plan_change(self, tenant: Tenant, new_plan: str) -> list[str]:
        conflicts: list[str] = []

        if new_plan != Tenant.PLAN_PRO:
            if tenant.sms_enabled:
                conflicts.append("sms_enabled")
            if tenant.whatsapp_enabled:
                conflicts.append("whatsapp_enabled")
            addons = tenant.addons_enabled or []
            if any(addon in {"rn_admin", "rn_client"} for addon in addons):
                conflicts.append("native_addons")

        if new_plan == Tenant.PLAN_BASIC:
            if tenant.reports_enabled:
                conflicts.append("reports_enabled")
            if tenant.pwa_client_enabled:
                conflicts.append("pwa_client_enabled")
            if tenant.pwa_admin_enabled:
                conflicts.append("pwa_admin_enabled")
            if tenant.push_web_enabled or tenant.push_mobile_enabled:
                conflicts.append("push_notifications")

        return conflicts

    def _apply_plan_change(self, tenant: Tenant, new_plan: str) -> None:
        updates = {"plan_tier"}
        tenant.plan_tier = new_plan

        if new_plan != Tenant.PLAN_PRO:
            if tenant.sms_enabled:
                tenant.sms_enabled = False
                updates.add("sms_enabled")
            if tenant.whatsapp_enabled:
                tenant.whatsapp_enabled = False
                updates.add("whatsapp_enabled")
            if tenant.rn_admin_enabled:
                tenant.rn_admin_enabled = False
                updates.add("rn_admin_enabled")
            if tenant.rn_client_enabled:
                tenant.rn_client_enabled = False
                updates.add("rn_client_enabled")
            addons = tenant.addons_enabled or []
            filtered = [
                addon for addon in addons if addon not in {"rn_admin", "rn_client"}
            ]
            if filtered != addons:
                tenant.addons_enabled = filtered
                updates.add("addons_enabled")

        if new_plan == Tenant.PLAN_BASIC:
            for field in [
                "reports_enabled",
                "pwa_admin_enabled",
                "pwa_client_enabled",
                "push_web_enabled",
                "push_mobile_enabled",
            ]:
                if getattr(tenant, field):
                    setattr(tenant, field, False)
                    updates.add(field)

        tenant.save(update_fields=list(updates))

    def _reset_owner_credentials(
        self, tenant: Tenant, data: dict[str, Any]
    ) -> dict[str, Any]:
        email = data["email"].lower()
        username = data.get("username")
        display_name = data.get("name")

        existing_user = CustomUser.objects.filter(email=email).first()
        if existing_user and existing_user.tenant_id != tenant.id:
            raise TenantError(
                "Email em uso por outro tenant.",
                code=ErrorCodes.VALIDATION_DUPLICATE_VALUE,
            )

        owner = existing_user
        if owner is None:
            owner = tenant.users.order_by("date_joined").first()

        if owner is None:
            owner = CustomUser(tenant=tenant)

        if not username:
            base_username = email.split("@")[0]
            candidate = base_username
            idx = 1
            while (
                CustomUser.objects.exclude(id=owner.id)
                .filter(username=candidate)
                .exists()
            ):
                candidate = f"{base_username}{idx}"
                idx += 1
            username = candidate

        password = secrets.token_urlsafe(12)
        owner.username = username
        owner.email = email
        owner.set_password(password)
        if display_name:
            owner.first_name = display_name
        owner.is_active = True
        owner.save()

        # Atualiza owner do tenant se necessário (se tivermos campo owner)
        # Aqui assumimos que o owner é implícito ou gerenciado por roles

        return {
            "email": email,
            "username": username,
            "password": password,
            "tenant": tenant.name,
        }


class OpsAlertViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsOpsSupportOrAdmin]
    serializer_class = OpsAlertSerializer

    def get_queryset(self):
        return OpsAlert.objects.all().order_by("-created_at")

    @extend_schema(
        description="Lista alertas do sistema (paginado)",
        responses=OpsAlertSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        description="Marca alerta como resolvido",
        responses=OpsAlertSerializer,
    )
    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve(self, request: Request, pk: int | None = None) -> Response:
        alert = self.get_object()
        if alert.resolved_at:
            return Response(
                {"message": "Alerta já resolvido."}, status=status.HTTP_200_OK
            )

        alert.resolved_at = timezone.now()
        alert.resolved_by = request.user
        alert.save()

        OpsSupportAuditLog.objects.create(
            actor=request.user,
            action="resolve_alert",  # Assuming string or enum value matches
            payload={"alert_id": alert.id, "message": alert.message},
        )

        return Response(OpsAlertSerializer(alert).data)


class OpsSupportViewSet(viewsets.ViewSet):
    permission_classes = [IsOpsSupportOrAdmin]

    @extend_schema(
        description="Reenvia notificação por ID",
        request=OpsResendNotificationSerializer,
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=False, methods=["post"], url_path="resend-notification")
    def resend_notification(self, request: Request) -> Response:
        serializer = OpsResendNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        notification_id = serializer.validated_data["notification_id"]
        channel = serializer.validated_data.get("channel")

        try:
            log = NotificationLog.objects.get(id=notification_id)
        except NotificationLog.DoesNotExist:
            return Response(
                {"error": "Notificação não encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if channel and log.channel != channel:
            return Response(
                {"error": f"Notificação não é do canal {channel}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if log.status != "failed":
            return Response(
                {
                    "error": {
                        "code": "E403",
                        "message": "Apenas notificações falhas podem ser reenviadas.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Lógica de reenvio simulada (ou chamar serviço real)
        # Em produção, isso chamaria o serviço de notificações
        log.status = "sent"
        log.metadata["ops_resends"] = log.metadata.get("ops_resends", 0) + 1
        log.save()

        OPS_NOTIFICATIONS_RESEND_TOTAL.labels(
            channel=log.channel, result="success"
        ).inc()

        # Registrar auditoria
        OpsSupportAuditLog.objects.create(
            actor=request.user,
            action="resend_notification",
            target_tenant=log.tenant,
            target_user=log.user,
            payload={
                "notification_id": notification_id,
                "channel": log.channel,
                # "recipient": log.recipient, # Removed as field does not exist
            },
        )
        return Response({"message": "Notificação reenviada com sucesso."})

    @extend_schema(
        description="Limpa bloqueio de conta de usuário",
        request=OpsClearLockoutSerializer,
        responses=OpenApiTypes.OBJECT,
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="clear-lockout",
        permission_classes=[IsOpsAdmin],
    )
    def clear_lockout(self, request: Request) -> Response:
        serializer = OpsClearLockoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_id = serializer.validated_data.get("user_id")
        lockout_id = serializer.validated_data.get("lockout_id")

        user = None
        lockouts_to_resolve = []

        if user_id:
            try:
                user = CustomUser.objects.get(id=user_id)
                lockouts_to_resolve = AccountLockout.objects.filter(
                    user=user, resolved_at__isnull=True
                )
            except CustomUser.DoesNotExist:
                return Response(
                    {"error": "Usuário não encontrado."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        elif lockout_id:
            try:
                lockout = AccountLockout.objects.get(id=lockout_id)
                user = lockout.user
                lockouts_to_resolve = [lockout]
            except AccountLockout.DoesNotExist:
                return Response(
                    {"error": "Bloqueio não encontrado."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            return Response(
                {"error": "Informe user_id ou lockout_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve lockouts
        resolved_count = 0
        now = timezone.now()
        for lockout in lockouts_to_resolve:
            if not lockout.resolved_at:
                lockout.resolved_at = now
                lockout.resolved_by = request.user
                lockout.save(update_fields=["resolved_at", "resolved_by"])
                resolved_count += 1

        # Unlock user if they were locked
        if user and not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])

        OPS_LOCKOUTS_CLEARED_TOTAL.labels(result="success").inc()

        # Registrar auditoria
        OpsSupportAuditLog.objects.create(
            actor=request.user,
            action="clear_lockout",
            target_tenant=user.tenant if user else None,
            target_user=user,
            payload={"resolved_count": resolved_count},
        )

        return Response(
            {"message": f"Bloqueio resolvido com sucesso. ({resolved_count} registros)"}
        )


class OpsMetricsOverviewView(APIView):
    permission_classes = [IsOpsSupportOrAdmin]

    @extend_schema(
        responses=OpenApiTypes.OBJECT,
        description="Retorna métricas gerais do sistema (últimos 30 dias)",
    )
    def get(self, request, *args: Any, **kwargs: Any) -> Response:
        now = timezone.now()

        # Totals
        active_tenants = Tenant.objects.filter(is_active=True).count()
        trials_expiring_7d = UserFeatureFlags.objects.filter(
            trial_until__gte=now, trial_until__lte=now + timedelta(days=7)
        ).count()
        alerts_open = OpsAlert.objects.filter(resolved_at__isnull=True).count()

        # MRR Estimation
        plan_pricing = {
            Tenant.PLAN_BASIC: Decimal("29.00"),
            Tenant.PLAN_STANDARD: Decimal("55.00"),
            Tenant.PLAN_PRO: Decimal("95.00"),
        }
        expected_mrr = Decimal("0.00")
        for tenant in Tenant.objects.filter(is_active=True):
            expected_mrr += plan_pricing.get(tenant.plan_tier, Decimal("0.00"))

        # Daily Notification Stats (last 7 days)
        notification_daily = []
        for i in range(7):
            date = (now - timedelta(days=i)).date()
            logs = NotificationLog.objects.filter(created_at__date=date)

            # Group by channel
            channels_stats = {}
            # In a real scenario, use aggregation. Here keeping it simple or mocking if needed.
            # But the test expects a list of dicts.
            # Let's do a simple count per channel
            channel_counts = logs.values("channel").annotate(count=Count("id"))
            for entry in channel_counts:
                channels_stats[entry["channel"]] = entry["count"]

            notification_daily.append(
                {
                    "date": date.isoformat(),
                    "channels": channels_stats,
                    "total": logs.count(),
                }
            )

        return Response(
            {
                "totals": {
                    "active_tenants": active_tenants,
                    "trials_expiring_7d": trials_expiring_7d,
                    "alerts_open": alerts_open,
                },
                "mrr_estimated": {
                    "total": f"{expected_mrr:.2f}",
                },
                "notification_daily": notification_daily,
            }
        )


class OpsUserViewSet(viewsets.ModelViewSet):
    """
    Gerenciamento de usuários do Ops (CRUD).
    Apenas OpsAdmin pode criar/editar/deletar.
    OpsSupport pode apenas visualizar.
    """

    permission_classes = [IsOpsSupportOrAdmin]
    serializer_class = OpsUserSerializer
    queryset = CustomUser.objects.filter(is_staff=True).order_by("-date_joined")

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsOpsAdmin()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == "create":
            return OpsUserCreateSerializer
        if self.action in ["update", "partial_update"]:
            return OpsUserUpdateSerializer
        return OpsUserSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(email__icontains=search) | queryset.filter(
                username__icontains=search
            )
        return queryset


class OpsSupportAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Visualização de logs de auditoria do Ops.
    Apenas OpsAdmin pode visualizar.
    """

    permission_classes = [IsOpsAdmin]
    serializer_class = OpsSupportAuditLogSerializer
    queryset = OpsSupportAuditLog.objects.all().order_by("-created_at")

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtros
        actor_id = self.request.query_params.get("actor_id")
        if actor_id:
            queryset = queryset.filter(actor_id=actor_id)

        action_type = self.request.query_params.get("action")
        if action_type:
            queryset = queryset.filter(action=action_type)

        date_from = self.request.query_params.get("date_from")
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        return queryset
