import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, CustomUser, TenantStaffMember
from core.models import Professional, ScheduleSlot


def _make_setup(slug):
    tenant = Tenant.objects.create(name=f"Salon {slug}", slug=slug, is_active=True)
    owner = CustomUser.objects.create_user(
        username=f"owner_{slug}", email=f"owner_{slug}@example.com", password="Pass123!", tenant=tenant
    )
    staff = TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER, status=TenantStaffMember.Status.ACTIVE
    )
    prof_user = CustomUser.objects.create_user(
        username=f"prof_{slug}", email=f"prof_{slug}@example.com", password="Pass123!", tenant=tenant
    )
    professional = Professional.objects.create(
        tenant=tenant, user=prof_user, staff_member=staff, name="Ana Lima", is_active=True
    )
    return tenant, owner, professional


def _make_slot(tenant, professional, status_="available", is_available=True):
    now = timezone.now()
    return ScheduleSlot.objects.create(
        tenant=tenant,
        professional=professional,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, minutes=30),
        is_available=is_available,
        status=status_,
    )


@pytest.mark.django_db
class TestSlotBlock:
    def setup_method(self):
        self.client = APIClient()

    def test_block_available_slot(self):
        tenant, owner, professional = _make_setup("block-ok")
        slot = _make_slot(tenant, professional)
        self.client.force_authenticate(user=owner)

        resp = self.client.post(
            f"/api/slots/{slot.id}/block/", {"reason": "Manutenção"}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK
        slot.refresh_from_db()
        assert slot.status == "blocked"
        assert slot.is_available is False
        assert slot.blocked_reason == "Manutenção"

    def test_block_without_reason(self):
        tenant, owner, professional = _make_setup("block-noreason")
        slot = _make_slot(tenant, professional)
        self.client.force_authenticate(user=owner)

        resp = self.client.post(f"/api/slots/{slot.id}/block/", {}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        slot.refresh_from_db()
        assert slot.status == "blocked"
        assert slot.blocked_reason == ""

    def test_block_booked_slot_rejected(self):
        tenant, owner, professional = _make_setup("block-booked")
        slot = _make_slot(tenant, professional, status_="booked", is_available=False)
        self.client.force_authenticate(user=owner)

        resp = self.client.post(f"/api/slots/{slot.id}/block/", {}, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        slot.refresh_from_db()
        assert slot.status == "booked"
        assert slot.is_available is False

    def test_unblock_blocked_slot(self):
        tenant, owner, professional = _make_setup("unblock-ok")
        slot = _make_slot(tenant, professional, status_="blocked", is_available=False)
        self.client.force_authenticate(user=owner)

        resp = self.client.post(f"/api/slots/{slot.id}/unblock/", {}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        slot.refresh_from_db()
        assert slot.status == "available"
        assert slot.is_available is True

    def test_unblock_non_blocked_slot_rejected(self):
        tenant, owner, professional = _make_setup("unblock-notblocked")
        slot = _make_slot(tenant, professional)
        self.client.force_authenticate(user=owner)

        resp = self.client.post(f"/api/slots/{slot.id}/unblock/", {}, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        slot.refresh_from_db()
        assert slot.status == "available"

    def test_collaborator_cannot_block_other_professional_slot(self):
        tenant, _owner, professional = _make_setup("block-collab-other")
        collab_user = CustomUser.objects.create_user(
            username="collab_block", email="collab_block@example.com", password="Pass123!", tenant=tenant
        )
        TenantStaffMember.objects.create(
            tenant=tenant, user=collab_user, role=TenantStaffMember.Role.COLLABORATOR,
            status=TenantStaffMember.Status.ACTIVE,
        )
        slot = _make_slot(tenant, professional)
        self.client.force_authenticate(user=collab_user)

        resp = self.client.post(f"/api/slots/{slot.id}/block/", {}, format="json")

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        slot.refresh_from_db()
        assert slot.status == "available"

    def test_collaborator_can_block_own_slot(self):
        tenant, _owner, professional = _make_setup("block-collab-own")
        collab_user = CustomUser.objects.create_user(
            username="collab_own", email="collab_own@example.com", password="Pass123!", tenant=tenant
        )
        collab_staff = TenantStaffMember.objects.create(
            tenant=tenant, user=collab_user, role=TenantStaffMember.Role.COLLABORATOR,
            status=TenantStaffMember.Status.ACTIVE,
        )
        professional.staff_member = collab_staff
        professional.save(update_fields=["staff_member"])
        slot = _make_slot(tenant, professional)
        self.client.force_authenticate(user=collab_user)

        resp = self.client.post(f"/api/slots/{slot.id}/block/", {}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        slot.refresh_from_db()
        assert slot.status == "blocked"

    def test_block_cross_tenant_slot_is_forbidden(self):
        tenant_a, owner_a, _prof_a = _make_setup("block-tenant-a")
        _tenant_b, _owner_b, professional_b = _make_setup("block-tenant-b")
        slot = _make_slot(_tenant_b, professional_b)
        self.client.force_authenticate(user=owner_a)

        resp = self.client.post(f"/api/slots/{slot.id}/block/", {}, format="json")

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        slot.refresh_from_db()
        assert slot.status == "available"

    def test_unblock_cross_tenant_slot_is_forbidden(self):
        tenant_a, owner_a, _prof_a = _make_setup("unblock-tenant-a")
        _tenant_b, _owner_b, professional_b = _make_setup("unblock-tenant-b")
        slot = _make_slot(_tenant_b, professional_b, status_="blocked", is_available=False)
        self.client.force_authenticate(user=owner_a)

        resp = self.client.post(f"/api/slots/{slot.id}/unblock/", {}, format="json")

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        slot.refresh_from_db()
        assert slot.status == "blocked"

    def test_blocked_slot_not_in_public_slot_list(self):
        tenant, _owner, professional = _make_setup("block-public-hidden")
        slot = _make_slot(tenant, professional, status_="blocked", is_available=False)

        resp = self.client.get(
            "/api/public/slots/",
            {"professional_id": professional.id, "tenant": tenant.slug},
        )

        assert resp.status_code == status.HTTP_200_OK
        returned_ids = [item["id"] for item in resp.data]
        assert slot.id not in returned_ids
