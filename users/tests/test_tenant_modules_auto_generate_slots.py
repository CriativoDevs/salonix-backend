"""
Testes do toggle `auto_generate_slots_enabled` em TenantModulesSettingsView
(BE-SLOTS-04, #559).
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant, TenantBusinessHours, TenantStaffMember

URL = "/api/users/tenant/modules/"


def _make_owner(slug):
    tenant = Tenant.objects.create(
        name=f"Salon {slug}",
        slug=slug,
        is_active=True,
        plan_tier=Tenant.PLAN_BASIC,
    )
    owner = CustomUser.objects.create_user(
        username=f"owner_{slug}",
        email=f"owner_{slug}@example.com",
        password="Pass123!",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return tenant, owner


@pytest.mark.django_db
class TestAutoGenerateSlotsToggle:
    def setup_method(self):
        self.client = APIClient()

    def test_enable_without_business_hours_returns_400(self):
        tenant, owner = _make_owner("mod-slots-nobh")
        self.client.force_authenticate(user=owner)
        resp = self.client.patch(
            URL, {"auto_generate_slots_enabled": True}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        tenant.refresh_from_db()
        assert tenant.auto_generate_slots_enabled is False

    def test_enable_with_business_hours_returns_200_and_persists(self):
        tenant, owner = _make_owner("mod-slots-ok")
        TenantBusinessHours.objects.create(
            tenant=tenant,
            day_of_week=0,
            start_time="09:00",
            end_time="12:00",
            is_active=True,
        )
        self.client.force_authenticate(user=owner)
        resp = self.client.patch(
            URL, {"auto_generate_slots_enabled": True}, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["auto_generate_slots_enabled"] is True
        tenant.refresh_from_db()
        assert tenant.auto_generate_slots_enabled is True

    def test_disable_has_no_business_hours_restriction(self):
        tenant, owner = _make_owner("mod-slots-disable")
        tenant.auto_generate_slots_enabled = True
        tenant.save(update_fields=["auto_generate_slots_enabled"])
        self.client.force_authenticate(user=owner)
        resp = self.client.patch(
            URL, {"auto_generate_slots_enabled": False}, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.auto_generate_slots_enabled is False

    def test_appears_in_tenant_meta_serializer(self):
        tenant, owner = _make_owner("mod-slots-meta")
        TenantBusinessHours.objects.create(
            tenant=tenant,
            day_of_week=0,
            start_time="09:00",
            end_time="12:00",
            is_active=True,
        )
        self.client.force_authenticate(user=owner)
        self.client.patch(URL, {"auto_generate_slots_enabled": True}, format="json")

        meta_resp = self.client.get(
            "/api/users/tenant/meta/", HTTP_X_TENANT_SLUG=tenant.slug
        )
        assert meta_resp.status_code == status.HTTP_200_OK
        assert meta_resp.data["auto_generate_slots_enabled"] is True
