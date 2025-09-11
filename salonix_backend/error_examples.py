"""
Exemplos de uso do sistema de tratamento de erros.

Este arquivo demonstra como usar as funcionalidades do error_handling.py
nas views e serializers do projeto.
"""

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .error_handling import (
    BusinessError,
    ErrorCodes,
    FeatureDisabledError,
    SalonixError,
    TenantError,
    create_error_response,
    handle_business_errors,
    validate_required_fields,
)


# =====================================================
# EXEMPLO 1: View com tratamento de erros de negócio
# =====================================================


@api_view(["POST"])
@handle_business_errors
def example_appointment_create(request):
    """Exemplo de criação de agendamento com tratamento de erros."""

    # Validar campos obrigatórios
    try:
        validate_required_fields(
            request.data, ["service_id", "slot_id", "client_email"]
        )
    except ValidationError as e:
        # O custom_exception_handler vai tratar automaticamente
        raise

    # Simular verificação de tenant
    tenant = getattr(request, "tenant", None)
    if not tenant:
        raise TenantError("Tenant não encontrado ou não especificado")

    if not tenant.is_active:
        raise TenantError("Tenant inativo", code=ErrorCodes.BUSINESS_TENANT_INACTIVE)

    # Simular verificação de feature
    if not tenant.can_use_appointments():
        raise FeatureDisabledError("appointments", tenant.name)

    # Simular conflito de horário
    slot_id = request.data.get("slot_id")
    if slot_id == "999":  # Slot já ocupado
        raise BusinessError(
            "Horário já está ocupado por outro agendamento",
            code=ErrorCodes.BUSINESS_APPOINTMENT_CONFLICT,
            details={
                "slot_id": slot_id,
                "conflicting_appointment": "123",
                "suggested_slots": ["1001", "1002", "1003"],
            },
        )

    # Simular limite de plano
    if tenant.plan_tier == "free" and tenant.monthly_appointments >= 10:
        raise BusinessError(
            "Limite mensal de agendamentos atingido para o plano gratuito",
            code=ErrorCodes.BUSINESS_PLAN_LIMIT_EXCEEDED,
            details={
                "current_count": tenant.monthly_appointments,
                "plan_limit": 10,
                "plan_tier": "free",
                "upgrade_url": "/upgrade",
            },
        )

    # Sucesso
    return Response(
        {
            "id": "new_appointment_123",
            "message": "Agendamento criado com sucesso",
            "status": "confirmed",
        }
    )


# =====================================================
# EXEMPLO 2: View com erro customizado
# =====================================================


