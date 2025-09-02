"""
Configurações globais de testes para multi-tenant
"""

import pytest
from unittest.mock import patch
from users.models import CustomUser, Tenant
from core.models import Service, Professional, ScheduleSlot, Appointment


@pytest.fixture(autouse=True, scope="function")
def setup_default_tenant(db):
    """Cria tenant padrão para todos os testes automaticamente"""
    # Limpar qualquer tenant existente
    Tenant.objects.all().delete()

    tenant = Tenant.objects.create(
        slug="test-default",
        name="Test Default Salon",
        primary_color="#3B82F6",
        secondary_color="#1F2937",
    )

    # Monkey patch para definir tenant automaticamente em objetos que não têm
    original_service_save = Service.save
    original_professional_save = Professional.save
    original_slot_save = ScheduleSlot.save
    original_appointment_save = Appointment.save
    original_user_save = CustomUser.save

    def service_save_with_tenant(self, *args, **kwargs):
        if self.tenant_id is None:
            self.tenant = tenant
        return original_service_save(self, *args, **kwargs)

    def professional_save_with_tenant(self, *args, **kwargs):
        if self.tenant_id is None:
            self.tenant = tenant
        return original_professional_save(self, *args, **kwargs)

    def slot_save_with_tenant(self, *args, **kwargs):
        if self.tenant_id is None:
            self.tenant = tenant
        return original_slot_save(self, *args, **kwargs)

    def appointment_save_with_tenant(self, *args, **kwargs):
        if self.tenant_id is None:
            self.tenant = tenant
        return original_appointment_save(self, *args, **kwargs)

    def user_save_with_tenant(self, *args, **kwargs):
        if self.tenant_id is None:
            self.tenant = tenant
        return original_user_save(self, *args, **kwargs)

    # Aplicar monkey patches
    Service.save = service_save_with_tenant
    Professional.save = professional_save_with_tenant
    ScheduleSlot.save = slot_save_with_tenant
    Appointment.save = appointment_save_with_tenant
    CustomUser.save = user_save_with_tenant

    # Mock do middleware para definir request.tenant nos testes
    def mock_tenant_middleware(get_response):
        def middleware(request):
            request.tenant = tenant
            return get_response(request)

        return middleware

    with patch("core.middleware.TenantMiddleware", mock_tenant_middleware):
        yield tenant

    # Cleanup: restaurar métodos originais
    Service.save = original_service_save
    Professional.save = original_professional_save
    ScheduleSlot.save = original_slot_save
    Appointment.save = original_appointment_save
    CustomUser.save = original_user_save


@pytest.fixture
def tenant_fixture(setup_default_tenant):
    """Retorna o tenant padrão"""
    return setup_default_tenant


@pytest.fixture
def user_fixture(db, tenant_fixture):
    """Cria usuário padrão para testes"""
    return CustomUser.objects.create_user(
        username="testuser", email="test@example.com", password="testpass"
    )


@pytest.fixture(autouse=True)
def mock_tenant_in_views(setup_default_tenant):
    """
    Mock automático para definir request.tenant em todas as views que usam TenantAwareMixin
    """
    from unittest.mock import patch
    from core.mixins import TenantIsolatedMixin

    original_get_queryset = TenantIsolatedMixin.get_queryset

    def mock_get_queryset(self):
        # Definir tenant no request se não estiver definido
        if not hasattr(self.request, "tenant") or self.request.tenant is None:
            # Tentar usar o tenant do usuário autenticado primeiro
            if (
                hasattr(self.request, "user")
                and hasattr(self.request.user, "tenant")
                and self.request.user.tenant is not None
            ):
                self.request.tenant = self.request.user.tenant
            else:
                self.request.tenant = setup_default_tenant
        return original_get_queryset(self)

    # Aplicar o mock
    TenantIsolatedMixin.get_queryset = mock_get_queryset

    yield

    # Restaurar método original
    TenantIsolatedMixin.get_queryset = original_get_queryset
