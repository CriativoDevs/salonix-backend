"""
Sistema de validações centralizado para Salonix Backend.

Este módulo fornece:
- Validadores customizados reutilizáveis
- Validações de negócio específicas
- Sanitização de dados
- Validações de formato
- Validações de integridade
"""

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Union

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, URLValidator
from django.utils import timezone
from django.utils.deconstruct import deconstructible
from rest_framework import serializers

from salonix_backend.error_handling import (
    BusinessError,
    ErrorCodes,
    SalonixError,
)


# =====================================================
# VALIDADORES DE FORMATO
# =====================================================


@deconstructible
class PhoneNumberValidator:
    """Validador para números de telefone portugueses e internacionais."""

    message = (
        "Número de telefone inválido. Use formato português (+351...) ou internacional."
    )
    code = "invalid_phone"

    def __call__(self, value: str):
        if not value:
            return

        # Remover espaços e caracteres especiais
        clean_value = re.sub(r"[^\d+]", "", str(value))

        # Padrões aceitos (apenas dígitos após códigos)
        patterns = [
            r"^\+351[0-9]{9}$",  # Portugal: +351XXXXXXXXX
            r"^[0-9]{9}$",  # Nacional: XXXXXXXXX
            r"^\+[1-9][0-9]{7,14}$",  # Internacional: +XXXXXXXXXXXXXXX (min 8 dígitos após código país)
        ]

        if not any(re.match(pattern, clean_value) for pattern in patterns):
            raise ValidationError(self.message, code=self.code)


@deconstructible
class PostalCodeValidator:
    """Validador para códigos postais portugueses."""

    message = "Código postal inválido. Use formato XXXX-XXX."
    code = "invalid_postal_code"

    def __call__(self, value: str):
        if not value:
            return

        # Padrão português: XXXX-XXX
        pattern = r"^[0-9]{4}-[0-9]{3}$"

        if not re.match(pattern, str(value)):
            raise ValidationError(self.message, code=self.code)


@deconstructible
class NIFValidator:
    """Validador para Número de Identificação Fiscal português."""

    message = "NIF inválido. Deve ter 9 dígitos e ser válido."
    code = "invalid_nif"

    def __call__(self, value: str):
        if not value:
            return

        # Remover espaços
        clean_value = re.sub(r"\s+", "", str(value))

        # Deve ter exatamente 9 dígitos
        if not re.match(r"^[0-9]{9}$", clean_value):
            raise ValidationError(self.message, code=self.code)

        # Algoritmo de validação do NIF
        if not self._validate_nif_checksum(clean_value):
            raise ValidationError(self.message, code=self.code)

    def _validate_nif_checksum(self, nif: str) -> bool:
        """Valida o dígito de controle do NIF."""
        if len(nif) != 9:
            return False

        # Multiplicadores
        multipliers = [9, 8, 7, 6, 5, 4, 3, 2]

        # Calcular soma
        total = sum(int(nif[i]) * multipliers[i] for i in range(8))

        # Calcular dígito de controle
        remainder = total % 11
        check_digit = 0 if remainder < 2 else 11 - remainder

        return int(nif[8]) == check_digit


@deconstructible
class PriceValidator:
    """Validador para preços monetários."""

    def __init__(
        self,
        min_value: Decimal = Decimal("0.01"),
        max_value: Decimal = Decimal("9999.99"),
    ):
        self.min_value = min_value
        self.max_value = max_value

    def __call__(self, value: Union[str, int, float, Decimal]):
        if value is None:
            return

        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, TypeError):
            raise ValidationError(
                "Preço deve ser um valor numérico válido.", code="invalid_price_format"
            )

        if decimal_value < self.min_value:
            raise ValidationError(
                f"Preço deve ser pelo menos {self.min_value}€.", code="price_too_low"
            )

        if decimal_value > self.max_value:
            raise ValidationError(
                f"Preço não pode exceder {self.max_value}€.", code="price_too_high"
            )

        # Validar casas decimais (máximo 2)
        from typing import cast
        if cast(int, decimal_value.as_tuple().exponent) < -2:
            raise ValidationError(
                "Preço não pode ter mais de 2 casas decimais.", code="too_many_decimals"
            )


@deconstructible
class DurationValidator:
    """Validador para durações em minutos."""

    def __init__(self, min_minutes: int = 5, max_minutes: int = 480):  # 8 horas max
        self.min_minutes = min_minutes
        self.max_minutes = max_minutes

    def __call__(self, value: int):
        if value is None:
            return

        try:
            minutes = int(value)
        except (ValueError, TypeError):
            raise ValidationError(
                "Duração deve ser um número inteiro de minutos.",
                code="invalid_duration_format",
            )

        if minutes < self.min_minutes:
            raise ValidationError(
                f"Duração deve ser pelo menos {self.min_minutes} minutos.",
                code="duration_too_short",
            )

        if minutes > self.max_minutes:
            raise ValidationError(
                f"Duração não pode exceder {self.max_minutes} minutos.",
                code="duration_too_long",
            )

        # Validar múltiplos de 5 minutos
        if minutes % 5 != 0:
            raise ValidationError(
                "Duração deve ser múltipla de 5 minutos.",
                code="invalid_duration_increment",
            )


