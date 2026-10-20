import pytest
from datetime import date, datetime, time, timedelta
import zoneinfo

from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, CustomUser, TenantStaffMember
from core.models import Professional, ScheduleSlot

URL = "/api/slots/bulk-block/"

MONDAY = date(2026, 6, 1)  # segunda-feira
TZ = zoneinfo.ZoneInfo("Europe/Lisbon")


def _make_setup(slug):
    tenant = Tenant.objects.create(
        name=f"Salon {slug}", slug=slug, is_active=True, timezone="Europe/Lisbon"
    )
    owner = CustomUser.objects.create_user(
        username=f"owner_{slug}", email=f"owner_{slug}@example.com", password="Pass123!", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER, status=TenantStaffMember.Status.ACTIVE
    )
    prof_user = CustomUser.objects.create_user(
        username=f"prof_{slug}", email=f"prof_{slug}@example.com", password="Pass123!", tenant=tenant
    )
    staff = TenantStaffMember.objects.filter(tenant=tenant, user=owner).first()
    professional = Professional.objects.create(
        tenant=tenant, user=prof_user, staff_member=staff, name="Ana Lima", is_active=True
    )
    return tenant, owner, professional


def _dt(day, hhmm):
    h, m = hhmm.split(":")
    return datetime.combine(day, time(int(h), int(m))).replace(tzinfo=TZ)


