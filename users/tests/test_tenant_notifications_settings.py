import pytest
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, CustomUser, TenantStaffMember

URL = "/api/users/tenant/notifications/"


def _make_tenant_user(slug, role, **tenant_kwargs):
    tenant = Tenant.objects.create(
        name=f"Salon {slug}", slug=slug, is_active=True, **tenant_kwargs
    )
    user = CustomUser.objects.create_user(
        username=f"user_{slug}",
        email=f"user_{slug}@example.com",
        password="Pass123!",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=role,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return tenant, user


@pytest.mark.django_db
class TestTenantNotificationsSettingsGet:
    def setup_method(self):
        self.client = APIClient()

    def test_get_returns_current_settings(self):
        tenant, owner = _make_tenant_user(
            "notif-get-owner",
            TenantStaffMember.Role.OWNER,
            sms_enabled=True,
            whatsapp_enabled=False,
            push_mobile_enabled=True,
            push_web_enabled=False,
        )
        self.client.force_authenticate(user=owner)
        resp = self.client.get(URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == {
            "sms_enabled": True,
            "whatsapp_enabled": False,
            "push_mobile_enabled": True,
            "push_web_enabled": False,
        }

    def test_get_requires_authentication(self):
        resp = self.client.get(URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_isolated_between_tenants(self):
        tenant_a, owner_a = _make_tenant_user(
            "notif-iso-a",
            TenantStaffMember.Role.OWNER,
            sms_enabled=True,
            whatsapp_enabled=True,
        )
        tenant_b, owner_b = _make_tenant_user(
            "notif-iso-b",
            TenantStaffMember.Role.OWNER,
            sms_enabled=False,
            whatsapp_enabled=False,
        )
        self.client.force_authenticate(user=owner_b)
        resp = self.client.get(URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["sms_enabled"] is False
        assert resp.data["whatsapp_enabled"] is False