# =====================================================
# VALIDADORES DE NEGÓCIO
# =====================================================


class BusinessHoursValidator:
    """Validador para horários de funcionamento."""

    def __init__(self, min_hour: int = 6, max_hour: int = 23):
        self.min_hour = min_hour
        self.max_hour = max_hour

    def __call__(self, start_time: datetime, end_time: datetime):
        """Valida horário de funcionamento."""
        if not start_time or not end_time:
            return

        # Validar se end_time é após start_time
        if end_time <= start_time:
            raise BusinessError(
                "Horário de fim deve ser posterior ao horário de início.",
                code=ErrorCodes.VALIDATION_INVALID_VALUE,
            )

        # Validar duração mínima (15 minutos)
        min_duration = timedelta(minutes=15)
        if end_time - start_time < min_duration:
            raise BusinessError(
                "Duração mínima do horário é de 15 minutos.",
                code=ErrorCodes.VALIDATION_INVALID_VALUE,
            )

        # Validar duração máxima (8 horas)
        max_duration = timedelta(hours=8)
        if end_time - start_time > max_duration:
            raise BusinessError(
                "Duração máxima do horário é de 8 horas.",
                code=ErrorCodes.VALIDATION_INVALID_VALUE,
            )

        # Validar horários comerciais
        if start_time.hour < self.min_hour or start_time.hour > self.max_hour:
            raise BusinessError(
                f"Horário de início deve estar entre {self.min_hour}h e {self.max_hour}h.",
                code=ErrorCodes.BUSINESS_SLOT_UNAVAILABLE,
            )

        if end_time.hour > self.max_hour or (
            end_time.hour == 0 and end_time.minute > 0
        ):
            raise BusinessError(
                f"Horário de fim deve estar até {self.max_hour}h.",
                code=ErrorCodes.BUSINESS_SLOT_UNAVAILABLE,
            )


class FutureTimeValidator:
    """Validador para garantir que o horário é no futuro."""

    def __init__(self, min_advance_minutes: int = 30):
        self.min_advance_minutes = min_advance_minutes

    def __call__(self, value: datetime):
        if not value:
            return

        now = timezone.now()
        min_time = now + timedelta(minutes=self.min_advance_minutes)

        if value <= min_time:
            raise BusinessError(
                f"Agendamento deve ser feito com pelo menos {self.min_advance_minutes} minutos de antecedência.",
                code=ErrorCodes.BUSINESS_SLOT_UNAVAILABLE,
            )


class WorkdayValidator:
    """Validador para dias úteis (segunda a sábado)."""

    def __call__(self, value: datetime):
        if not value:
            return

        # Domingo = 6
        if value.weekday() == 6:
            raise BusinessError(
                "Agendamentos não são permitidos aos domingos.",
                code=ErrorCodes.BUSINESS_SLOT_UNAVAILABLE,
            )


# =====================================================
# VALIDADORES DE INTEGRIDADE
# =====================================================


class TenantOwnershipValidator:
    """Validador para garantir que recursos pertencem ao tenant correto."""

    def __init__(self, model_class, tenant_field: str = "tenant"):
        self.model_class = model_class
        self.tenant_field = tenant_field

    def __call__(self, resource_id: int, tenant):
        if not resource_id or not tenant:
            return

        try:
            resource = self.model_class.objects.get(id=resource_id)
        except self.model_class.DoesNotExist:
            raise BusinessError(
                f"{self.model_class.__name__} não encontrado.",
                code=ErrorCodes.RESOURCE_NOT_FOUND,
            )

        resource_tenant = getattr(resource, self.tenant_field)
        if resource_tenant != tenant:
            raise BusinessError(
                f"{self.model_class.__name__} não pertence ao tenant atual.",
                code=ErrorCodes.RESOURCE_ACCESS_DENIED,
            )


class UniqueTogetherValidator:
    """Validador para campos únicos em conjunto."""

    def __init__(
        self, model_class, fields: List[str], exclude_id: Optional[int] = None
    ):
        self.model_class = model_class
        self.fields = fields
        self.exclude_id = exclude_id

    def __call__(self, data: Dict[str, Any]):
        # Construir filtro
        filter_kwargs = {
            field: data.get(field)
            for field in self.fields
            if data.get(field) is not None
        }

        if not filter_kwargs:
            return

        queryset = self.model_class.objects.filter(**filter_kwargs)

        if self.exclude_id:
            queryset = queryset.exclude(id=self.exclude_id)

        if queryset.exists():
            field_names = ", ".join(self.fields)
            raise BusinessError(
                f"Já existe um registro com essa combinação de {field_names}.",
                code=ErrorCodes.VALIDATION_DUPLICATE_VALUE,
            )


