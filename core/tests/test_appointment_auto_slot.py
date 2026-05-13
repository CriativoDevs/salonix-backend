import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, CustomUser, TenantStaffMember
from core.models import Professional, Service, ScheduleSlot, Appointment

URL = "/api/appointments/"

FUTURE = timezone.now() + timedelta(days=1)
FUTURE_START = FUTURE.replace(minute=0, second=0, microsecond=0)
FUTURE_END = FUTURE_START + timedelta(hours=1)


def _make_setup(slug):
    tenant = Tenant.objects.create(name=f"Salon {slug}", slug=slug, is_active=True)
    owner = CustomUser.objects.create_user(
        username=f"owner_{slug}", email=f"owner_{slug}@example.com",
        password="Pass123!", tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner,
        role=TenantStaffMember.Role.OWNER, status=TenantStaffMember.Status.ACTIVE,
    )
    prof_user = CustomUser.objects.create_user(
        username=f"prof_{slug}", email=f"prof_{slug}@example.com",
        password="Pass123!", tenant=tenant,
    )
    prof_staff = TenantStaffMember.objects.create(
        tenant=tenant, user=prof_user,
        role=TenantStaffMember.Role.COLLABORATOR, status=TenantStaffMember.Status.ACTIVE,
    )
    professional = Professional.objects.create(
        tenant=tenant, user=prof_user, staff_member=prof_staff,
        name="Ana Lima", is_active=True,
    )
    service = Service.objects.create(
        tenant=tenant, user=owner, name="Corte", duration_minutes=60, price_eur="20.00",
    )
    return tenant, owner, professional, service


@pytest.mark.django_db
class TestAutoSlotCreation:
    def setup_method(self):
        self.client = APIClient()

    def test_auto_slot_creates_appointment_and_slot(self):
        tenant, owner, professional, service = _make_setup("as-basic")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional": professional.id,
            "service": service.id,
            "start_time": FUTURE_START.isoformat(),
            "end_time": FUTURE_END.isoformat(),
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert Appointment.objects.filter(tenant=tenant).count() == 1
        assert ScheduleSlot.objects.filter(tenant=tenant, professional=professional).count() == 1
        slot = ScheduleSlot.objects.get(tenant=tenant, professional=professional)
        assert slot.status == "booked"
        assert not slot.is_available

    def test_auto_slot_reuses_existing_available_slot(self):
        tenant, owner, professional, service = _make_setup("as-reuse")
        existing_slot = ScheduleSlot.objects.create(
            tenant=tenant, professional=professional,
            start_time=FUTURE_START, end_time=FUTURE_END,
            is_available=True, status="available",
        )
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional": professional.id,
            "service": service.id,
            "start_time": FUTURE_START.isoformat(),
            "end_time": FUTURE_END.isoformat(),
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert ScheduleSlot.objects.filter(tenant=tenant, professional=professional).count() == 1
        existing_slot.refresh_from_db()
        assert existing_slot.status == "booked"

    def test_traditional_slot_id_still_works(self):
        tenant, owner, professional, service = _make_setup("as-trad")
        slot = ScheduleSlot.objects.create(
            tenant=tenant, professional=professional,
            start_time=FUTURE_START, end_time=FUTURE_END,
            is_available=True, status="available",
        )
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional": professional.id,
            "service": service.id,
            "slot": slot.id,
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        slot.refresh_from_db()
        assert slot.status == "booked"


@pytest.mark.django_db
class TestAutoSlotValidation:
    def setup_method(self):
        self.client = APIClient()

    def test_missing_start_time_returns_error(self):
        _tenant, owner, professional, service = _make_setup("as-val-nostart")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional": professional.id,
            "service": service.id,
            "end_time": FUTURE_END.isoformat(),
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_end_time_returns_error(self):
        _tenant, owner, professional, service = _make_setup("as-val-noend")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional": professional.id,
            "service": service.id,
            "start_time": FUTURE_START.isoformat(),
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_end_before_start_returns_error(self):
        _tenant, owner, professional, service = _make_setup("as-val-endbeforestart")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional": professional.id,
            "service": service.id,
            "start_time": FUTURE_END.isoformat(),
            "end_time": FUTURE_START.isoformat(),
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_past_start_time_returns_error(self):
        _tenant, owner, professional, service = _make_setup("as-val-past")
        past = timezone.now() - timedelta(hours=1)
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional": professional.id,
            "service": service.id,
            "start_time": past.isoformat(),
            "end_time": (past + timedelta(hours=1)).isoformat(),
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_overlap_with_booked_slot_returns_error(self):
        tenant, owner, professional, service = _make_setup("as-val-overlap")
        ScheduleSlot.objects.create(
            tenant=tenant, professional=professional,
            start_time=FUTURE_START, end_time=FUTURE_END,
            is_available=False, status="booked",
        )
        self.client.force_authenticate(user=owner)
        # Tenta agendar no mesmo horário
        resp = self.client.post(URL, {
            "professional": professional.id,
            "service": service.id,
            "start_time": FUTURE_START.isoformat(),
            "end_time": FUTURE_END.isoformat(),
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_slot_no_times_returns_error(self):
        _tenant, owner, professional, service = _make_setup("as-val-nothing")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional": professional.id,
            "service": service.id,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
