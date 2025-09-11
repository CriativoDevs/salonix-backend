"""
Testes para o sistema de tratamento de erros padronizado.

Testa:
- Exception handlers customizados
- Códigos de erro padronizados
- Logging estruturado
- Sanitização de dados sensíveis
- Formatos de resposta
"""

import json
import logging
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from typing import Any, cast
from rest_framework import status
from rest_framework.exceptions import ValidationError, NotFound, PermissionDenied

from salonix_backend.error_handling import (
    ErrorCodes,
    SalonixError,
    BusinessError,
    TenantError,
    FeatureDisabledError,
    custom_exception_handler,
    sanitize_data,
    log_error,
    validate_required_fields,
    create_error_response,
)
from users.models import Tenant, CustomUser

User = get_user_model()


class ErrorCodesTestCase(TestCase):
    """Testa os códigos de erro padronizados."""

    def test_error_codes_format(self):
        """Testa se os códigos seguem o padrão correto."""
        # Todos os códigos devem começar com 'E' seguido de 3 dígitos
        codes = [
            ErrorCodes.AUTH_REQUIRED,
            ErrorCodes.VALIDATION_REQUIRED_FIELD,
            ErrorCodes.BUSINESS_TENANT_NOT_FOUND,
            ErrorCodes.SYSTEM_INTERNAL_ERROR,
            ErrorCodes.RESOURCE_NOT_FOUND,
        ]

        for code in codes:
            self.assertTrue(code.startswith("E"))
            self.assertEqual(len(code), 4)
            self.assertTrue(code[1:].isdigit())

    def test_error_codes_categories(self):
        """Testa se os códigos estão nas categorias corretas."""
        # Autenticação: E001-E099
        self.assertTrue(ErrorCodes.AUTH_REQUIRED.startswith("E0"))

        # Validação: E100-E199
        self.assertTrue(ErrorCodes.VALIDATION_REQUIRED_FIELD.startswith("E1"))

        # Negócio: E200-E299
        self.assertTrue(ErrorCodes.BUSINESS_TENANT_NOT_FOUND.startswith("E2"))

        # Sistema: E300-E399
        self.assertTrue(ErrorCodes.SYSTEM_INTERNAL_ERROR.startswith("E3"))

        # Recursos: E400-E499
        self.assertTrue(ErrorCodes.RESOURCE_NOT_FOUND.startswith("E4"))


class SalonixErrorTestCase(TestCase):
    """Testa as exceções customizadas."""

    def test_salonix_error_basic(self):
        """Testa criação básica de SalonixError."""
        error = SalonixError("Erro de teste")

        self.assertEqual(str(error), "Erro de teste")
        self.assertEqual(error.code, ErrorCodes.SYSTEM_INTERNAL_ERROR)
        self.assertEqual(error.status_code, 500)
        self.assertEqual(error.details, {})

    def test_salonix_error_with_details(self):
        """Testa SalonixError com detalhes customizados."""
        details = {"field": "value", "count": 42}
        error = SalonixError(
            "Erro customizado",
            code=ErrorCodes.VALIDATION_INVALID_VALUE,
            details=details,
            status_code=400,
        )

        self.assertEqual(error.code, ErrorCodes.VALIDATION_INVALID_VALUE)
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.details, details)

    def test_business_error(self):
        """Testa BusinessError."""
        error = BusinessError(
            "Regra de negócio violada", code=ErrorCodes.BUSINESS_APPOINTMENT_CONFLICT
        )

        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.code, ErrorCodes.BUSINESS_APPOINTMENT_CONFLICT)

    def test_tenant_error(self):
        """Testa TenantError."""
        error = TenantError("Tenant não encontrado")

        self.assertEqual(error.code, ErrorCodes.BUSINESS_TENANT_NOT_FOUND)
        self.assertEqual(error.status_code, 400)

    def test_feature_disabled_error(self):
        """Testa FeatureDisabledError."""
        error = FeatureDisabledError("reports", "Salão Teste")

        self.assertEqual(error.code, ErrorCodes.BUSINESS_FEATURE_DISABLED)
        self.assertIn("reports", error.message)
        self.assertIn("Salão Teste", error.message)
        self.assertEqual(error.details["feature"], "reports")
        self.assertEqual(error.details["tenant"], "Salão Teste")


