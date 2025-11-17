import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from users.models import CustomUser, Tenant, TenantStaffMember
from users.serializers import StaffUpdateSerializer, StaffAcceptInviteSerializer
from core.models import Professional


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