@api_view(["GET"])
def example_external_service(request):
    """Exemplo de integração com serviço externo."""

    try:
        # Simular chamada para serviço externo
        import requests

        response = requests.get("https://api.example.com/data", timeout=5)
        response.raise_for_status()

        return Response({"data": response.json()})

    except requests.Timeout:
        raise SalonixError(
            "Timeout ao conectar com serviço externo",
            code=ErrorCodes.SYSTEM_EXTERNAL_SERVICE_ERROR,
            details={"service": "example_api", "timeout": 5, "retry_after": 60},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    except requests.RequestException as e:
        raise SalonixError(
            "Erro na comunicação com serviço externo",
            code=ErrorCodes.SYSTEM_EXTERNAL_SERVICE_ERROR,
            details={"service": "example_api", "error": str(e)},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


# =====================================================
# EXEMPLO 3: View com validação customizada
# =====================================================


@api_view(["POST"])
def example_user_registration(request):
    """Exemplo de registro de usuário com validações."""

    data = request.data

    # Validação de email
    email = data.get("email", "").lower().strip()
    if not email or "@" not in email:
        return create_error_response(
            "Email inválido",
            code=ErrorCodes.VALIDATION_INVALID_FORMAT,
            status_code=status.HTTP_400_BAD_REQUEST,
            details={
                "field": "email",
                "provided_value": data.get("email"),
                "expected_format": "usuario@dominio.com",
            },
        )

    # Verificar se email já existe
    from users.models import CustomUser

    if CustomUser.objects.filter(email=email).exists():
        return create_error_response(
            "Email já está em uso",
            code=ErrorCodes.VALIDATION_DUPLICATE_VALUE,
            status_code=status.HTTP_409_CONFLICT,
            details={
                "field": "email",
                "value": email,
                "suggestion": "Tente fazer login ou use um email diferente",
            },
        )

    # Validação de senha
    password = data.get("password", "")
    if len(password) < 8:
        return create_error_response(
            "Senha deve ter pelo menos 8 caracteres",
            code=ErrorCodes.VALIDATION_INVALID_VALUE,
            status_code=status.HTTP_400_BAD_REQUEST,
            details={
                "field": "password",
                "min_length": 8,
                "current_length": len(password),
            },
        )

    # Sucesso
    return Response(
        {"message": "Usuário registrado com sucesso", "user_id": "new_user_123"}
    )


# =====================================================
# EXEMPLO 4: Serializer com validação customizada
# =====================================================

from rest_framework import serializers


class ExampleAppointmentSerializer(serializers.Serializer):
    """Exemplo de serializer com validações customizadas."""

    service_id = serializers.IntegerField()
    slot_id = serializers.IntegerField()
    client_email = serializers.EmailField()
    notes = serializers.CharField(max_length=500, required=False)

    def validate_service_id(self, value):
        """Validar se o serviço existe e está ativo."""
        from core.models import Service

        try:
            service = Service.objects.get(id=value, is_active=True)
        except Service.DoesNotExist:
            raise serializers.ValidationError(
                f"Serviço com ID {value} não encontrado ou inativo"
            )

        # Verificar se o serviço pertence ao tenant atual
        request = self.context.get("request")
        if request and hasattr(request, "tenant"):
            if service.tenant != request.tenant:
                raise serializers.ValidationError(
                    "Serviço não pertence ao tenant atual"
                )

        return value

    def validate_slot_id(self, value):
        """Validar se o slot existe e está disponível."""
        from core.models import ScheduleSlot

        try:
            slot = ScheduleSlot.objects.get(id=value)
        except ScheduleSlot.DoesNotExist:
            raise serializers.ValidationError(f"Slot com ID {value} não encontrado")

        if not slot.is_available:
            raise serializers.ValidationError(
                "Slot não está disponível", code=ErrorCodes.BUSINESS_SLOT_UNAVAILABLE
            )

        return value

    def validate(self, attrs):
        """Validação cruzada dos dados."""
        service_id = attrs.get("service_id")
        slot_id = attrs.get("slot_id")

        # Verificar se o slot é compatível com o serviço
        # (exemplo: duração do serviço vs. duração do slot)
        if service_id and slot_id:
            from core.models import Service, ScheduleSlot

            try:
                service = Service.objects.get(id=service_id)
                slot = ScheduleSlot.objects.get(id=slot_id)

                slot_duration = (slot.end_time - slot.start_time).total_seconds() / 60
                if service.duration_minutes > slot_duration:
                    raise serializers.ValidationError(
                        f"Serviço requer {service.duration_minutes} minutos, "
                        f"mas slot tem apenas {slot_duration} minutos"
                    )
            except (Service.DoesNotExist, ScheduleSlot.DoesNotExist):
                pass  # Já validado nos métodos individuais

        return attrs


# =====================================================
# EXEMPLO 5: Middleware para capturar erros não tratados
# =====================================================


class ErrorLoggingMiddleware:
    """Middleware para capturar erros não tratados pelas views."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_exception(self, request, exception):
        """Processar exceções não capturadas."""
        from .error_handling import log_error

        # Log do erro
        error_id = log_error(
            exception=exception,
            request=request,
            user=getattr(request, "user", None),
            tenant=getattr(request, "tenant", None),
            extra_context={"middleware": "ErrorLoggingMiddleware"},
        )

        # Retornar None para deixar o Django tratar o erro normalmente
        return None


# =====================================================
# EXEMPLO 6: Teste de integração
# =====================================================

from django.test import TestCase
from rest_framework.test import APIClient


class ErrorHandlingTestCase(TestCase):
    """Testes para o sistema de tratamento de erros."""

    def setUp(self):
        self.client = APIClient()

    def test_validation_error_format(self):
        """Testar formato de resposta para erros de validação."""
        response = self.client.post(
            "/api/example/appointment/",
            {
                # Dados inválidos propositalmente
                "service_id": "invalid",
                "client_email": "not-an-email",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)

        error = response.data["error"]
        self.assertIn("code", error)
        self.assertIn("message", error)
        self.assertIn("details", error)
        self.assertIn("error_id", error)

        # Verificar se o código está no formato esperado
        self.assertTrue(error["code"].startswith("E"))

    def test_business_error_format(self):
        """Testar formato de resposta para erros de negócio."""
        # Simular erro de tenant inativo
        response = self.client.post(
            "/api/example/appointment/",
            {"service_id": 1, "slot_id": 1, "client_email": "test@example.com"},
            HTTP_X_TENANT_SLUG="inactive-tenant",
        )

        self.assertEqual(response.status_code, 400)

        error = response.data["error"]
        self.assertEqual(error["code"], ErrorCodes.BUSINESS_TENANT_INACTIVE)
        self.assertIn("Tenant inativo", error["message"])

    def test_system_error_format(self):
        """Testar formato de resposta para erros de sistema."""
        # Simular erro de serviço externo
        response = self.client.get("/api/example/external-service/")

        # Verificar se o erro foi tratado adequadamente
        if response.status_code >= 500:
            error = response.data["error"]
            self.assertIn("code", error)
            self.assertIn("error_id", error)