@pytest.mark.django_db
class TestBulkBlockPermissions:
    def setup_method(self):
        self.client = APIClient()

    def test_unauthenticated_rejected(self):
        resp = self.client.post(URL, {}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_collaborator_rejected(self):
        tenant, _, professional = _make_setup("bb-perm-collab")
        collab = CustomUser.objects.create_user(
            username="collab_bb", email="collab_bb@x.com", password="Pass123!", tenant=tenant
        )
        TenantStaffMember.objects.create(
            tenant=tenant, user=collab, role=TenantStaffMember.Role.COLLABORATOR,
            status=TenantStaffMember.Status.ACTIVE
        )
        self.client.force_authenticate(user=collab)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "12:00",
        }, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_manager_allowed(self):
        tenant, _, professional = _make_setup("bb-perm-mgr")
        manager = CustomUser.objects.create_user(
            username="mgr_bb", email="mgr_bb@x.com", password="Pass123!", tenant=tenant
        )
        TenantStaffMember.objects.create(
            tenant=tenant, user=manager, role=TenantStaffMember.Role.MANAGER,
            status=TenantStaffMember.Status.ACTIVE
        )
        self.client.force_authenticate(user=manager)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "12:00",
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestBulkBlockValidation:
    def setup_method(self):
        self.client = APIClient()

    def test_missing_professional_id(self):
        _tenant, owner, _prof = _make_setup("bb-val-noprof")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "12:00",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_professional_from_other_tenant_rejected(self):
        tenant_a, owner_a, _prof_a = _make_setup("bb-val-iso-a")
        _tenant_b, _owner_b, prof_b = _make_setup("bb-val-iso-b")
        self.client.force_authenticate(user=owner_a)
        resp = self.client.post(URL, {
            "professional_id": prof_b.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "12:00",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_date_range(self):
        _tenant, owner, professional = _make_setup("bb-val-daterange")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY - timedelta(days=1)),
            "start_time": "09:00", "end_time": "12:00",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_time_range(self):
        _tenant, owner, professional = _make_setup("bb-val-timerange")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "12:00", "end_time": "09:00",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_interval_out_of_range(self):
        _tenant, owner, professional = _make_setup("bb-val-interval")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "12:00",
            "interval_minutes": 5,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_works_without_business_hours_configured(self):
        # Diferente do bulk_generate, bulk_block não exige TenantBusinessHours.
        _tenant, owner, professional = _make_setup("bb-val-nobh")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "10:00",
            "interval_minutes": 30,
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == 2


@pytest.mark.django_db
class TestBulkBlockBehaviour:
    def setup_method(self):
        self.client = APIClient()

    def test_creates_blocked_slots_when_none_exist(self):
        tenant, owner, professional = _make_setup("bb-create")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "11:00",
            "interval_minutes": 30,
            "reason": "Férias",
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == {"blocked": 0, "created": 4, "skipped_booked": 0}

        slots = ScheduleSlot.objects.filter(tenant=tenant, professional=professional).order_by("start_time")
        assert slots.count() == 4
        for slot in slots:
            assert slot.status == "blocked"
            assert slot.is_available is False
            assert slot.blocked_reason == "Férias"
        assert slots[0].start_time == _dt(MONDAY, "09:00")
        assert slots[0].end_time == _dt(MONDAY, "09:30")
        assert slots[3].end_time == _dt(MONDAY, "11:00")

    def test_blocks_existing_available_slots_covering_range(self):
        tenant, owner, professional = _make_setup("bb-block-existing")
        existing = ScheduleSlot.objects.create(
            tenant=tenant, professional=professional,
            start_time=_dt(MONDAY, "09:00"), end_time=_dt(MONDAY, "10:00"),
            is_available=True, status="available",
        )
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "10:00",
            "interval_minutes": 60,
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["blocked"] == 1
        assert resp.data["created"] == 0
        existing.refresh_from_db()
        assert existing.status == "blocked"
        assert existing.is_available is False

    def test_booked_slot_is_not_touched(self):
        tenant, owner, professional = _make_setup("bb-skip-booked")
        booked = ScheduleSlot.objects.create(
            tenant=tenant, professional=professional,
            start_time=_dt(MONDAY, "09:00"), end_time=_dt(MONDAY, "10:00"),
            is_available=False, status="booked",
        )
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "10:00",
            "interval_minutes": 60,
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["skipped_booked"] == 1
        assert resp.data["blocked"] == 0
        booked.refresh_from_db()
        assert booked.status == "booked"
        assert booked.is_available is False

    def test_mixed_booked_available_and_gap_in_same_range(self):
        tenant, owner, professional = _make_setup("bb-mixed")
        booked = ScheduleSlot.objects.create(
            tenant=tenant, professional=professional,
            start_time=_dt(MONDAY, "09:00"), end_time=_dt(MONDAY, "09:30"),
            is_available=False, status="booked",
        )
        available = ScheduleSlot.objects.create(
            tenant=tenant, professional=professional,
            start_time=_dt(MONDAY, "09:30"), end_time=_dt(MONDAY, "10:00"),
            is_available=True, status="available",
        )
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "11:00",
            "interval_minutes": 30,
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["skipped_booked"] == 1
        assert resp.data["blocked"] == 1
        assert resp.data["created"] == 2  # 10:00-10:30 e 10:30-11:00

        booked.refresh_from_db()
        available.refresh_from_db()
        assert booked.status == "booked"
        assert available.status == "blocked"
        created_slots = ScheduleSlot.objects.filter(
            tenant=tenant, professional=professional, start_time__gte=_dt(MONDAY, "10:00")
        )
        assert created_slots.count() == 2
        for slot in created_slots:
            assert slot.status == "blocked"

    def test_missing_professional_id_returns_400(self):
        _tenant, owner, _prof = _make_setup("bb-noprof2")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "10:00",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_tenant_isolation_does_not_touch_other_tenant_slot(self):
        tenant_a, owner_a, prof_a = _make_setup("bb-iso-a")
        tenant_b, _owner_b, prof_b = _make_setup("bb-iso-b")
        other_tenant_slot = ScheduleSlot.objects.create(
            tenant=tenant_b, professional=prof_b,
            start_time=_dt(MONDAY, "09:00"), end_time=_dt(MONDAY, "10:00"),
            is_available=True, status="available",
        )
        self.client.force_authenticate(user=owner_a)
        resp = self.client.post(URL, {
            "professional_id": prof_a.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "10:00",
            "interval_minutes": 60,
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        other_tenant_slot.refresh_from_db()
        assert other_tenant_slot.status == "available"
        assert ScheduleSlot.objects.filter(tenant=tenant_b).count() == 1

    def test_cross_tenant_professional_id_rejected(self):
        tenant_a, owner_a, _prof_a = _make_setup("bb-iso-cross-a")
        _tenant_b, _owner_b, prof_b = _make_setup("bb-iso-cross-b")
        self.client.force_authenticate(user=owner_a)
        resp = self.client.post(URL, {
            "professional_id": prof_b.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "10:00",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_blocked_slots_created_do_not_appear_in_public_slot_list(self):
        tenant, owner, professional = _make_setup("bb-public-hidden")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(MONDAY),
            "start_time": "09:00", "end_time": "10:00",
            "interval_minutes": 30,
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == 2

        public_resp = self.client.get(
            "/api/public/slots/",
            {"professional_id": professional.id, "tenant": tenant.slug},
        )
        assert public_resp.status_code == status.HTTP_200_OK
        assert public_resp.data == []

    def test_multi_day_range_blocks_each_day(self):
        tenant, owner, professional = _make_setup("bb-multiday")
        self.client.force_authenticate(user=owner)
        date_to = MONDAY + timedelta(days=2)
        resp = self.client.post(URL, {
            "professional_id": professional.id,
            "date_from": str(MONDAY), "date_to": str(date_to),
            "start_time": "09:00", "end_time": "10:00",
            "interval_minutes": 60,
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == 3
        assert ScheduleSlot.objects.filter(tenant=tenant, professional=professional).count() == 3
