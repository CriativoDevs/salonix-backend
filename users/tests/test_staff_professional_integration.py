import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIRequestFactory, APIClient

from users.models import CustomUser, Tenant, TenantStaffMember
from users.serializers import (
    StaffUpdateSerializer,
    StaffAcceptInviteSerializer,
    UserRegistrationSerializer,
)
from core.models import Professional, Service, ProfessionalService


@pytest.mark.django_db
def test_collaborator_activation_creates_professional():
    tenant = Tenant.objects.create(name="Salon Alpha", slug="salon-alpha")

    owner = CustomUser.objects.create_user(
        username="owner",
        email="owner@example.com",
        password="pass123",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    collaborator = CustomUser.objects.create_user(
        username="collab",
        email="collab@example.com",
        password="pass123",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=collaborator,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.INVITED,
    )

    staff.mark_activated()

    professional = Professional.objects.get(staff_member=staff)
    assert professional.user == collaborator
    assert professional.tenant == tenant
    assert professional.is_active is True


@pytest.mark.django_db
def test_mark_disabled_deactivates_professional():
    tenant = Tenant.objects.create(name="Salon Beta", slug="salon-beta")
    owner = CustomUser.objects.create_user(
        username="owner-beta",
        email="owner-beta@example.com",
        password="pass123",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    collaborator = CustomUser.objects.create_user(
        username="collab-beta",
        email="collab-beta@example.com",
        password="pass123",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=collaborator,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )
    professional = staff.ensure_professional()
    assert professional is not None

    staff.mark_disabled()
    professional.refresh_from_db()
    assert professional.is_active is False


@pytest.mark.django_db
def test_staff_update_reactivates_professional():
    tenant = Tenant.objects.create(name="Salon Gamma", slug="salon-gamma")
    owner = CustomUser.objects.create_user(
        username="owner-gamma",
        email="owner-gamma@example.com",
        password="pass123",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    collaborator = CustomUser.objects.create_user(
        username="collab-gamma",
        email="collab-gamma@example.com",
        password="pass123",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=collaborator,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )
    professional = staff.ensure_professional()
    assert professional is not None

    staff.mark_disabled()
    professional.refresh_from_db()
    assert professional.is_active is False

    factory = APIRequestFactory()
    request = factory.patch("/api/users/staff/")
    request.user = owner
    serializer = StaffUpdateSerializer(
        instance=staff,
        data={"status": TenantStaffMember.Status.ACTIVE},
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    professional.refresh_from_db()
    assert professional.is_active is True
    assert staff.status == TenantStaffMember.Status.ACTIVE


@pytest.mark.django_db
def test_promoting_manager_to_collaborator_creates_professional():
    tenant = Tenant.objects.create(name="Salon Delta", slug="salon-delta")
    owner = CustomUser.objects.create_user(
        username="owner-delta",
        email="owner-delta@example.com",
        password="pass123",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    manager_user = CustomUser.objects.create_user(
        username="manager-delta",
        email="manager-delta@example.com",
        password="pass123",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=manager_user,
        role=TenantStaffMember.Role.MANAGER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    factory = APIRequestFactory()
    request = factory.patch("/api/users/staff/")
    request.user = owner
    serializer = StaffUpdateSerializer(
        instance=staff,
        data={"role": TenantStaffMember.Role.COLLABORATOR},
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    professional = Professional.objects.get(staff_member=staff)
    assert professional.user == manager_user
    assert professional.is_active is True


@pytest.mark.django_db
def test_owner_registration_auto_creates_professional():
    """
    BE-PROF-01: a maioria dos tenants é dono que atende sozinho. No
    registro (UserRegistrationSerializer.create), o owner já deve nascer
    com um Professional próprio, sem precisar criá-lo manualmente depois.
    """
    data = {
        "username": "owner-solo",
        "email": "owner-solo@example.com",
        "password": "StrongPass!9",
        "salon_name": "Studio Solo",
    }
    serializer = UserRegistrationSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()

    staff = TenantStaffMember.objects.get(user=user, role=TenantStaffMember.Role.OWNER)
    professional = Professional.objects.get(staff_member=staff)
    assert professional.user == user
    assert professional.tenant == user.tenant
    assert professional.is_active is True


@pytest.mark.django_db
def test_ensure_professional_for_owner_links_all_tenant_services():
    """
    BE-PROF-01: ensure_professional_for_owner() deve vincular o
    Professional recém-criado do owner a todos os Services já existentes
    do tenant via ProfessionalService (reaproveita
    link_all_tenant_services_to_professional, compartilhada com
    ProfessionalViewSet._auto_link_services_if_sole_active_staff).
    """
    tenant = Tenant.objects.create(name="Studio Solo 2", slug="studio-solo-2")
    owner = CustomUser.objects.create_user(
        username="owner-solo-2",
        email="owner-solo-2@example.com",
        password="pass123",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    service_a = Service.objects.create(
        tenant=tenant, user=owner, name="Tatuagem pequena", duration_minutes=60,
        price_eur=50,
    )
    service_b = Service.objects.create(
        tenant=tenant, user=owner, name="Tatuagem grande", duration_minutes=180,
        price_eur=200,
    )

    professional = staff.ensure_professional_for_owner()

    assert professional is not None
    linked_service_ids = set(
        ProfessionalService.objects.filter(
            tenant=tenant, professional=professional
        ).values_list("service_id", flat=True)
    )
    assert linked_service_ids == {service_a.id, service_b.id}


@pytest.mark.django_db
def test_ensure_professional_generic_still_ignores_owner():
    """
    Regressão: ensure_professional() (sem _allow_owner, usado por
    mark_activated/seed scripts/StaffUpdateSerializer) deve continuar
    retornando None para OWNER — só COLLABORATOR é auto-criado por essa
    via genérica. A criação de Professional para owner só acontece
    explicitamente via ensure_professional_for_owner().
    """
    tenant = Tenant.objects.create(name="Salon Zeta", slug="salon-zeta")
    owner = CustomUser.objects.create_user(
        username="owner-zeta",
        email="owner-zeta@example.com",
        password="pass123",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    result = staff.ensure_professional()

    assert result is None
    assert not Professional.objects.filter(staff_member=staff).exists()


@pytest.mark.django_db
def test_owner_can_delete_own_professional(user_fixture):
    """
    BE-PROF-01: owner que só gerencia (não atende) deve conseguir remover
    o próprio Professional auto-criado, sem erro — fluxo equivalente ao
    `deleteProfessional` do frontend (src/api/professionals.js:125)
    batendo em ProfessionalViewSet.destroy.

    Usa `user_fixture` (owner ACTIVE no tenant "test-default") porque o
    conftest.py global fixa `request.tenant` no tenant default para toda
    chamada HTTP de teste (autouse `setup_default_tenant`/`mock_tenant_in_views`);
    um tenant construído ad-hoc faria `ProfessionalViewSet.get_object()`
    rejeitar por "tenant" divergente — artefato do harness de teste, não
    do código de produção.
    """
    owner = user_fixture
    staff = owner.staff_member
    professional = staff.ensure_professional_for_owner()
    assert professional is not None

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.delete(f"/api/professionals/{professional.id}/")

    assert response.status_code == 204
    assert not Professional.objects.filter(id=professional.id).exists()


@pytest.mark.django_db
def test_accept_invite_serializer_creates_professional():
    tenant = Tenant.objects.create(name="Salon Epsilon", slug="salon-epsilon")
    owner = CustomUser.objects.create_user(
        username="owner-epsilon",
        email="owner-epsilon@example.com",
        password="pass123",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    collaborator = CustomUser.objects.create_user(
        username="collab-epsilon",
        email="collab-epsilon@example.com",
        password="pass123",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=collaborator,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.INVITED,
    )

    token = "test-token-123"
    staff.set_invite(token, timezone.now() + timedelta(days=7), invited_by=owner)

    serializer = StaffAcceptInviteSerializer(
        data={"token": token, "password": "StrongPass!9"}
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    professional = Professional.objects.get(staff_member=staff)
    assert professional.user == collaborator
    assert professional.is_active is True
