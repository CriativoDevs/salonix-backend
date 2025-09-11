"""
Sistema de tratamento de erros padronizado para Salonix Backend.

Este módulo fornece:
- Códigos de erro padronizados
- Exception handlers customizados para DRF
- Logging estruturado de erros
- Sanitização de dados sensíveis
- Métricas de erro para monitoramento
"""

import logging
import traceback
from typing import Any, Dict, Optional, Union

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)

# =====================================================
# CÓDIGOS DE ERRO PADRONIZADOS
# =====================================================


class ErrorCodes:
    """Códigos de erro padronizados do sistema."""

    # Erros de Autenticação (E001-E099)
    AUTH_REQUIRED = "E001"
    AUTH_INVALID_TOKEN = "E002"
    AUTH_EXPIRED_TOKEN = "E003"
    AUTH_INSUFFICIENT_PERMISSIONS = "E004"

    # Erros de Validação (E100-E199)
    VALIDATION_REQUIRED_FIELD = "E100"
    VALIDATION_INVALID_FORMAT = "E101"
    VALIDATION_INVALID_VALUE = "E102"
    VALIDATION_DUPLICATE_VALUE = "E103"
    VALIDATION_CONSTRAINT_VIOLATION = "E104"

    # Erros de Negócio (E200-E299)
    BUSINESS_TENANT_NOT_FOUND = "E200"
    BUSINESS_TENANT_INACTIVE = "E201"
    BUSINESS_APPOINTMENT_CONFLICT = "E202"
    BUSINESS_SLOT_UNAVAILABLE = "E203"
    BUSINESS_FEATURE_DISABLED = "E204"
    BUSINESS_PLAN_LIMIT_EXCEEDED = "E205"

    # Erros de Sistema (E300-E399)
    SYSTEM_INTERNAL_ERROR = "E300"
    SYSTEM_DATABASE_ERROR = "E301"
    SYSTEM_CACHE_ERROR = "E302"
    SYSTEM_EXTERNAL_SERVICE_ERROR = "E303"
    SYSTEM_RATE_LIMIT_EXCEEDED = "E304"

    # Erros de Recursos (E400-E499)
    RESOURCE_NOT_FOUND = "E400"
    RESOURCE_ALREADY_EXISTS = "E401"
    RESOURCE_ACCESS_DENIED = "E402"
    RESOURCE_MODIFICATION_DENIED = "E403"


# =====================================================
# EXCEÇÕES CUSTOMIZADAS
# =====================================================


