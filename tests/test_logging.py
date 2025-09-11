"""
Testes para configuração de logging.
"""

import json
import logging
from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.test import TestCase, RequestFactory, override_settings
from django.http import HttpResponse

from salonix_backend.logging_utils import (
    JSONFormatter,
    DevelopmentFormatter,
    RequestContextFilter,
    get_request_id,
    setup_logging_context,
)
from salonix_backend.middleware import RequestLoggingMiddleware
from users.models import CustomUser, Tenant


class TestJSONFormatter(TestCase):
    """Testes para o formatador JSON."""

    def setUp(self):
        self.formatter = JSONFormatter()

    def test_basic_log_formatting(self):
        """Teste formatação básica de log."""
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = self.formatter.format(record)
        log_data = json.loads(formatted)

        assert log_data["level"] == "INFO"
        assert log_data["logger"] == "test.logger"
        assert log_data["message"] == "Test message"
        assert log_data["line"] == 42
        assert "timestamp" in log_data

    def test_log_with_request_context(self):
        """Teste formatação com contexto de request."""
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message with context",
            args=(),
            exc_info=None,
        )

        # Adicionar contexto de request
        record.request_id = "test-request-123"
        record.user_id = "456"
        record.tenant_id = "test-tenant"
        record.endpoint = "/api/test/"
        record.method = "GET"
        record.status_code = 200
        record.duration_ms = 150.5

        formatted = self.formatter.format(record)
        log_data = json.loads(formatted)

        assert log_data["request_id"] == "test-request-123"
        assert log_data["user_id"] == "456"
        assert log_data["tenant_id"] == "test-tenant"
        assert log_data["endpoint"] == "/api/test/"
        assert log_data["method"] == "GET"
        assert log_data["status_code"] == 200
        assert log_data["duration_ms"] == 150.5

    def test_log_with_exception(self):
        """Teste formatação com exceção."""
        import sys

        try:
            raise ValueError("Test exception")
        except ValueError:
            exc_info = sys.exc_info()
            record = logging.LogRecord(
                name="test.logger",
                level=logging.ERROR,
                pathname="test.py",
                lineno=42,
                msg="Error occurred",
                args=(),
                exc_info=exc_info,
            )

        formatted = self.formatter.format(record)
        log_data = json.loads(formatted)

        assert "exception" in log_data
        assert log_data["exception"]["type"] == "ValueError"
        assert log_data["exception"]["message"] == "Test exception"
        assert "traceback" in log_data["exception"]


class TestDevelopmentFormatter(TestCase):
    """Testes para o formatador de desenvolvimento."""

    def setUp(self):
        self.formatter = DevelopmentFormatter()

    def test_basic_formatting(self):
        """Teste formatação básica para desenvolvimento."""
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = self.formatter.format(record)

        assert "INFO" in formatted
        assert "test.logger" in formatted
        assert "Test message" in formatted
        assert "(test:42)" in formatted

    def test_formatting_with_context(self):
        """Teste formatação com contexto de request."""
        record = logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="test.py",
            lineno=42,
            msg="Warning message",
            args=(),
            exc_info=None,
        )

        record.request_id = "test-123"
        record.user_id = "456"
        record.endpoint = "/api/test/"

        formatted = self.formatter.format(record)

        assert "WARNING" in formatted
        assert "req_id=test-123" in formatted
        assert "user=456" in formatted
        assert "endpoint=/api/test/" in formatted


class TestRequestContextFilter(TestCase):
    """Testes para o filtro de contexto de request."""

    def setUp(self):
        self.filter = RequestContextFilter()

    def test_filter_without_request(self):
        """Teste filtro sem request no contexto."""
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Deve sempre retornar True, mesmo sem contexto
        result = self.filter.filter(record)
        assert result is True


