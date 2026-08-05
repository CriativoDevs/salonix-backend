from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Appointment, Professional, SalonCustomer, Service, ScheduleSlot
from users.models import CustomUser, Tenant, TenantStaffMember
from vouchers.models import ClientVoucher, Voucher


def auth_client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Salon Voucher", slug="salon-voucher")


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name="Salon Voucher B", slug="salon-voucher-b")


@pytest.fixture
def salon_owner(db, tenant):
    user = CustomUser.objects.create_user(
        username="owner-av", password="pass", email="owner-av@example.com", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def other_owner(db, other_tenant):
    user = CustomUser.objects.create_user(
        username="owner-av-2",
        password="pass",
        email="owner-av-2@example.com",
        tenant=other_tenant,
    )
    TenantStaffMember.objects.create(
        tenant=other_tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def client_user(db, tenant):
    return CustomUser.objects.create_user(
        username="client-av", password="pass", email="client-av@example.com", tenant=tenant
    )


@pytest.fixture
def customer(db, tenant):
    return SalonCustomer.objects.create(tenant=tenant, name="Cliente Voucher")


@pytest.fixture
def other_customer(db, tenant):
    return SalonCustomer.objects.create(tenant=tenant, name="Outro Cliente")


@pytest.fixture
def appointment(db, tenant, salon_owner, client_user, customer):
    service = Service.objects.create(
        tenant=tenant,
        user=salon_owner,
        name="Corte",
        duration_minutes=30,
        price_eur="20.00",
    )
    prof = Professional.objects.create(
        tenant=tenant, user=salon_owner, name="João", is_active=True
    )
    now = timezone.now()
    slot = ScheduleSlot.objects.create(
        tenant=tenant,
        professional=prof,
        start_time=now + timedelta(days=1, hours=1),
        end_time=now + timedelta(days=1, hours=1, minutes=30),
        is_available=True,
        status="available",
    )
    slot.mark_booked()
    return Appointment.objects.create(
        tenant=tenant,
        client=client_user,
        customer=customer,
        service=service,
        professional=prof,
        slot=slot,
    )


@pytest.fixture
def voucher(db, tenant):
    return Voucher.objects.create(
        tenant=tenant, code="APPLYME1", type=Voucher.VoucherType.PERCENT, value=10
    )


@pytest.fixture
def client_voucher(db, tenant, voucher, customer):
    return ClientVoucher.objects.create(tenant=tenant, voucher=voucher, client=customer)


def url(appointment):
    return f"/api/salon/appointments/{appointment.id}/apply-voucher/"


@pytest.mark.django_db
class TestApplyVoucher:
    def test_apply_valid_voucher(self, appointment, client_voucher, salon_owner):
        c = auth_client(salon_owner)
        resp = c.post(
            url(appointment), {"client_voucher_id": client_voucher.id}, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["id"] == client_voucher.id
        assert data["voucher_code"] == client_voucher.voucher.code
        assert data["voucher_type"] == client_voucher.voucher.type
        assert data["status"] == "used"
        assert data["used_in_booking"] == appointment.id

        client_voucher.refresh_from_db()
        assert client_voucher.used_at is not None
        assert client_voucher.used_in_booking_id == appointment.id

    def test_apply_already_used_voucher(self, appointment, client_voucher, salon_owner):
        client_voucher.used_at = timezone.now()
        client_voucher.save(update_fields=["used_at"])

        c = auth_client(salon_owner)
        resp = c.post(
            url(appointment), {"client_voucher_id": client_voucher.id}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "client_voucher_id" in resp.data["error"]["details"]

    def test_apply_expired_voucher(self, appointment, client_voucher, salon_owner):
        client_voucher.voucher.valid_until = timezone.localdate() - timedelta(days=1)
        client_voucher.voucher.save(update_fields=["valid_until"])

        c = auth_client(salon_owner)
        resp = c.post(
            url(appointment), {"client_voucher_id": client_voucher.id}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "client_voucher_id" in resp.data["error"]["details"]

        client_voucher.refresh_from_db()
        assert client_voucher.used_at is None

    def test_apply_voucher_from_other_tenant(
        self, appointment, other_tenant, salon_owner
    ):
        other_customer_b = SalonCustomer.objects.create(
            tenant=other_tenant, name="Cliente B"
        )
        other_voucher = Voucher.objects.create(
            tenant=other_tenant,
            code="OTHERTEN",
            type=Voucher.VoucherType.FIXED,
            value=5,
        )
        other_client_voucher = ClientVoucher.objects.create(
            tenant=other_tenant, voucher=other_voucher, client=other_customer_b
        )

        c = auth_client(salon_owner)
        resp = c.post(
            url(appointment),
            {"client_voucher_id": other_client_voucher.id},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "client_voucher_id" in resp.data["error"]["details"]

        other_client_voucher.refresh_from_db()
        assert other_client_voucher.used_at is None

    def test_apply_voucher_not_assigned_to_appointment_client(
        self, appointment, tenant, voucher, other_customer, salon_owner
    ):
        not_assigned = ClientVoucher.objects.create(
            tenant=tenant, voucher=voucher, client=other_customer
        )

        c = auth_client(salon_owner)
        resp = c.post(
            url(appointment), {"client_voucher_id": not_assigned.id}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "client_voucher_id" in resp.data["error"]["details"]

        not_assigned.refresh_from_db()
        assert not_assigned.used_at is None

    def test_apply_voucher_nonexistent_client_voucher(self, appointment, salon_owner):
        c = auth_client(salon_owner)
        resp = c.post(
            url(appointment), {"client_voucher_id": 999999}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "client_voucher_id" in resp.data["error"]["details"]

    def test_apply_voucher_missing_field(self, appointment, salon_owner):
        c = auth_client(salon_owner)
        resp = c.post(url(appointment), {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_apply_voucher_unauthenticated(self, appointment, client_voucher):
        c = APIClient()
        resp = c.post(
            url(appointment), {"client_voucher_id": client_voucher.id}, format="json"
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_apply_voucher_forbidden_for_other_salon(
        self, appointment, client_voucher, other_owner
    ):
        c = auth_client(other_owner)
        resp = c.post(
            url(appointment), {"client_voucher_id": client_voucher.id}, format="json"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

        client_voucher.refresh_from_db()
        assert client_voucher.used_at is None

    def test_apply_voucher_without_customer_link(
        self, tenant, salon_owner, client_user, client_voucher
    ):
        service = Service.objects.create(
            tenant=tenant,
            user=salon_owner,
            name="Barba",
            duration_minutes=20,
            price_eur="10.00",
        )
        prof = Professional.objects.create(
            tenant=tenant, user=salon_owner, name="Rui", is_active=True
        )
        now = timezone.now()
        slot = ScheduleSlot.objects.create(
            tenant=tenant,
            professional=prof,
            start_time=now + timedelta(days=2, hours=1),
            end_time=now + timedelta(days=2, hours=1, minutes=20),
            is_available=True,
            status="available",
        )
        slot.mark_booked()
        appt_no_customer = Appointment.objects.create(
            tenant=tenant,
            client=client_user,
            customer=None,
            service=service,
            professional=prof,
            slot=slot,
        )

        c = auth_client(salon_owner)
        resp = c.post(
            url(appt_no_customer),
            {"client_voucher_id": client_voucher.id},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "client_voucher_id" in resp.data["error"]["details"]
