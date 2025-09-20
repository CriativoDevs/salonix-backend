from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict

import csv
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from notifications.models import NotificationLog
from notifications.services import NotificationService

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
)
from users.models import CustomUser, Tenant, UserFeatureFlags
from salonix_backend.error_handling import BusinessError, ErrorCodes, TenantError

logger = logging.getLogger(__name__)

PLAN_PRICING_EUR: Dict[str, Decimal] = {
    Tenant.PLAN_BASIC: Decimal("29.00"),
    Tenant.PLAN_STANDARD: Decimal("59.00"),
    Tenant.PLAN_PRO: Decimal("99.00"),
}


class OpsAuthLoginThrottle(ScopedRateThrottle):
    scope = "ops_auth_login"


class OpsAuthRefreshThrottle(ScopedRateThrottle):
    scope = "ops_auth_refresh"


class OpsAuthLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OpsAuthLoginThrottle]

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
                extra={"email": request.data.get("email", ""), "reason": "invalid_payload"},
            )
            OPS_AUTH_EVENTS_TOTAL.labels(
                event="login", result="failure", role="unknown"
            ).inc()
            raise

        data = serializer.validated_data
        user = getattr(serializer, "user", None)
        ops_role = data.get("ops_role", "unknown")
        OPS_AUTH_EVENTS_TOTAL.labels(event="login", result="success", role=ops_role).inc()
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


class OpsAuthRefreshView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OpsAuthRefreshThrottle]

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
        OPS_AUTH_EVENTS_TOTAL.labels(event="refresh", result="success", role=ops_role).inc()
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


class OpsTenantPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class OpsTenantViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Endpoints de gestão de tenants para o console Ops."""

    serializer_class = OpsTenantSerializer
    pagination_class = OpsTenantPagination
    permission_classes = [IsOpsSupportOrAdmin]

    NOTIFICATION_SUCCESS_STATUSES = {"sent", "delivered"}
    EXPORT_FILENAME = "ops-tenants-export.csv"

    def get_queryset(self):
        queryset = Tenant.objects.all()

        thirty_days_ago = timezone.now() - timedelta(days=30)

        owner_subquery = (
            CustomUser.objects.filter(tenant=OuterRef("pk")).order_by("date_joined")
        )

        queryset = queryset.annotate(
            users_total=Count("users", distinct=True),
            users_active=Count(
                "users",
                filter=Q(users__is_active=True),
                distinct=True,
            ),
            users_staff=Count(
                "users",
                filter=Q(users__is_staff=True),
                distinct=True,
            ),
            notification_sms_total=Count(
                "notification_logs",
                filter=Q(
                    notification_logs__channel="sms",
                    notification_logs__status__in=self.NOTIFICATION_SUCCESS_STATUSES,
                ),
                distinct=True,
            ),
            notification_whatsapp_total=Count(
                "notification_logs",
                filter=Q(
                    notification_logs__channel="whatsapp",
                    notification_logs__status__in=self.NOTIFICATION_SUCCESS_STATUSES,
                ),
                distinct=True,
            ),
            notification_sms_30d=Count(
                "notification_logs",
                filter=Q(
                    notification_logs__channel="sms",
                    notification_logs__status__in=self.NOTIFICATION_SUCCESS_STATUSES,
                    notification_logs__created_at__gte=thirty_days_ago,
                ),
                distinct=True,
            ),
            notification_whatsapp_30d=Count(
                "notification_logs",
                filter=Q(
                    notification_logs__channel="whatsapp",
                    notification_logs__status__in=self.NOTIFICATION_SUCCESS_STATUSES,
                    notification_logs__created_at__gte=thirty_days_ago,
                ),
                distinct=True,
            ),
            tenant_last_login=Max("users__last_login"),
            owner_id=Subquery(owner_subquery.values("id")[:1]),
            owner_username=Subquery(owner_subquery.values("username")[:1]),
            owner_email=Subquery(owner_subquery.values("email")[:1]),
            owner_last_login=Subquery(owner_subquery.values("last_login")[:1]),
            owner_date_joined=Subquery(owner_subquery.values("date_joined")[:1]),
            owner_trial_until=Subquery(
                UserFeatureFlags.objects.filter(
                    user__tenant=OuterRef("pk")
                )
                .order_by("user__date_joined")
                .values("trial_until")[:1]
            ),
            owner_trial_status=Subquery(
                UserFeatureFlags.objects.filter(user__tenant=OuterRef("pk"))
                .order_by("user__date_joined")
                .values("pro_status")[:1]
            ),
        )

        return queryset

    def get_permissions(self):
        if getattr(self, "action", None) in {
            "update_plan",
            "block_tenant",
            "unblock_tenant",
            "reset_owner",
        }:
            return [IsOpsAdmin()]
        return [permission() for permission in self.permission_classes]

    def list(self, request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        params = self.request.query_params

        plan = params.get("plan_tier")
        if plan:
            queryset = queryset.filter(plan_tier=plan)

        is_active = params.get("is_active")
        if is_active is not None:
            if is_active.lower() in {"true", "1", "yes"}:
                queryset = queryset.filter(is_active=True)
            elif is_active.lower() in {"false", "0", "no"}:
                queryset = queryset.filter(is_active=False)

        search = params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(slug__icontains=search)
            )

        module = params.get("module")
        if module:
            module = module.lower()
            if module == "reports":
                queryset = queryset.filter(reports_enabled=True)
            elif module == "sms":
                queryset = queryset.filter(sms_enabled=True)
            elif module == "whatsapp":
                queryset = queryset.filter(whatsapp_enabled=True)

        created_from = params.get("created_from")
        if created_from:
            parsed = parse_date(created_from)
            if parsed:
                queryset = queryset.filter(created_at__date__gte=parsed)

        created_to = params.get("created_to")
        if created_to:
            parsed = parse_date(created_to)
            if parsed:
                queryset = queryset.filter(created_at__date__lte=parsed)

        ordering = params.get("ordering")
        allowed = {
            "name",
            "plan_tier",
            "created_at",
            "updated_at",
            "users_total",
            "users_active",
            "notification_sms_total",
            "notification_whatsapp_total",
            "tenant_last_login",
        }
        if ordering:
            field = ordering
            descending = field.startswith("-")
            base_field = field[1:] if descending else field
            if base_field in allowed:
                queryset = queryset.order_by(field)
        else:
            queryset = queryset.order_by("-created_at")

        return queryset

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request, *args: Any, **kwargs: Any) -> HttpResponse:
        queryset = self.filter_queryset(self.get_queryset()).order_by("name")
        serializer = self.get_serializer(queryset, many=True)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f"attachment; filename={self.EXPORT_FILENAME}"

        writer = csv.writer(response)
        writer.writerow(
            [
                "tenant_id",
                "name",
                "slug",
                "plan_tier",
                "is_active",
                "users_total",
                "users_active",
                "sms_total",
                "whatsapp_total",
                "last_login",
                "trial_until",
                "created_at",
            ]
        )

        for item in serializer.data:
            history = item.get("history", {})
            writer.writerow(
                [
                    item.get("id"),
                    item.get("name"),
                    item.get("slug"),
                    item.get("plan_tier"),
                    item.get("is_active"),
                    item.get("user_counts", {}).get("total"),
                    item.get("user_counts", {}).get("active"),
                    item.get("notification_consumption", {}).get("sms_total"),
                    item.get("notification_consumption", {}).get("whatsapp_total"),
                    history.get("last_login"),
                    history.get("trial_until"),
                    item.get("created_at"),
                ]
            )

        return response

    @action(detail=True, methods=["patch"], url_path="plan")
    def update_plan(self, request, *args: Any, **kwargs: Any) -> Response:
        tenant = self.get_object()
        serializer = OpsTenantPlanUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan_tier = serializer.validated_data["plan_tier"]
        force = serializer.validated_data.get("force", False)

        if plan_tier == tenant.plan_tier:
            return Response(self.get_serializer(tenant).data)

        conflicts = self._validate_plan_change(tenant, plan_tier)
        if conflicts and not force:
            raise BusinessError(
                "Downgrade requer confirmação de force.",
                code=ErrorCodes.BUSINESS_PLAN_LIMIT_EXCEEDED,
                details={"conflicts": conflicts},
            )

        self._apply_plan_change(tenant, plan_tier)
        tenant.refresh_from_db()
        data = self.get_serializer(tenant).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="block")
    def block_tenant(self, request, *args: Any, **kwargs: Any) -> Response:
        tenant = self.get_object()
        if not tenant.is_active:
            return Response(self.get_serializer(tenant).data)

        tenant.is_active = False
        tenant.save(update_fields=["is_active", "updated_at"])
        tenant.refresh_from_db()
        return Response(self.get_serializer(tenant).data)

    @action(detail=True, methods=["post"], url_path="unblock")
    def unblock_tenant(self, request, *args: Any, **kwargs: Any) -> Response:
        tenant = self.get_object()
        if tenant.is_active:
            return Response(self.get_serializer(tenant).data)

        tenant.is_active = True
        tenant.save(update_fields=["is_active", "updated_at"])
        tenant.refresh_from_db()
        return Response(self.get_serializer(tenant).data)

    @action(detail=True, methods=["post"], url_path="reset-owner")
    def reset_owner(self, request, *args: Any, **kwargs: Any) -> Response:
        tenant = self.get_object()
        serializer = OpsTenantResetOwnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            owner_data = self._reset_owner_credentials(tenant, serializer.validated_data)
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

    def _reset_owner_credentials(self, tenant: Tenant, data: dict[str, Any]) -> dict[str, Any]:
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
            while CustomUser.objects.exclude(id=owner.id).filter(username=candidate).exists():
                idx += 1
                candidate = f"{base_username}{idx}"
            username = candidate

        owner.username = username
        owner.email = email
        owner.tenant = tenant
        owner.is_active = True
        if display_name:
            owner.salon_name = display_name
        elif not owner.salon_name:
            owner.salon_name = tenant.name

        temporary_password = secrets.token_urlsafe(8)
        owner.set_password(temporary_password)
        owner.save()

        return {
            "owner_id": owner.id,
            "email": owner.email,
            "username": owner.username,
            "temporary_password": temporary_password,
        }


class OpsMetricsOverviewView(APIView):
    permission_classes = [IsOpsSupportOrAdmin]

    def get(self, request, *args: Any, **kwargs: Any) -> Response:
        now = timezone.now()

        active_tenants = Tenant.objects.filter(is_active=True)
        plan_counts = active_tenants.values("plan_tier").annotate(total=Count("id"))

        breakdown: Dict[str, Dict[str, Any]] = {}
        mrr_total = Decimal("0.00")
        for item in plan_counts:
            plan = item["plan_tier"]
            count = item["total"]
            unit_price = PLAN_PRICING_EUR.get(plan, Decimal("0.00"))
            value = unit_price * count
            breakdown[plan] = {
                "count": count,
                "unit_price": f"{unit_price:.2f}",
                "value": f"{value:.2f}",
            }
            mrr_total += value

        trial_cutoff = now + timedelta(days=7)
        trials_expiring = (
            UserFeatureFlags.objects.filter(
                trial_until__isnull=False,
                trial_until__lte=trial_cutoff,
                user__tenant__is_active=True,
            )
            .distinct()
            .count()
        )

        alerts_open = OpsAlert.objects.filter(resolved_at__isnull=True).count()

        since = now - timedelta(days=6)
        logs = (
            NotificationLog.objects.filter(
                created_at__date__gte=since.date(),
                status__in=["sent", "delivered"],
            )
            .annotate(day=TruncDate("created_at"))
            .values("day", "channel")
            .annotate(total=Count("id"))
        )

        daily_map: Dict[Any, Dict[str, int]] = {}
        for entry in logs:
            day = entry["day"].date() if hasattr(entry["day"], "date") else entry["day"]
            channel = entry["channel"]
            total = entry["total"]
            daily_map.setdefault(day, {})[channel] = total

        notification_daily = []
        for offset in range(7):
            day = (since + timedelta(days=offset)).date()
            channels = daily_map.get(day, {})
            total = sum(channels.values())
            notification_daily.append(
                {
                    "date": day.isoformat(),
                    "total": total,
                    "channels": channels,
                }
            )

        data = {
            "generated_at": now.isoformat(),
            "totals": {
                "active_tenants": active_tenants.count(),
                "trials_expiring_7d": trials_expiring,
                "alerts_open": alerts_open,
            },
            "mrr_estimated": {
                "currency": "EUR",
                "total": f"{mrr_total:.2f}",
                "breakdown": breakdown,
            },
            "notification_daily": notification_daily,
        }
        return Response(data, status=status.HTTP_200_OK)


class OpsAlertViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = OpsAlertSerializer
    permission_classes = [IsOpsSupportOrAdmin]

    def get_queryset(self):
        return OpsAlert.objects.select_related("tenant", "resolved_by", "notification_log")

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        resolved = self.request.query_params.get("resolved")
        if resolved is None:
            queryset = queryset.filter(resolved_at__isnull=True)
        else:
            value = resolved.lower()
            if value in {"true", "1", "yes"}:
                queryset = queryset.filter(resolved_at__isnull=False)
            elif value in {"false", "0", "no"}:
                queryset = queryset.filter(resolved_at__isnull=True)
        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category=category)
        severity = self.request.query_params.get("severity")
        if severity:
            queryset = queryset.filter(severity=severity)
        return queryset

    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve(self, request, *args: Any, **kwargs: Any) -> Response:
        alert = self.get_object()
        if not alert.is_resolved:
            alert.mark_resolved(request.user if request.user.is_authenticated else None)
            OpsSupportAuditLog.objects.create(
                actor=request.user if request.user.is_authenticated else None,
                action=OpsSupportAuditLog.Actions.RESOLVE_ALERT,
                target_tenant=alert.tenant,
                payload={"alert_id": alert.id},
                result={"resolved_at": alert.resolved_at.isoformat()},
            )
        serializer = self.get_serializer(alert)
        return Response({"alert": serializer.data, "meta": self._meta(request)})

    def _meta(self, request) -> Dict[str, Any]:
        return {
            "request_id": getattr(request, "request_id", None),
            "error_id": None,
        }


class OpsSupportResendNotificationView(APIView):
    permission_classes = [IsOpsSupportOrAdmin]

    def post(self, request, *args: Any, **kwargs: Any) -> Response:
        serializer = OpsResendNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log_id = serializer.validated_data["notification_log_id"]

        try:
            log = NotificationLog.objects.select_related("tenant", "user").get(id=log_id)
        except NotificationLog.DoesNotExist:
            raise BusinessError(
                "Notificação não encontrada.",
                code=ErrorCodes.RESOURCE_NOT_FOUND,
            )

        if log.status not in {"failed", "pending"}:
            raise BusinessError(
                "Somente notificações falhadas podem ser reenviadas.",
                code=ErrorCodes.RESOURCE_MODIFICATION_DENIED,
            )

        metadata = log.metadata or {}
        metadata["ops_resends"] = metadata.get("ops_resends", 0) + 1

        service = NotificationService()
        results = service.send_notification(
            tenant=log.tenant,
            user=log.user,
            channels=[log.channel],
            notification_type=log.notification_type,
            title=log.title,
            message=log.message,
            metadata={**metadata, "ops_resend_origin": log.id},
        )

        success = results.get(log.channel, False)
        result_label = "success" if success else "failure"
        OPS_NOTIFICATIONS_RESEND_TOTAL.labels(channel=log.channel, result=result_label).inc()

        if success:
            metadata["ops_last_resend_at"] = timezone.now().isoformat()
            metadata["ops_last_resend_by"] = getattr(request.user, "email", None)
            log.status = "sent"
            log.error_message = None
            log.metadata = metadata
            log.save(update_fields=["status", "error_message", "metadata"])
        else:
            metadata["ops_last_resend_error"] = "Driver retornou falso"
            log.metadata = metadata
            log.save(update_fields=["metadata"])

        OpsSupportAuditLog.objects.create(
            actor=request.user if request.user.is_authenticated else None,
            action=OpsSupportAuditLog.Actions.RESEND_NOTIFICATION,
            target_user=log.user,
            target_tenant=log.tenant,
            payload={"notification_log_id": log.id},
            result={"status": "sent" if success else "failed"},
        )

        response_status = status.HTTP_200_OK if success else status.HTTP_202_ACCEPTED
        return Response(
            {
                "status": "sent" if success else "failed",
                "channel": log.channel,
                "notification_log_id": log.id,
                "meta": self._meta(request),
            },
            status=response_status,
        )

    def _meta(self, request) -> Dict[str, Any]:
        return {
            "request_id": getattr(request, "request_id", None),
            "error_id": None,
        }


class OpsSupportClearLockoutView(APIView):
    permission_classes = [IsOpsAdmin]

    def post(self, request, *args: Any, **kwargs: Any) -> Response:
        serializer = OpsClearLockoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lockout_id = serializer.validated_data["lockout_id"]
        note = serializer.validated_data.get("note")

        try:
            lockout = AccountLockout.objects.select_related("user", "tenant").get(id=lockout_id)
        except AccountLockout.DoesNotExist:
            raise BusinessError(
                "Lockout não encontrado.",
                code=ErrorCodes.RESOURCE_NOT_FOUND,
            )

        metadata = lockout.metadata or {}
        if note:
            notes = metadata.get("notes", [])
            notes.append(
                {
                    "note": note,
                    "author": getattr(request.user, "email", None),
                    "timestamp": timezone.now().isoformat(),
                }
            )
            metadata["notes"] = notes
            lockout.metadata = metadata
            lockout.save(update_fields=["metadata"])

        if lockout.is_active:
            lockout.resolve(request.user if request.user.is_authenticated else None)
            if not lockout.user.is_active:
                lockout.user.is_active = True
                lockout.user.save(update_fields=["is_active"])
            OPS_LOCKOUTS_CLEARED_TOTAL.labels(result="success").inc()
        else:
            OPS_LOCKOUTS_CLEARED_TOTAL.labels(result="noop").inc()

        OpsSupportAuditLog.objects.create(
            actor=request.user if request.user.is_authenticated else None,
            action=OpsSupportAuditLog.Actions.CLEAR_LOCKOUT,
            target_user=lockout.user,
            target_tenant=lockout.tenant,
            payload={"lockout_id": lockout.id, "note": note},
            result={"resolved_at": lockout.resolved_at.isoformat() if lockout.resolved_at else None},
        )

        return Response(
            {
                "lockout_id": lockout.id,
                "resolved_at": lockout.resolved_at.isoformat() if lockout.resolved_at else None,
                "meta": self._meta(request),
            },
            status=status.HTTP_200_OK,
        )

    def _meta(self, request) -> Dict[str, Any]:
        return {
            "request_id": getattr(request, "request_id", None),
            "error_id": None,
        }
