"""Testes de POST /api/clients/me/appointments/{id}/apply-voucher/ (BE-VOUCHER-06).

Permite que o PRÓPRIO cliente (JWT scope=client) aplique um voucher já
atribuído a ele a um agendamento que seja dele mesmo. Reaproveita a
mesma lógica de validação de `core.views.SalonAppointmentViewSet.apply_voucher`
(BE-VOUCHER-03, #472), mas com permissão de cliente em vez de staff.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Appointment, Professional, SalonCustomer, Service, ScheduleSlot
from users.models import CustomUser, Tenant, TenantStaffMember
from vouchers.models import ClientVoucher, Voucher


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(
        name="Salão Apply Cliente",
        slug="salao-apply-cliente",
        plan_tier=Tenant.PLAN_BASIC,
        pwa_client_enabled=True,
    )


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        name="Outro Salão Apply Cliente",
        slug="outro-salao-apply-cliente",
        plan_tier=Tenant.PLAN_BASIC,
        pwa_client_enabled=True,
    )


@pytest.fixture
def owner(db, tenant):
    user = CustomUser.objects.create_user(
        username="owner-apply-cliente",
        password="pass",
        email="owner-apply-cliente@example.com",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def customer(db, tenant):
    customer = SalonCustomer.objects.create(
        tenant=tenant,
        name="Cliente Apply Voucher",
        email="cliente-apply-voucher@test.com",
    )
    customer.set_password("securepass123")
    customer.save()
    return customer


@pytest.fixture
def other_customer(db, tenant):
    """Outro cliente do MESMO tenant."""
    other = SalonCustomer.objects.create(
        tenant=tenant,
        name="Outro Cliente Apply Voucher",
        email="outro-cliente-apply-voucher@test.com",
    )
    other.set_password("securepass123")
    other.save()
    return other


@pytest.fixture
def appointment(db, tenant, owner, customer):
    service = Service.objects.create(
        tenant=tenant,
        user=owner,
        name="Corte",
        duration_minutes=30,
        price_eur="20.00",
    )
    prof = Professional.objects.create(
        tenant=tenant, user=owner, name="João", is_active=True
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
        client=owner,
        customer=customer,
        service=service,
        professional=prof,
        slot=slot,
    )


@pytest.fixture
def other_customer_appointment(db, tenant, owner, other_customer):
    """Agendamento de OUTRO cliente do mesmo tenant (não deve poder ser alvo)."""
    service = Service.objects.create(
        tenant=tenant,
        user=owner,
        name="Barba",
        duration_minutes=20,
        price_eur="10.00",
    )
    prof = Professional.objects.create(
        tenant=tenant, user=owner, name="Rui", is_active=True
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
    return Appointment.objects.create(
        tenant=tenant,
        client=owner,
        customer=other_customer,
        service=service,
        professional=prof,
        slot=slot,
    )


@pytest.fixture
def voucher(db, tenant):
    return Voucher.objects.create(
        tenant=tenant, code="CLIAPPL1", type=Voucher.VoucherType.PERCENT, value=10
    )


@pytest.fixture
def client_voucher(db, tenant, voucher, customer):
    return ClientVoucher.objects.create(tenant=tenant, voucher=voucher, client=customer)


def _login(tenant, customer):
    c = APIClient()
    resp = c.post(
        reverse("clients_login"),
        {
            "email": customer.email,
            "password": "securepass123",
            "tenant_slug": tenant.slug,
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    return c, resp.data["access"]


def auth_headers(access_token):
    return {"HTTP_AUTHORIZATION": f"Bearer {access_token}"}


def url(appointment):
    return f"/api/clients/me/appointments/{appointment.id}/apply-voucher/"


@pytest.mark.django_db
class TestClientApplyVoucher:
    def test_client_applies_own_voucher_to_own_appointment(
        self, tenant, customer, appointment, client_voucher
    ):
        c, token = _login(tenant, customer)
        resp = c.post(
            url(appointment),
            {"client_voucher_id": client_voucher.id},
            format="json",
            **auth_headers(token),
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["id"] == client_voucher.id
        assert data["status"] == "used"
        assert data["used_in_booking"] == appointment.id

        client_voucher.refresh_from_db()
        assert client_voucher.used_at is not None
        assert client_voucher.used_in_booking_id == appointment.id

    def test_client_cannot_apply_voucher_to_appointment_of_another_client(
        self, tenant, customer, other_customer_appointment, client_voucher
    ):
        c, token = _login(tenant, customer)
        resp = c.post(
            url(other_customer_appointment),
            {"client_voucher_id": client_voucher.id},
            format="json",
            **auth_headers(token),
        )
        # get_object_or_404 escopado a tenant+customer: agendamento de outro
        # cliente não é "encontrado" para este JWT.
        assert resp.status_code == status.HTTP_404_NOT_FOUND

        client_voucher.refresh_from_db()
        assert client_voucher.used_at is None

    def test_client_cannot_apply_voucher_assigned_to_another_client(
        self, tenant, customer, other_customer, appointment
    ):
        other_voucher = Voucher.objects.create(
            tenant=tenant, code="NOTYOURS", type=Voucher.VoucherType.FIXED, value=5
        )
        not_mine = ClientVoucher.objects.create(
            tenant=tenant, voucher=other_voucher, client=other_customer
        )

        c, token = _login(tenant, customer)
        resp = c.post(
            url(appointment),
            {"client_voucher_id": not_mine.id},
            format="json",
            **auth_headers(token),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

        not_mine.refresh_from_db()
        assert not_mine.used_at is None

    def test_client_cannot_apply_voucher_from_another_tenant(
        self, tenant, customer, appointment, other_tenant
    ):
        other_tenant_customer = SalonCustomer.objects.create(
            tenant=other_tenant, name="Cliente de Outro Tenant"
        )
        other_voucher = Voucher.objects.create(
            tenant=other_tenant,
            code="OTHERTEN",
            type=Voucher.VoucherType.FIXED,
            value=5,
        )
        other_client_voucher = ClientVoucher.objects.create(
            tenant=other_tenant, voucher=other_voucher, client=other_tenant_customer
        )

        c, token = _login(tenant, customer)
        resp = c.post(
            url(appointment),
            {"client_voucher_id": other_client_voucher.id},
            format="json",
            **auth_headers(token),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

        other_client_voucher.refresh_from_db()
        assert other_client_voucher.used_at is None

    def test_client_cannot_apply_already_used_voucher(
        self, tenant, customer, appointment, client_voucher
    ):
        client_voucher.used_at = timezone.now()
        client_voucher.save(update_fields=["used_at"])

        c, token = _login(tenant, customer)
        resp = c.post(
            url(appointment),
            {"client_voucher_id": client_voucher.id},
            format="json",
            **auth_headers(token),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_client_cannot_apply_expired_voucher(
        self, tenant, customer, appointment, client_voucher
    ):
        client_voucher.voucher.valid_until = timezone.localdate() - timedelta(days=1)
        client_voucher.voucher.save(update_fields=["valid_until"])

        c, token = _login(tenant, customer)
        resp = c.post(
            url(appointment),
            {"client_voucher_id": client_voucher.id},
            format="json",
            **auth_headers(token),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

        client_voucher.refresh_from_db()
        assert client_voucher.used_at is None

    def test_apply_voucher_nonexistent_client_voucher(
        self, tenant, customer, appointment
    ):
        c, token = _login(tenant, customer)
        resp = c.post(
            url(appointment),
            {"client_voucher_id": 999999},
            format="json",
            **auth_headers(token),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_apply_voucher_missing_field(self, tenant, customer, appointment):
        c, token = _login(tenant, customer)
        resp = c.post(url(appointment), {}, format="json", **auth_headers(token))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_apply_voucher_unauthenticated(self, appointment, client_voucher):
        c = APIClient()
        resp = c.post(
            url(appointment),
            {"client_voucher_id": client_voucher.id},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_apply_voucher_nonexistent_appointment(self, tenant, customer):
        c, token = _login(tenant, customer)
        resp = c.post(
            "/api/clients/me/appointments/999999/apply-voucher/",
            {"client_voucher_id": 1},
            format="json",
            **auth_headers(token),
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
