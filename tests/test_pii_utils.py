"""
Testes para utilitários de mascaramento de PII.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from salonix_backend.pii_utils import (
    mask_email,
    mask_phone,
    mask_cpf,
    mask_identifier,
    mask_pii_dict,
    mask_user_repr,
    is_sensitive_field,
    sanitize_log_data,
)

User = get_user_model()


class TestMaskEmail:
    """Testes para mascaramento de email."""

    def test_mask_standard_email(self):
        """Email padrão deve mascarar domínio completo."""
        assert mask_email("john.doe@example.com") == "j***@example.com"

    def test_mask_short_local_part(self):
        """Email com local part curto."""
        assert mask_email("a@test.com") == "a***@test.com"

    def test_mask_long_local_part(self):
        """Email com local part longo."""
        assert mask_email("verylongemailaddress@domain.co.uk") == "v***@domain.co.uk"

    def test_mask_email_with_plus(self):
        """Email com caractere + (gmail aliases)."""
        assert mask_email("user+tag@gmail.com") == "u***@gmail.com"

    def test_mask_email_none(self):
        """None deve retornar None."""
        assert mask_email(None) is None

    def test_mask_email_empty(self):
        """String vazia deve retornar None."""
        assert mask_email("") is None

    def test_mask_email_whitespace(self):
        """Email com espaços deve ser trimado."""
        assert mask_email("  john@example.com  ") == "j***@example.com"


class TestMaskPhone:
    """Testes para mascaramento de telefone."""

    def test_mask_phone_international(self):
        """Telefone com formato internacional."""
        result = mask_phone("+5511987654321")
        assert "+55 11" in result
        assert "4321" in result
        assert "**" in result

    def test_mask_phone_with_formatting(self):
        """Telefone com formatação (XX) XXXXX-XXXX."""
        result = mask_phone("(11) 98765-4321")
        assert "(11)" in result
        assert "4321" in result
        assert "***" in result

    def test_mask_phone_digits_only(self):
        """Telefone apenas com dígitos."""
        result = mask_phone("11987654321")
        assert "4321" in result
        assert "***" in result

    def test_mask_phone_none(self):
        """None deve retornar None."""
        assert mask_phone(None) is None

    def test_mask_phone_empty(self):
        """String vazia deve retornar None."""
        assert mask_phone("") is None

    def test_mask_phone_short(self):
        """Telefone muito curto."""
        result = mask_phone("123")
        assert result == "****"


class TestMaskCPF:
    """Testes para mascaramento de CPF."""

    def test_mask_cpf_formatted(self):
        """CPF com formatação XXX.XXX.XXX-XX."""
        assert mask_cpf("123.456.789-01") == "***.***.**-01"

    def test_mask_cpf_unformatted(self):
        """CPF sem formatação."""
        assert mask_cpf("12345678901") == "***.***.**-01"

    def test_mask_cpf_none(self):
        """None deve retornar None."""
        assert mask_cpf(None) is None

    def test_mask_cpf_empty(self):
        """String vazia deve retornar None."""
        assert mask_cpf("") is None

    def test_mask_cpf_short(self):
        """CPF muito curto."""
        assert mask_cpf("123") == "***"


class TestMaskIdentifier:
    """Testes para mascaramento de identificadores genéricos."""

    def test_mask_identifier_default(self):
        """Identificador padrão."""
        result = mask_identifier("ABC123456789")
        assert "6789" in result
        assert "****" in result

    def test_mask_identifier_short(self):
        """Identificador muito curto."""
        result = mask_identifier("12345")
        assert result == "****"

    def test_mask_identifier_none(self):
        """None deve retornar None."""
        assert mask_identifier(None) is None

    def test_mask_identifier_empty(self):
        """String vazia deve retornar None."""
        assert mask_identifier("") is None


class TestMaskPIIDict:
    """Testes para mascaramento de dicionários com PII."""

    def test_mask_pii_dict_auto_email(self):
        """Detectar e mascarar email automaticamente."""
        data = {"email": "john@example.com", "name": "John"}
        result = mask_pii_dict(data)
        assert result["email"] == "j***@example.com"
        assert result["name"] == "John"

    def test_mask_pii_dict_auto_phone(self):
        """Detectar e mascarar telefone automaticamente."""
        data = {"phone_number": "11987654321", "id": 123}
        result = mask_pii_dict(data)
        assert "4321" in result["phone_number"]
        assert result["id"] == 123

    def test_mask_pii_dict_custom_fields(self):
        """Mascarar campos customizados."""
        data = {"email": "john@example.com", "phone": "+5511987654321"}
        sensitive = {"email": "email", "phone": "phone"}
        result = mask_pii_dict(data, sensitive)
        assert result["email"] == "j***@example.com"
        assert "4321" in result["phone"]

    def test_mask_pii_dict_none(self):
        """None deve retornar None."""
        assert mask_pii_dict(None) is None

    def test_mask_pii_dict_preserves_unmapped(self):
        """Campos não mapeados devem ser preservados."""
        data = {"email": "john@example.com", "status": "active"}
        result = mask_pii_dict(data)
        assert "email" in result
        assert "status" in result
        assert result["status"] == "active"


class TestMaskUserRepr(TestCase):
    """Testes para representação mascarada de usuário."""

    def test_mask_user_repr_basic(self):
        """Representação básica de usuário."""
        user = User.objects.create_user(
            username="johndoe", email="john@example.com", password="testpass123"
        )
        result = mask_user_repr(user)

        assert result["user_id"] == user.id
        assert result["username"] == "johndoe"
        assert result["email"] == "j***@example.com"

    def test_mask_user_repr_none(self):
        """None deve retornar dicionário vazio."""
        assert mask_user_repr(None) == {}

    def test_mask_user_repr_with_phone(self):
        """Representação com telefone."""
        user = User.objects.create_user(
            username="johndoe", email="john@example.com", password="testpass123"
        )
        user.phone_number = "11987654321"
        result = mask_user_repr(user)

        assert "phone" in result
        assert "4321" in result["phone"]


class TestIsSensitiveField:
    """Testes para detecção de campos sensíveis."""

    def test_is_sensitive_password(self):
        """Campo 'password' é sensível."""
        assert is_sensitive_field("password") is True

    def test_is_sensitive_token(self):
        """Campo com 'token' é sensível."""
        assert is_sensitive_field("access_token") is True
        assert is_sensitive_field("refresh_token") is True

    def test_is_sensitive_api_key(self):
        """Campo com 'api_key' é sensível."""
        assert is_sensitive_field("api_key") is True
        assert is_sensitive_field("stripe_api_key") is True

    def test_is_sensitive_case_insensitive(self):
        """Detecção deve ser case-insensitive."""
        assert is_sensitive_field("PASSWORD") is True
        assert is_sensitive_field("Token") is True

    def test_is_not_sensitive_normal_field(self):
        """Campo normal não é sensível."""
        assert is_sensitive_field("email") is False
        assert is_sensitive_field("username") is False


class TestSanitizeLogData:
    """Testes para sanitização de dados de log."""

    def test_sanitize_removes_password(self):
        """Campo password deve ser removido."""
        data = {"email": "john@example.com", "password": "secret123"}
        result = sanitize_log_data(data)

        assert result["password"] == "[REDACTED]"
        assert "secret123" not in str(result)

    def test_sanitize_masks_email(self):
        """Email deve ser mascarado."""
        data = {"email": "john@example.com"}
        result = sanitize_log_data(data)

        assert result["email"] == "j***@example.com"

    def test_sanitize_masks_phone(self):
        """Telefone deve ser mascarado."""
        data = {"phone_number": "11987654321"}
        result = sanitize_log_data(data)

        assert "4321" in result["phone_number"]

    def test_sanitize_preserves_non_sensitive(self):
        """Dados não sensíveis devem ser preservados."""
        data = {"name": "John", "status": "active"}
        result = sanitize_log_data(data)

        assert result["name"] == "John"
        assert result["status"] == "active"

    def test_sanitize_multiple_sensitive_fields(self):
        """Múltiplos campos sensíveis."""
        data = {
            "email": "john@example.com",
            "phone": "11987654321",
            "password": "secret",
            "api_key": "sk_live_xxx",
        }
        result = sanitize_log_data(data)

        assert result["email"] == "j***@example.com"
        assert result["password"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"
