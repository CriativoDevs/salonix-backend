import pytest
from users.models import CustomUser, Tenant
from core.models import Service, Professional, ScheduleSlot, Appointment


@pytest.fixture(autouse=True)
def setup_default_tenant(db):
    """Cria tenant padrão para todos os testes automaticamente"""
    tenant, _ = Tenant.objects.get_or_create(
        slug="test-default",
        defaults={
            "name": "Test Default Salon",
            "primary_color": "#3B82F6",
            "secondary_color": "#1F2937",
        },
    )

    # Monkey patch para definir tenant automaticamente
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

    Service.save = service_save_with_tenant
    Professional.save = professional_save_with_tenant
    ScheduleSlot.save = slot_save_with_tenant
    Appointment.save = appointment_save_with_tenant
    CustomUser.save = user_save_with_tenant

    return tenant


@pytest.fixture
def tenant_fixture(db, setup_default_tenant):
    """Retorna o tenant padrão"""
    return setup_default_tenant


@pytest.fixture
def user_fixture(db, tenant_fixture):
    return CustomUser.objects.create_user(
        username="testuser", email="test@example.com", password="testpass"
    )