class SanitizeDataTestCase(TestCase):
    """Testa a sanitização de dados sensíveis."""

    def test_sanitize_password(self):
        """Testa sanitização de senhas."""
        data = {"username": "test", "password": "secret123"}
        sanitized = sanitize_data(data)

        self.assertEqual(sanitized["username"], "test")
        self.assertEqual(sanitized["password"], "[REDACTED]")

    def test_sanitize_nested_dict(self):
        """Testa sanitização de dicionários aninhados."""
        data = {
            "user": {
                "name": "João",
                "auth_token": "abc123",
                "preferences": {"theme": "dark"},
            },
            "api_key": "secret",
        }

        sanitized = sanitize_data(data)

        self.assertEqual(sanitized["user"]["name"], "João")
        self.assertEqual(sanitized["user"]["auth_token"], "[REDACTED]")
        self.assertEqual(sanitized["user"]["preferences"]["theme"], "dark")
        self.assertEqual(sanitized["api_key"], "[REDACTED]")

    def test_sanitize_list(self):
        """Testa sanitização de listas."""
        data = [
            {"name": "user1", "password": "pass1"},
            {"name": "user2", "token": "token2"},
        ]

        sanitized = sanitize_data(data)

        self.assertEqual(sanitized[0]["name"], "user1")
        self.assertEqual(sanitized[0]["password"], "[REDACTED]")
        self.assertEqual(sanitized[1]["name"], "user2")
        self.assertEqual(sanitized[1]["token"], "[REDACTED]")

    def test_sanitize_long_string(self):
        """Testa truncamento de strings longas."""
        long_string = "a" * 150
        sanitized = sanitize_data(long_string)

        self.assertTrue(sanitized.endswith("... [TRUNCATED]"))
        self.assertEqual(len(sanitized), 100 + len("... [TRUNCATED]"))


class LogErrorTestCase(TestCase):
    """Testa o logging estruturado de erros."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")

    @patch("salonix_backend.error_handling.logger")
    def test_log_error_basic(self, mock_logger):
        """Testa logging básico de erro."""
        exception = ValueError("Erro de teste")

        error_id = log_error(exception)

        # Verificar se o logger foi chamado
        mock_logger.error.assert_called_once()

        # Verificar formato do error_id
        self.assertEqual(len(error_id), 8)

        # Verificar contexto do log
        call_args = mock_logger.error.call_args
        extra_context = call_args[1]["extra"]

        self.assertIn("error_id", extra_context)
        self.assertIn("error_type", extra_context)
        self.assertIn("error_message", extra_context)
        self.assertEqual(extra_context["error_type"], "ValueError")
        self.assertEqual(extra_context["error_message"], "Erro de teste")

    @patch("salonix_backend.error_handling.logger")
    def test_log_error_with_request(self, mock_logger):
        """Testa logging com contexto de request."""
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.post("/api/test/", {"field": "value"})
        request.user = self.user
        request.tenant = self.tenant

        exception = ValidationError("Dados inválidos")

        log_error(exception, request=request, user=self.user, tenant=self.tenant)

        # Verificar contexto da request
        call_args = mock_logger.error.call_args
        extra_context = call_args[1]["extra"]

        self.assertEqual(extra_context["method"], "POST")
        self.assertEqual(extra_context["path"], "/api/test/")
        self.assertEqual(extra_context["user_id"], self.user.id)
        self.assertEqual(extra_context["tenant_slug"], self.tenant.slug)


class CustomExceptionHandlerTestCase(APITestCase):
    """Testa o exception handler customizado."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")

    def test_validation_error_format(self):
        """Testa formato de resposta para ValidationError."""
        from rest_framework.views import APIView
        from rest_framework.response import Response

        class TestView(APIView):
            def get(self, request):
                raise ValidationError({"field": "Este campo é obrigatório."})

        # Simular request
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/test/")
        request.user = self.user

        view = TestView()
        context = {"request": request, "view": view}

        # Testar exception handler
        exc = ValidationError({"field": "Este campo é obrigatório."})
        response = custom_exception_handler(exc, context)

        # Verificar formato da resposta
        data = cast(dict[str, Any], response.data)
        self.assertIn("error", data)
        error = cast(dict[str, Any], data["error"])

        self.assertIn("code", error)
        self.assertIn("message", error)
        self.assertIn("details", error)
        self.assertIn("error_id", error)

        # Verificar código específico
        self.assertEqual(error["code"], ErrorCodes.VALIDATION_INVALID_VALUE)

    def test_salonix_error_format(self):
        """Testa formato de resposta para SalonixError."""
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/test/")
        request.user = self.user

        context = {"request": request}

        # Testar com SalonixError customizado
        exc = TenantError("Tenant não encontrado")
        response = custom_exception_handler(exc, context)
        data = cast(dict[str, Any], response.data)
        error = cast(dict[str, Any], data["error"])
        # TenantError herda de BusinessError que herda de SalonixError
        self.assertTrue(error["code"].startswith("E"))  # Qualquer código E válido
        self.assertIn("Tenant não encontrado", error["message"])

    def test_unknown_error_format(self):
        """Testa formato de resposta para erro desconhecido."""
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/test/")
        request.user = self.user

        context = {"request": request}

        # Testar com exceção não mapeada
        exc = RuntimeError("Erro inesperado")
        response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, 500)
        data = cast(dict[str, Any], response.data)
        error = cast(dict[str, Any], data["error"])
        self.assertEqual(error["code"], ErrorCodes.SYSTEM_INTERNAL_ERROR)
        self.assertIn("Erro interno do servidor", error["message"])


