from __future__ import annotations

import logging
from typing import Any, Dict

from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from ops.observability import OPS_AUTH_EVENTS_TOTAL
from ops.serializers import OpsTokenObtainPairSerializer, OpsTokenRefreshSerializer

logger = logging.getLogger(__name__)


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
