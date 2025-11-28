import pytest
from django.urls import reverse
from django.test.utils import override_settings
from django.core.cache import cache
from rest_framework.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant, TenantStaffMember
from users.serializers import StaffContactUpdateSerializer


@pytest.mark.django_db
def test_access_link_requires_member_id():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner",
        email="owner@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("tenant_staff_access_link")
    response = client.post(url, {}, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    details = (response.data.get("error") or {}).get("details") or {}
    assert "id" in details


@pytest.mark.django_db
def test_access_link_denies_non_owner_manager():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    collab_user = CustomUser.objects.create_user(
        username="collab",
        email="collab@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=collab_user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )

    # Autenticar como colaborador tentando enviar link para si mesmo
    client = APIClient()
    client.force_authenticate(user=collab_user)
    url = reverse("tenant_staff_access_link")
    response = client.post(url, {"id": staff.id}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_access_link_blocks_owner_and_disabled():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner2",
        email="owner2@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    owner_staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    manager = CustomUser.objects.create_user(
        username="manager",
        email="manager@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=manager,
        role=TenantStaffMember.Role.MANAGER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    disabled_user = CustomUser.objects.create_user(
        username="disabled",
        email="disabled@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    disabled_staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=disabled_user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.DISABLED,
    )

    client = APIClient()
    client.force_authenticate(user=manager)
    url = reverse("tenant_staff_access_link")

    r1 = client.post(url, {"id": owner_staff.id}, format="json")
    assert r1.status_code == status.HTTP_400_BAD_REQUEST
    assert "Owner" in (
        r1.data.get("detail") or r1.data.get("error", {}).get("message", "")
    )

    r2 = client.post(url, {"id": disabled_staff.id}, format="json")
    assert r2.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        "desativado"
        in (
            r2.data.get("detail") or r2.data.get("error", {}).get("message", "")
        ).lower()
    )


@pytest.mark.django_db
def test_access_link_success_sends_email(monkeypatch):
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner3",
        email="owner3@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    collab_user = CustomUser.objects.create_user(
        username="collab3",
        email="collab3@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=collab_user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )

    # Evitar envio real de e-mail
    monkeypatch.setattr(
        "core.email_utils.send_staff_access_link_email",
        lambda to_email, access_url, salon_name: True,
        raising=True,
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("tenant_staff_access_link")
    response = client.post(url, {"id": staff.id}, format="json")
    assert response.status_code == status.HTTP_200_OK
    assert response.data.get("access_link_sent") is True


@pytest.mark.django_db
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "users-throttle-access-link",
        }
    },
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.UserRateThrottle",
            "rest_framework.throttling.ScopedRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "user": "1000/day",
            "users_password_reset": "2/min",
        },
    },
)
def test_access_link_is_throttled(monkeypatch):
    cache.clear()
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    owner = CustomUser.objects.create_user(
        username="owner_thr",
        email="owner_thr@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )

    collab_user = CustomUser.objects.create_user(
        username="collab_thr",
        email="collab_thr@salon.local",
        password="pass12345",
        tenant=tenant,
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant,
        user=collab_user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )

    # evitar envio real
    monkeypatch.setattr(
        "core.email_utils.send_staff_access_link_email",
        lambda to_email, access_url, salon_name: True,
        raising=True,
    )

    c = APIClient()
    c.force_authenticate(owner)
    url = reverse("tenant_staff_access_link")

    r1 = c.post(url, {"id": staff.id}, format="json")
    r2 = c.post(url, {"id": staff.id}, format="json")
    assert r1.status_code == status.HTTP_200_OK
    assert r2.status_code == status.HTTP_200_OK
    r3 = c.post(url, {"id": staff.id}, format="json")
    assert r3.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
def test_staff_contact_update_serializer_blocks_duplicate_email():
    tenant = Tenant.objects.create(name="Salon", slug="salon")
    CustomUser.objects.create_user(
        username="u1", email="a@e.com", password="x", tenant=tenant
    )
    u2 = CustomUser.objects.create_user(
        username="u2", email="b@e.com", password="x", tenant=tenant
    )
    s2 = TenantStaffMember.objects.create(
        tenant=tenant,
        user=u2,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )
    ser = StaffContactUpdateSerializer(instance=s2, data={"email": "a@e.com"})
    with pytest.raises(ValidationError):
        ser.is_valid(raise_exception=True)
