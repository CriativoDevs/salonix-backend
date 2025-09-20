"""Middleware personalizado para o Salonix Backend."""

import logging
import time
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.deprecation import MiddlewareMixin
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
)
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from .logging_utils import get_request_id, setup_logging_context
from users.models import CustomUser
from salonix_backend.error_handling import ErrorCodes, log_error

logger = logging.getLogger(__name__)

OPS_SCOPES = {
    CustomUser.OpsRoles.OPS_ADMIN,
    CustomUser.OpsRoles.OPS_SUPPORT,
}


class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Middleware para logging de requests com contexto estruturado.

    Funcionalidades:
    - Adiciona X-Request-ID único para cada request
    - Configura contexto de logging para toda a request
    - Loga início e fim de cada request
    - Calcula tempo de resposta
    - Adiciona headers de correlação
    """

    def process_request(self, request: HttpRequest) -> None:
        """Processar request antes da view."""
        # Gerar ou usar X-Request-ID existente
        request_id = request.headers.get("X-Request-ID") or get_request_id()
        request.request_id = request_id

        # Configurar contexto de logging
        setup_logging_context(request)

        # Marcar início do request
        request.start_time = time.time()

        # Log do início do request
        logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "endpoint": request.path,
                "user_agent": request.headers.get("User-Agent", ""),
                "remote_addr": self._get_client_ip(request),
                "content_type": request.content_type,
            },
        )

    def process_response(
        self, request: HttpRequest, response: HttpResponse
    ) -> HttpResponse:
        """Processar response após a view."""
        # Calcular duração
        duration_ms = None
        if hasattr(request, "start_time"):
            duration_ms = round((time.time() - request.start_time) * 1000, 2)

        # Adicionar headers de correlação
        if hasattr(request, "request_id"):
            response["X-Request-ID"] = request.request_id

        # Log do fim do request
        logger.info(
            "Request completed",
            extra={
                "request_id": getattr(request, "request_id", "unknown"),
                "method": request.method,
                "endpoint": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "user_id": (
                    str(request.user.id)
                    if hasattr(request, "user") and request.user.is_authenticated
                    else None
                ),
                "tenant_id": (
                    request.user.tenant.slug
                    if hasattr(request, "user")
                    and request.user.is_authenticated
                    and hasattr(request.user, "tenant")
                    and request.user.tenant
                    else None
                ),
            },
        )

        return response

    def process_exception(self, request: HttpRequest, exception: Exception) -> None:
        """Processar exceções."""
        # Calcular duração até a exceção
        duration_ms = None
        if hasattr(request, "start_time"):
            duration_ms = round((time.time() - request.start_time) * 1000, 2)

        # Log da exceção
        logger.error(
            f"Request failed with exception: {exception}",
            extra={
                "request_id": getattr(request, "request_id", "unknown"),
                "method": request.method,
                "endpoint": request.path,
                "duration_ms": duration_ms,
                "exception_type": type(exception).__name__,
                "user_id": (
                    str(request.user.id)
                    if hasattr(request, "user") and request.user.is_authenticated
                    else None
                ),
                "tenant_id": (
                    request.user.tenant.slug
                    if hasattr(request, "user")
                    and request.user.is_authenticated
                    and hasattr(request.user, "tenant")
                    and request.user.tenant
                    else None
                ),
            },
            exc_info=True,
        )

    def _get_client_ip(self, request: HttpRequest) -> str:
        """Obter IP do cliente considerando proxies."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR", "unknown")
        return ip


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Middleware para adicionar headers de segurança.
    """

    def process_response(
        self, request: HttpRequest, response: HttpResponse
    ) -> HttpResponse:
        """Adicionar headers de segurança."""
        # Headers de segurança básicos
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["X-XSS-Protection"] = "1; mode=block"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy básico (ajuste conforme necessário)
        if not response.get("Content-Security-Policy"):
            response["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self';"
            )

        return response


class ScopeAccessMiddleware(MiddlewareMixin):
    """
    Middleware que garante isolamento entre escopos Tenant e Ops.

    - Tokens do console Ops (`ops_admin`, `ops_support`) só podem acessar rotas `/api/ops/`
    - Tokens de tenant não podem acessar rotas `/api/ops/`
    """

    OPS_PREFIX = "/api/ops/"

    def __init__(self, get_response):
        super().__init__(get_response)
        self.authenticator = JWTAuthentication()

    def process_request(self, request: HttpRequest):
        request.auth_scope = None
        return None

    def process_view(self, request: HttpRequest, view_func, view_args, view_kwargs):
        path = request.path or ""

        if not path.startswith("/api/"):
            return None

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer"):
            return None

        try:
            auth_result = self.authenticator.authenticate(request)
        except InvalidToken as exc:
            return self._build_error_response(
                request,
                message="Token inválido.",
                status_code=401,
                error_code=ErrorCodes.AUTH_INVALID_TOKEN,
                exception=AuthenticationFailed("Token inválido."),
            )

        if auth_result is None:
            return None

        user, token = auth_result
        request.user = user
        request.auth = token
        scope = token.get("scope") or "tenant"
        request.auth_scope = scope

        if path.startswith(self.OPS_PREFIX):
            if not user.is_authenticated:
                return self._build_error_response(
                    request,
                    message="Autenticação necessária.",
                    status_code=401,
                    error_code=ErrorCodes.AUTH_REQUIRED,
                    exception=NotAuthenticated("Autenticação necessária."),
                )
            if user.is_superuser:
                return None
            if scope not in OPS_SCOPES:
                return self._build_error_response(
                    request,
                    message="Acesso restrito ao console Ops.",
                    status_code=403,
                    error_code=ErrorCodes.AUTH_INSUFFICIENT_PERMISSIONS,
                    exception=PermissionDenied("Acesso restrito ao console Ops."),
                )
        else:
            if scope in OPS_SCOPES and not user.is_superuser:
                return self._build_error_response(
                    request,
                    message="Contas staff não podem acessar rotas do painel do tenant.",
                    status_code=403,
                    error_code=ErrorCodes.AUTH_INSUFFICIENT_PERMISSIONS,
                    exception=PermissionDenied(
                        "Contas staff não podem acessar rotas do painel do tenant."
                    ),
                )

        return None

    def _build_error_response(
        self,
        request: HttpRequest,
        *,
        message: str,
        status_code: int,
        error_code: str,
        exception: Exception,
    ) -> JsonResponse:
        error_id = log_error(
            exception,
            request=request,
            user=getattr(request, "user", None),
            tenant=getattr(request, "tenant", None),
        )
        payload = {
            "error": {
                "code": error_code,
                "message": message,
                "details": {},
                "error_id": error_id,
            }
        }
        return JsonResponse(payload, status=status_code)
