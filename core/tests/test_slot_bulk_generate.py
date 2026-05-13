import pytest
from datetime import date, timedelta
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, CustomUser, TenantStaffMember, TenantBusinessHours
from core.models import Professional, ScheduleSlot

URL = "/api/slots/bulk-generate/"

MON = 0
TUE = 1
SAT = 5
SUN = 6

# Segunda-feira fixa para testes determinísticos
MONDAY = date(2026, 6, 1)  # segunda-feira


def _make_setup(slug):
    tenant = Tenant.objects.create(name=f"Salon {slug}", slug=slug, is_active=True, timezone="Europe/Lisbon")
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


def _add_bh(tenant, day, start="09:00", end="12:00"):
    TenantBusinessHours.objects.create(
        tenant=tenant, day_of_week=day, start_time=start, end_time=end, is_active=True
    )


@pytest.mark.django_db
class TestBulkGeneratePermissions:
    def setup_method(self):
        self.client = APIClient()

    def test_unauthenticated_rejected(self):
        resp = self.client.post(URL, {}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_collaborator_rejected(self):
        tenant, _, professional = _make_setup("bg-perm-collab")
        collab = CustomUser.objects.create_user(
            username="collab_bg", email="collab_bg@x.com", password="Pass123!", tenant=tenant
        )
        TenantStaffMember.objects.create(
            tenant=tenant, user=collab, role=TenantStaffMember.Role.COLLABORATOR,
            status=TenantStaffMember.Status.ACTIVE
        )
        _add_bh(tenant, MON)
        self.client.force_authenticate(user=collab)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "day", "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_manager_allowed(self):
        tenant, _, professional = _make_setup("bg-perm-mgr")
        manager = CustomUser.objects.create_user(
            username="mgr_bg", email="mgr_bg@x.com", password="Pass123!", tenant=tenant
        )
        TenantStaffMember.objects.create(
            tenant=tenant, user=manager, role=TenantStaffMember.Role.MANAGER,
            status=TenantStaffMember.Status.ACTIVE
        )
        _add_bh(tenant, MON)
        self.client.force_authenticate(user=manager)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "day", "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestBulkGenerateValidation:
    def setup_method(self):
        self.client = APIClient()

    def _auth(self, slug):
        tenant, owner, professional = _make_setup(slug)
        _add_bh(tenant, MON)
        self.client.force_authenticate(user=owner)
        return tenant, owner, professional

    def test_missing_professional_id(self):
        _tenant, owner, _prof = _make_setup("bg-val-noprof")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {"period": "day", "date": str(MONDAY)}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_period(self):
        _tenant, owner, professional = _make_setup("bg-val-period")
        _add_bh(_tenant, MON)
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "quarter", "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_interval_below_minimum(self):
        _tenant, owner, professional = _make_setup("bg-val-intlow")
        _add_bh(_tenant, MON)
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "day",
            "interval_minutes": 10, "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_interval_above_maximum(self):
        _tenant, owner, professional = _make_setup("bg-val-inthigh")
        _add_bh(_tenant, MON)
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "day",
            "interval_minutes": 600, "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_date_format(self):
        _tenant, owner, professional = _make_setup("bg-val-date")
        _add_bh(_tenant, MON)
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "day", "date": "01/06/2026"
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_professional_from_other_tenant_rejected(self):
        tenant_a, owner_a, _prof_a = _make_setup("bg-val-iso-a")
        tenant_b, _owner_b, prof_b = _make_setup("bg-val-iso-b")
        _add_bh(tenant_a, MON)
        self.client.force_authenticate(user=owner_a)
        resp = self.client.post(URL, {
            "professional_id": prof_b.id, "period": "day", "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_business_hours_returns_error(self):
        tenant, owner, professional = _make_setup("bg-val-nobh")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "day", "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestBulkGenerateDay:
    def setup_method(self):
        self.client = APIClient()

    def test_day_generates_correct_slots(self):
        # 09:00-12:00, 60 min → 3 slots: 09-10, 10-11, 11-12
        tenant, owner, professional = _make_setup("bg-day-basic")
        _add_bh(tenant, MON, "09:00", "12:00")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "day",
            "interval_minutes": 60, "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == 3
        assert resp.data["skipped"] == 0
        assert ScheduleSlot.objects.filter(tenant=tenant, professional=professional).count() == 3

    def test_day_with_30min_interval(self):
        # 09:00-11:00, 30 min → 4 slots
        tenant, owner, professional = _make_setup("bg-day-30")
        _add_bh(tenant, MON, "09:00", "11:00")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "day",
            "interval_minutes": 30, "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == 4

    def test_day_no_business_hours_for_that_weekday(self):
        # MONDAY tem 0 slots porque BH está só no domingo
        tenant, owner, professional = _make_setup("bg-day-noday")
        _add_bh(tenant, SUN, "09:00", "12:00")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "day",
            "interval_minutes": 60, "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == 0
        assert resp.data["skipped"] == 0

    def test_day_idempotent_skips_existing(self):
        tenant, owner, professional = _make_setup("bg-day-idem")
        _add_bh(tenant, MON, "09:00", "12:00")
        self.client.force_authenticate(user=owner)
        payload = {
            "professional_id": professional.id, "period": "day",
            "interval_minutes": 60, "date": str(MONDAY)
        }
        resp1 = self.client.post(URL, payload, format="json")
        assert resp1.data["created"] == 3
        resp2 = self.client.post(URL, payload, format="json")
        assert resp2.data["created"] == 0
        assert resp2.data["skipped"] == 3
        assert ScheduleSlot.objects.filter(tenant=tenant, professional=professional).count() == 3


@pytest.mark.django_db
class TestBulkGenerateWeek:
    def setup_method(self):
        self.client = APIClient()

    def test_week_generates_slots_for_active_days(self):
        # Semana de 2026-06-01 (seg) a 2026-06-07 (dom)
        # BH: seg (09-12, 3 slots 60min) e sab (10-12, 2 slots 60min)
        tenant, owner, professional = _make_setup("bg-week-basic")
        _add_bh(tenant, MON, "09:00", "12:00")
        _add_bh(tenant, SAT, "10:00", "12:00")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "week",
            "interval_minutes": 60, "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == 5  # 3 + 2

    def test_week_correct_date_range_from_any_day(self):
        # Passar quarta-feira da mesma semana deve gerar a mesma semana toda
        tenant, owner, professional = _make_setup("bg-week-mid")
        _add_bh(tenant, MON, "09:00", "10:00")  # 1 slot
        wednesday = MONDAY + timedelta(days=2)
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "week",
            "interval_minutes": 60, "date": str(wednesday)
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == 1

    def test_week_idempotent(self):
        tenant, owner, professional = _make_setup("bg-week-idem")
        _add_bh(tenant, MON, "09:00", "11:00")
        self.client.force_authenticate(user=owner)
        payload = {
            "professional_id": professional.id, "period": "week",
            "interval_minutes": 60, "date": str(MONDAY)
        }
        resp1 = self.client.post(URL, payload, format="json")
        created = resp1.data["created"]
        resp2 = self.client.post(URL, payload, format="json")
        assert resp2.data["created"] == 0
        assert resp2.data["skipped"] == created


@pytest.mark.django_db
class TestBulkGenerateMonth:
    def setup_method(self):
        self.client = APIClient()

    def test_month_generates_slots_for_all_active_mondays(self):
        # Junho 2026: segundas = 1, 8, 15, 22, 29 → 5 segundas
        # BH: seg 09:00-10:00, 60min → 1 slot por segunda = 5 slots
        tenant, owner, professional = _make_setup("bg-month-mon")
        _add_bh(tenant, MON, "09:00", "10:00")
        self.client.force_authenticate(user=owner)
        resp = self.client.post(URL, {
            "professional_id": professional.id, "period": "month",
            "interval_minutes": 60, "date": str(MONDAY)
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == 5

    def test_month_idempotent(self):
        tenant, owner, professional = _make_setup("bg-month-idem")
        _add_bh(tenant, MON, "09:00", "10:00")
        self.client.force_authenticate(user=owner)
        payload = {
            "professional_id": professional.id, "period": "month",
            "interval_minutes": 60, "date": str(MONDAY)
        }
        resp1 = self.client.post(URL, payload, format="json")
        created = resp1.data["created"]
        resp2 = self.client.post(URL, payload, format="json")
        assert resp2.data["skipped"] == created
        assert resp2.data["created"] == 0

    def test_month_isolated_between_tenants(self):
        tenant_a, owner_a, prof_a = _make_setup("bg-month-iso-a")
        tenant_b, _owner_b, prof_b = _make_setup("bg-month-iso-b")
        _add_bh(tenant_a, MON, "09:00", "10:00")
        _add_bh(tenant_b, MON, "09:00", "10:00")
        self.client.force_authenticate(user=owner_a)
        self.client.post(URL, {
            "professional_id": prof_a.id, "period": "month",
            "interval_minutes": 60, "date": str(MONDAY)
        }, format="json")
        assert ScheduleSlot.objects.filter(tenant=tenant_b).count() == 0