# =====================================================
# SANITIZADORES
# =====================================================


def sanitize_text_input(value: str, max_length: Optional[int] = None) -> str:
    """Sanitiza entrada de texto."""
    if not value:
        return ""

    # Remover espaços extras
    sanitized = re.sub(r"\s+", " ", str(value).strip())

    # Remover caracteres de controle
    sanitized = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", sanitized)

    # Truncar se necessário
    if max_length and len(sanitized) > max_length:
        sanitized = sanitized[:max_length].strip()

    return sanitized


def sanitize_phone_number(value: str) -> str:
    """Sanitiza número de telefone."""
    if not value:
        return ""

    # Remover tudo exceto dígitos e +
    sanitized = re.sub(r"[^\d+]", "", str(value))

    # Adicionar +351 se for número nacional português
    if re.match(r"^[0-9]{9}$", sanitized):
        sanitized = f"+351{sanitized}"

    return sanitized


def sanitize_postal_code(value: str) -> str:
    """Sanitiza código postal português."""
    if not value:
        return ""

    # Remover tudo exceto dígitos e hífen
    sanitized = re.sub(r"[^\d-]", "", str(value))

    # Adicionar hífen se necessário
    if re.match(r"^[0-9]{7}$", sanitized):
        sanitized = f"{sanitized[:4]}-{sanitized[4:]}"

    return sanitized


# =====================================================
# VALIDADORES COMPOSTOS
# =====================================================


def validate_appointment_data(data: Dict[str, Any], tenant, user) -> Dict[str, Any]:
    """Validação completa para dados de agendamento."""
    errors = {}

    # Validar slot
    slot = data.get("slot")
    if slot:
        try:
            # Validar propriedade do tenant
            slot_validator = TenantOwnershipValidator(slot.__class__)
            slot_validator(slot.id, tenant)

            # Validar horário futuro
            future_validator = FutureTimeValidator(min_advance_minutes=30)
            future_validator(slot.start_time)

            # Validar dia útil
            workday_validator = WorkdayValidator()
            workday_validator(slot.start_time)

            # Validar horário comercial
            business_hours_validator = BusinessHoursValidator()
            business_hours_validator(slot.start_time, slot.end_time)

        except BusinessError as e:
            errors["slot"] = e.message

    # Validar serviço
    service = data.get("service")
    if service:
        try:
            service_validator = TenantOwnershipValidator(service.__class__)
            service_validator(service.id, tenant)
        except BusinessError as e:
            errors["service"] = e.message

    # Validar profissional
    professional = data.get("professional")
    if professional:
        try:
            prof_validator = TenantOwnershipValidator(professional.__class__)
            prof_validator(professional.id, tenant)
        except BusinessError as e:
            errors["professional"] = e.message

    # Validar compatibilidade slot-profissional
    if slot and professional and slot.professional != professional:
        errors["slot"] = "Slot não pertence ao profissional selecionado."

    # Validar notas
    notes = data.get("notes", "")
    if notes:
        data["notes"] = sanitize_text_input(notes, max_length=500)

    if errors:
        raise SalonixError(
            "Dados de agendamento inválidos",
            code=ErrorCodes.VALIDATION_INVALID_VALUE,
            details=errors,
        )

    return data


def validate_service_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validação completa para dados de serviço."""
    # Validar nome
    if "name" in data:
        data["name"] = sanitize_text_input(data["name"], max_length=200)
        if not data["name"]:
            raise SalonixError(
                "Nome do serviço é obrigatório",
                code=ErrorCodes.VALIDATION_REQUIRED_FIELD,
            )

    # Validar preço
    if "price_eur" in data:
        price_validator = PriceValidator()
        price_validator(data["price_eur"])

    # Validar duração
    if "duration_minutes" in data:
        duration_validator = DurationValidator()
        duration_validator(data["duration_minutes"])

    return data


def validate_professional_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validação completa para dados de profissional."""
    # Validar nome
    if "name" in data:
        data["name"] = sanitize_text_input(data["name"], max_length=200)
        if not data["name"]:
            raise SalonixError(
                "Nome do profissional é obrigatório",
                code=ErrorCodes.VALIDATION_REQUIRED_FIELD,
            )

    # Validar bio
    if "bio" in data:
        data["bio"] = sanitize_text_input(data["bio"], max_length=1000)

    return data


# =====================================================
# INSTÂNCIAS GLOBAIS
# =====================================================

# Validadores de formato
validate_phone_number = PhoneNumberValidator()
validate_postal_code = PostalCodeValidator()
validate_nif = NIFValidator()
validate_price = PriceValidator()
validate_duration = DurationValidator()

# Validadores de negócio
validate_business_hours = BusinessHoursValidator()
validate_future_time = FutureTimeValidator()
validate_workday = WorkdayValidator()