class SalonixError(APIException):
    """Exceção base para erros específicos do Salonix."""

    def __init__(
        self,
        message: str,
        code: str = ErrorCodes.SYSTEM_INTERNAL_ERROR,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        self.status_code = status_code
        # Para APIException, definir detail e status_code
        self.detail = message
        super().__init__(message)


class BusinessError(SalonixError):
    """Erro de regra de negócio."""

    def __init__(
        self, message: str, code: str, details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            code=code,
            details=details,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class TenantError(BusinessError):
    """Erro relacionado a tenant."""

    def __init__(self, message: str, code: str = ErrorCodes.BUSINESS_TENANT_NOT_FOUND):
        super().__init__(message=message, code=code)


class FeatureDisabledError(BusinessError):
    """Erro quando uma feature está desabilitada para o tenant."""

    def __init__(self, feature: str, tenant_name: str):
        message = (
            f"Feature '{feature}' não está disponível para o tenant '{tenant_name}'"
        )
        super().__init__(
            message=message,
            code=ErrorCodes.BUSINESS_FEATURE_DISABLED,
            details={"feature": feature, "tenant": tenant_name},
        )


# =====================================================
# MAPEAMENTO DE EXCEÇÕES PARA CÓDIGOS
# =====================================================

EXCEPTION_CODE_MAPPING = {
    # DRF Exceptions
    NotAuthenticated: ErrorCodes.AUTH_REQUIRED,
    AuthenticationFailed: ErrorCodes.AUTH_INVALID_TOKEN,
    PermissionDenied: ErrorCodes.AUTH_INSUFFICIENT_PERMISSIONS,
    NotFound: ErrorCodes.RESOURCE_NOT_FOUND,
    ValidationError: ErrorCodes.VALIDATION_INVALID_VALUE,
    Throttled: ErrorCodes.SYSTEM_RATE_LIMIT_EXCEEDED,
    # Django Exceptions
    Http404: ErrorCodes.RESOURCE_NOT_FOUND,
    DjangoValidationError: ErrorCodes.VALIDATION_CONSTRAINT_VIOLATION,
}


# =====================================================
# SANITIZAÇÃO DE DADOS SENSÍVEIS
# =====================================================

SENSITIVE_FIELDS = {
    "password",
    "token",
    "secret",
    "key",
    "auth",
    "authorization",
    "credit_card",
    "card_number",
    "cvv",
    "ssn",
    "cpf",
    "phone",
    "email",
    "api_key",
    "private_key",
    "session_id",
}


def sanitize_data(data: Any) -> Any:
    """Remove dados sensíveis de dicionários, listas e strings."""
    if isinstance(data, dict):
        return {
            key: (
                "[REDACTED]"
                if any(sensitive in key.lower() for sensitive in SENSITIVE_FIELDS)
                else sanitize_data(value)
            )
            for key, value in data.items()
        }
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    elif isinstance(data, str) and len(data) > 100:
        # Truncar strings muito longas
        return data[:100] + "... [TRUNCATED]"
    return data


# =====================================================
# LOGGING ESTRUTURADO DE ERROS
# =====================================================


def log_error(
    exception: Exception,
    request=None,
    user=None,
    tenant=None,
    extra_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Loga erro de forma estruturada e retorna um ID único do erro.

    Returns:
        str: ID único do erro para referência
    """
    import uuid

    error_id = str(uuid.uuid4())[:8]

    # Contexto básico do erro
    error_context = {
        "error_id": error_id,
        "error_type": type(exception).__name__,
        "error_message": str(exception),
        "error_code": getattr(exception, "code", "UNKNOWN"),
    }

    # Adicionar contexto da request se disponível
    if request:
        error_context.update(
            {
                "method": request.method,
                "path": request.path,
                "user_agent": request.META.get("HTTP_USER_AGENT", ""),
                "remote_addr": request.META.get("REMOTE_ADDR", ""),
                "query_params": sanitize_data(dict(request.GET)),
            }
        )

        # Dados do body (sanitizados)
        if hasattr(request, "data"):
            error_context["request_data"] = sanitize_data(request.data)

    # Contexto do usuário
    if user and hasattr(user, "id") and user.id:
        error_context.update(
            {
                "user_id": user.id,
                "username": getattr(user, "username", ""),
                "is_staff": getattr(user, "is_staff", False),
            }
        )

    # Contexto do tenant
    if tenant:
        error_context.update(
            {
                "tenant_id": getattr(tenant, "id", ""),
                "tenant_slug": getattr(tenant, "slug", ""),
                "tenant_plan": getattr(tenant, "plan_tier", ""),
            }
        )

    # Contexto adicional
    if extra_context:
        error_context.update(sanitize_data(extra_context))

    # Stack trace (apenas para erros internos)
    if not isinstance(exception, (ValidationError, NotFound, PermissionDenied)):
        error_context["stack_trace"] = traceback.format_exc()

    # Log do erro
    logger.error(
        f"Error {error_id}: {exception}",
        extra=error_context,
        exc_info=isinstance(exception, Exception)
        and not isinstance(exception, (ValidationError, NotFound, PermissionDenied)),
    )

    return error_id


# =====================================================
# EXCEPTION HANDLER CUSTOMIZADO
# =====================================================


def custom_exception_handler(exc, context):
    """
    Exception handler customizado para padronizar respostas de erro.

    Retorna respostas no formato:
    {
        "error": {
            "code": "E001",
            "message": "Mensagem de erro",
            "details": {...},
            "error_id": "abc12345"
        }
    }
    """
    # Obter response padrão do DRF
    response = exception_handler(exc, context)

    # Extrair contexto da request
    request = context.get("request")
    user = getattr(request, "user", None) if request else None
    tenant = getattr(request, "tenant", None) if request else None

    # Log do erro e obter ID único
    error_id = log_error(
        exception=exc,
        request=request,
        user=user,
        tenant=tenant,
        extra_context={
            "view": (
                getattr(context.get("view"), "__class__", type(None)).__name__
                if context.get("view")
                else ""
            )
        },
    )

    # Se DRF não tratou o erro, tratar como erro interno
    if response is None:
        return Response(
            {
                "error": {
                    "code": ErrorCodes.SYSTEM_INTERNAL_ERROR,
                    "message": "Erro interno do servidor",
                    "details": {"original_error": str(exc)},
                    "error_id": error_id,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Determinar código do erro
    error_code = ErrorCodes.SYSTEM_INTERNAL_ERROR

    # Para exceções customizadas do Salonix
    if isinstance(exc, SalonixError):
        error_code = exc.code
    else:
        # Mapear exceções conhecidas
        error_code = EXCEPTION_CODE_MAPPING.get(
            type(exc), ErrorCodes.SYSTEM_INTERNAL_ERROR
        )

    # Extrair mensagem de erro
    error_message = str(exc)
    error_details = {}

    # Tratamento especial para ValidationError do DRF
    if isinstance(exc, ValidationError):
        if isinstance(exc.detail, dict):
            error_details = exc.detail
            # Criar mensagem mais amigável
            field_errors = []
            for field, errors in exc.detail.items():
                if isinstance(errors, list):
                    field_errors.append(f"{field}: {', '.join(map(str, errors))}")
                else:
                    field_errors.append(f"{field}: {str(errors)}")
            error_message = "Dados inválidos: " + "; ".join(field_errors)
        elif isinstance(exc.detail, list):
            error_message = "; ".join(map(str, exc.detail))

    # Para exceções do Salonix, incluir detalhes
    if isinstance(exc, SalonixError):
        error_details.update(exc.details)

    # Formato padronizado de resposta
    custom_response_data = {
        "error": {
            "code": error_code,
            "message": error_message,
            "details": error_details,
            "error_id": error_id,
        }
    }

    response.data = custom_response_data
    return response


# =====================================================
# DECORATORS PARA TRATAMENTO DE ERROS
# =====================================================


def handle_business_errors(func):
    """Decorator para capturar e converter erros de negócio."""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Se já é um SalonixError, re-raise
            if isinstance(e, SalonixError):
                raise

            # Converter erros comuns em BusinessError
            if "tenant" in str(e).lower() and "not found" in str(e).lower():
                raise TenantError("Tenant não encontrado ou inativo")

            # Re-raise outros erros
            raise

    return wrapper


# =====================================================
# UTILITÁRIOS
# =====================================================


def create_error_response(
    message: str,
    code: str = ErrorCodes.SYSTEM_INTERNAL_ERROR,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    details: Optional[Dict[str, Any]] = None,
) -> Response:
    """Cria uma resposta de erro padronizada."""
    return Response(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "error_id": "manual",
            }
        },
        status=status_code,
    )


def validate_required_fields(data: Dict[str, Any], required_fields: list) -> None:
    """Valida se campos obrigatórios estão presentes."""
    missing_fields = [field for field in required_fields if not data.get(field)]

    if missing_fields:
        raise ValidationError(
            {field: "Este campo é obrigatório." for field in missing_fields}
        )
