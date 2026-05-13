import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, CustomUser, TenantStaffMember, TenantBusinessHours

URL = "/api/users/tenant/business-hours/"

VALID_SCHEDULE = [
    {"day_of_week": 0, "start_time": "09:00:00", "end_time": "18:00:00", "is_active": True},
    {"day_of_week": 1, "start_time": "09:00:00", "end_time": "18:00:00", "is_active": True},
    {"day_of_week": 5, "start_time": "10:00:00", "end_time": "16:00:00", "is_active": True},
    {"day_of_week": 6, "start_time": "10:00:00", "end_time": "14:00:00", "is_active": False},
]


def _make_tenant_user(slug, role):
    tenant = Tenant.objects.create(name=f"Salon {slug}", slug=slug, is_active=True)
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
class TestTenantBusinessHoursGet:
    def setup_method(self):
        self.client = APIClient()

    def test_get_empty_returns_empty_list(self):
        tenant, owner = _make_tenant_user("bh-get-empty", TenantStaffMember.Role.OWNER)
        self.client.force_authenticate(user=owner)
        resp = self.client.get(URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_get_returns_configured_hours(self):
        tenant, owner = _make_tenant_user("bh-get-full", TenantStaffMember.Role.OWNER)
        TenantBusinessHours.objects.create(
            tenant=tenant, day_of_week=0, start_time="09:00", end_time="18:00", is_active=True
        )
        TenantBusinessHours.objects.create(
            tenant=tenant, day_of_week=5, start_time="10:00", end_time="16:00", is_active=False
        )
        self.client.force_authenticate(user=owner)
        resp = self.client.get(URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 2
        days = [item["day_of_week"] for item in resp.data]
        assert days == sorted(days)

    def test_get_requires_authentication(self):
        resp = self.client.get(URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_isolated_between_tenants(self):
        tenant_a, owner_a = _make_tenant_user("bh-iso-a", TenantStaffMember.Role.OWNER)
        tenant_b, owner_b = _make_tenant_user("bh-iso-b", TenantStaffMember.Role.OWNER)
        TenantBusinessHours.objects.create(
            tenant=tenant_a, day_of_week=0, start_time="09:00", end_time="18:00"
        )
        self.client.force_authenticate(user=owner_b)
        resp = self.client.get(URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []


@pytest.mark.django_db
class TestTenantBusinessHoursPut:
    def setup_method(self):
        self.client = APIClient()

    def test_owner_can_set_schedule(self):
        tenant, owner = _make_tenant_user("bh-put-owner", TenantStaffMember.Role.OWNER)
        self.client.force_authenticate(user=owner)
        resp = self.client.put(URL, data=VALID_SCHEDULE, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 4
        assert TenantBusinessHours.objects.filter(tenant=tenant).count() == 4

    def test_manager_can_set_schedule(self):
        tenant, manager = _make_tenant_user("bh-put-mgr", TenantStaffMember.Role.MANAGER)
        self.client.force_authenticate(user=manager)
        resp = self.client.put(URL, data=VALID_SCHEDULE, format="json")
        assert resp.status_code == status.HTTP_200_OK

    def test_collaborator_cannot_set_schedule(self):
        _tenant, collab = _make_tenant_user("bh-put-collab", TenantStaffMember.Role.COLLABORATOR)
        self.client.force_authenticate(user=collab)
        resp = self.client.put(URL, data=VALID_SCHEDULE, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_put_requires_authentication(self):
        resp = self.client.put(URL, data=VALID_SCHEDULE, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_put_replaces_existing_schedule(self):
        tenant, owner = _make_tenant_user("bh-put-replace", TenantStaffMember.Role.OWNER)
        TenantBusinessHours.objects.create(
            tenant=tenant, day_of_week=2, start_time="08:00", end_time="17:00"
        )
        self.client.force_authenticate(user=owner)
        new_schedule = [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "18:00:00", "is_active": True},
        ]
        resp = self.client.put(URL, data=new_schedule, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert TenantBusinessHours.objects.filter(tenant=tenant).count() == 1
        assert TenantBusinessHours.objects.filter(tenant=tenant, day_of_week=0).exists()
        assert not TenantBusinessHours.objects.filter(tenant=tenant, day_of_week=2).exists()

    def test_put_empty_list_clears_schedule(self):
        tenant, owner = _make_tenant_user("bh-put-clear", TenantStaffMember.Role.OWNER)
        TenantBusinessHours.objects.create(
            tenant=tenant, day_of_week=0, start_time="09:00", end_time="18:00"
        )
        self.client.force_authenticate(user=owner)
        resp = self.client.put(URL, data=[], format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert TenantBusinessHours.objects.filter(tenant=tenant).count() == 0

    def test_validation_end_time_before_start_time(self):
        _tenant, owner = _make_tenant_user("bh-val-time", TenantStaffMember.Role.OWNER)
        self.client.force_authenticate(user=owner)
        invalid = [{"day_of_week": 0, "start_time": "18:00:00", "end_time": "09:00:00", "is_active": True}]
        resp = self.client.put(URL, data=invalid, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_validation_end_time_equal_start_time(self):
        _tenant, owner = _make_tenant_user("bh-val-eq", TenantStaffMember.Role.OWNER)
        self.client.force_authenticate(user=owner)
        invalid = [{"day_of_week": 0, "start_time": "09:00:00", "end_time": "09:00:00", "is_active": True}]
        resp = self.client.put(URL, data=invalid, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_validation_duplicate_days_rejected(self):
        _tenant, owner = _make_tenant_user("bh-val-dup", TenantStaffMember.Role.OWNER)
        self.client.force_authenticate(user=owner)
        duplicate = [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "18:00:00", "is_active": True},
            {"day_of_week": 0, "start_time": "10:00:00", "end_time": "17:00:00", "is_active": True},
        ]
        resp = self.client.put(URL, data=duplicate, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_validation_invalid_day_of_week(self):
        _tenant, owner = _make_tenant_user("bh-val-day", TenantStaffMember.Role.OWNER)
        self.client.force_authenticate(user=owner)
        invalid = [{"day_of_week": 7, "start_time": "09:00:00", "end_time": "18:00:00", "is_active": True}]
        resp = self.client.put(URL, data=invalid, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_put_not_a_list_rejected(self):
        _tenant, owner = _make_tenant_user("bh-val-list", TenantStaffMember.Role.OWNER)
        self.client.force_authenticate(user=owner)
        resp = self.client.put(URL, data={"day_of_week": 0}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_put_isolated_between_tenants(self):
        tenant_a, owner_a = _make_tenant_user("bh-iso-put-a", TenantStaffMember.Role.OWNER)
        tenant_b, owner_b = _make_tenant_user("bh-iso-put-b", TenantStaffMember.Role.OWNER)
        self.client.force_authenticate(user=owner_a)
        self.client.put(URL, data=VALID_SCHEDULE, format="json")
        assert TenantBusinessHours.objects.filter(tenant=tenant_b).count() == 0