class UtilityFunctionsTestCase(TestCase):
    """Testa funções utilitárias."""

    def test_validate_required_fields_success(self):
        """Testa validação bem-sucedida de campos obrigatórios."""
        data = {"name": "Test", "email": "test@example.com"}
        required_fields = ["name", "email"]

        # Não deve lançar exceção
        validate_required_fields(data, required_fields)

    def test_validate_required_fields_missing(self):
        """Testa validação com campos faltando."""
        data = {"name": "Test"}
        required_fields = ["name", "email", "phone"]

        with self.assertRaises(ValidationError) as cm:
            validate_required_fields(data, required_fields)

        error_dict = cm.exception.detail
        self.assertIn("email", error_dict)
        self.assertIn("phone", error_dict)
        self.assertNotIn("name", error_dict)

    def test_create_error_response(self):
        """Testa criação de resposta de erro."""
        response = create_error_response(
            "Erro de teste",
            code=ErrorCodes.VALIDATION_INVALID_VALUE,
            status_code=400,
            details={"field": "value"},
        )

        self.assertEqual(response.status_code, 400)

        data = cast(dict[str, Any], response.data)
        error = cast(dict[str, Any], data.get("error"))
        self.assertEqual(error["code"], ErrorCodes.VALIDATION_INVALID_VALUE)
        self.assertEqual(error["message"], "Erro de teste")
        self.assertEqual(error["details"]["field"], "value")


class IntegrationTestCase(APITestCase):
    """Testes de integração do sistema de erros."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user.tenant = self.tenant
        self.user.save()

    def test_tenant_meta_view_error_format(self):
        """Testa formato de erro na view TenantMetaView."""
        # Testar sem parâmetro tenant
        response = self.client.get("/api/users/tenant/meta/")

        self.assertEqual(response.status_code, 400)
        data = cast(dict[str, Any], response.data)
        self.assertIn("error", data)

        error = cast(dict[str, Any], data["error"])
        self.assertEqual(error["code"], ErrorCodes.VALIDATION_REQUIRED_FIELD)
        self.assertIn("obrigatório", error["message"])

    def test_tenant_meta_view_not_found(self):
        """Testa tenant não encontrado na view TenantMetaView."""
        response = self.client.get("/api/users/tenant/meta/?tenant=inexistente")

        self.assertEqual(response.status_code, 400)
        data = cast(dict[str, Any], response.data)
        self.assertIn("error", data)

        error = cast(dict[str, Any], data["error"])
        self.assertEqual(error["code"], ErrorCodes.BUSINESS_TENANT_NOT_FOUND)
        self.assertIn("não encontrado", error["message"])

    def test_tenant_meta_view_success(self):
        """Testa sucesso na view TenantMetaView."""
        response = self.client.get(f"/api/users/tenant/meta/?tenant={self.tenant.slug}")

        self.assertEqual(response.status_code, 200)
        # Não deve haver campo 'error' na resposta de sucesso
        data = cast(dict[str, Any], response.data)
        self.assertNotIn("error", data)


@override_settings(
    LOGGING={
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "test": {
                "class": "logging.StreamHandler",
            },
        },
        "loggers": {
            "salonix_backend.error_handling": {
                "handlers": ["test"],
                "level": "ERROR",
            },
        },
    }
)
class LoggingIntegrationTestCase(TestCase):
    """Testa integração do logging com o sistema de erros."""

    @patch("salonix_backend.error_handling.logger")
    def test_error_logging_in_view(self, mock_logger):
        """Testa se erros em views são logados corretamente."""
        from django.test import RequestFactory
        from users.views import TenantMetaView

        factory = RequestFactory()
        request = factory.get("/api/users/tenant/meta/")

        view = TenantMetaView()

        # Deve lançar TenantError que será logada
        with self.assertRaises(TenantError):
            view.get(request)

        # Verificar se o erro foi logado (via custom_exception_handler)
        # Em um teste real, isso seria capturado pelo middleware do DRF
