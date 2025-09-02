"""
Utilitários para testes com multi-tenant
"""

from users.models import Tenant
from core.models import Service, Professional, ScheduleSlot, Appointment


def create_service_with_tenant(tenant, **kwargs):
    """Cria Service com tenant automaticamente"""
    return Service.objects.create(tenant=tenant, **kwargs)


def create_professional_with_tenant(tenant, **kwargs):
    """Cria Professional com tenant automaticamente"""
    return Professional.objects.create(tenant=tenant, **kwargs)


def create_slot_with_tenant(tenant, **kwargs):
    """Cria ScheduleSlot com tenant automaticamente"""
    return ScheduleSlot.objects.create(tenant=tenant, **kwargs)


def create_appointment_with_tenant(tenant, **kwargs):
    """Cria Appointment com tenant automaticamente"""
    return Appointment.objects.create(tenant=tenant, **kwargs)


def get_or_create_default_tenant():
    """Obtém ou cria o tenant padrão para testes"""
    tenant, _ = Tenant.objects.get_or_create(
        slug="test-default",
        defaults={
            "name": "Test Default Salon",
            "primary_color": "#3B82F6",
            "secondary_color": "#1F2937",
        },
    )
    return tenant