@pytest.mark.django_db
class TestRequestLoggingMiddleware:
    """Testes para o middleware de logging."""

    def setup_method(self):
        self.factory = RequestFactory()
        # Criar middleware com get_response mock
        get_response = Mock()
        self.middleware = RequestLoggingMiddleware(get_response)

        # Criar tenant e usuário para testes
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = CustomUser.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )

    def test_process_request_adds_request_id(self):
        """Teste se o middleware adiciona request_id."""
        request = self.factory.get("/api/test/")

        self.middleware.process_request(request)

        assert hasattr(request, "request_id")
        assert request.request_id is not None
        assert len(request.request_id) > 0
        assert hasattr(request, "start_time")

    def test_process_request_uses_existing_request_id(self):
        """Teste se usa X-Request-ID existente."""
        request = self.factory.get("/api/test/", HTTP_X_REQUEST_ID="existing-123")

        self.middleware.process_request(request)

        assert request.request_id == "existing-123"

    def test_process_response_adds_headers(self):
        """Teste se o middleware adiciona headers de correlação."""
        request = self.factory.get("/api/test/")
        request.request_id = "test-123"
        request.start_time = 1234567890.0

        response = HttpResponse(b"OK")

        with patch("time.time", return_value=1234567890.1):
            processed_response = self.middleware.process_response(request, response)

        assert processed_response["X-Request-ID"] == "test-123"

    @patch("salonix_backend.middleware.logger")
    def test_logging_request_start(self, mock_logger):
        """Teste se loga início do request."""
        request = self.factory.get("/api/test/")

        self.middleware.process_request(request)

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert "Request started" in call_args[0][0]
        assert "request_id" in call_args[1]["extra"]
        assert "method" in call_args[1]["extra"]
        assert "endpoint" in call_args[1]["extra"]

    @patch("salonix_backend.middleware.logger")
    def test_logging_request_completion(self, mock_logger):
        """Teste se loga conclusão do request."""
        request = self.factory.get("/api/test/")
        request.request_id = "test-123"
        request.start_time = 1234567890.0
        request.user = self.user

        response = HttpResponse(b"OK")
        response.status_code = 200

        with patch("time.time", return_value=1234567890.1):
            self.middleware.process_response(request, response)

        # Deve ter sido chamado duas vezes: request start e completion
        assert mock_logger.info.call_count >= 1

        # Verificar se pelo menos uma chamada foi para completion
        completion_calls = [
            call
            for call in mock_logger.info.call_args_list
            if "Request completed" in call[0][0]
        ]
        assert len(completion_calls) > 0

        call_args = completion_calls[0]
        extra = call_args[1]["extra"]
        assert extra["request_id"] == "test-123"
        assert extra["status_code"] == 200
        assert "duration_ms" in extra
        assert extra["user_id"] == str(self.user.id)
        assert extra["tenant_id"] == self.tenant.slug

    @patch("salonix_backend.middleware.logger")
    def test_logging_exception(self, mock_logger):
        """Teste se loga exceções."""
        request = self.factory.get("/api/test/")
        request.request_id = "test-123"
        request.start_time = 1234567890.0
        request.user = self.user

        exception = ValueError("Test exception")

        with patch("time.time", return_value=1234567890.1):
            self.middleware.process_exception(request, exception)

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "Request failed with exception" in call_args[0][0]
        extra = call_args[1]["extra"]
        assert extra["request_id"] == "test-123"
        assert extra["exception_type"] == "ValueError"
        assert "duration_ms" in extra


class TestLoggingUtilities(TestCase):
    """Testes para utilitários de logging."""

    def test_get_request_id_generates_unique_ids(self):
        """Teste se get_request_id gera IDs únicos."""
        id1 = get_request_id()
        id2 = get_request_id()

        assert id1 != id2
        assert len(id1) > 0
        assert len(id2) > 0

    @patch("threading.current_thread")
    def test_setup_logging_context(self, mock_thread):
        """Teste configuração de contexto de logging."""
        request = Mock()
        mock_thread.return_value = Mock()

        setup_logging_context(request)

        assert hasattr(request, "request_id")
        assert mock_thread.return_value.request == request


@override_settings(
    LOGGING={
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "test": {
                "class": "logging.StreamHandler",
                "stream": StringIO(),
            },
        },
        "loggers": {
            "test_logger": {
                "handlers": ["test"],
                "level": "INFO",
            },
        },
    }
)
class TestLoggingIntegration(TestCase):
    """Testes de integração para logging."""

    def test_logging_configuration_works(self):
        """Teste se a configuração de logging funciona."""
        logger = logging.getLogger("test_logger")
        logger.info("Test message")

        # Se chegou até aqui sem erro, a configuração está funcionando
        assert True

    def test_json_formatter_integration(self):
        """Teste integração do formatador JSON."""
        output = StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(JSONFormatter())

        logger = logging.getLogger("test_json")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("Test JSON message")

        log_output = output.getvalue()
        assert log_output.strip()  # Deve ter conteúdo

        # Tentar parsear como JSON
        log_data = json.loads(log_output.strip())
        assert log_data["message"] == "Test JSON message"
        assert log_data["level"] == "INFO"
