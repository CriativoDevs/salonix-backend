"""Testes de GET /api/clients/me/vouchers/ (BE-VOUCHER-06).

Lista os `ClientVoucher` do próprio cliente autenticado via JWT
`scope=client` (ver `_get_client_from_jwt`). Isolamento por
tenant+cliente: nunca deve expor vouchers de outro cliente/tenant.
"""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import SalonCustomer
from users.models import Tenant
from vouchers.models import ClientVoucher, Voucher


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(
        name="Salão Vouchers Cliente",
        slug="salao-vouchers-cliente",
        plan_tier=Tenant.PLAN_BASIC,
        pwa_client_enabled=True,
    )


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        name="Outro Salão Vouchers Cliente",
        slug="outro-salao-vouchers-cliente",
        plan_tier=Tenant.PLAN_BASIC,
        pwa_client_enabled=True,
    )


@pytest.fixture
def customer(db, tenant):
    customer = SalonCustomer.objects.create(
        tenant=tenant,
        name="Cliente com Vouchers",
        email="cliente-vouchers@test.com",
    )
    customer.set_password("securepass123")
    customer.save()
    return customer


@pytest.fixture
def other_customer(db, tenant):
    """Outro cliente do MESMO tenant (para testar isolamento entre clientes)."""
    return SalonCustomer.objects.create(
        tenant=tenant, name="Outro Cliente do Mesmo Salão"
    )


@pytest.fixture
def other_tenant_customer(db, other_tenant):
    return SalonCustomer.objects.create(
        tenant=other_tenant, name="Cliente de Outro Tenant"
    )


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


@pytest.mark.django_db
class TestClientMeVouchersList:
    def test_client_can_list_own_vouchers(self, tenant, customer):
        voucher = Voucher.objects.create(
            tenant=tenant, code="MEACTIVE", type=Voucher.VoucherType.PERCENT, value=15
        )
        ClientVoucher.objects.create(tenant=tenant, voucher=voucher, client=customer)

        c, token = _login(tenant, customer)
        resp = c.get("/api/clients/me/vouchers/", **auth_headers(token))

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data) == 1
        assert data[0]["voucher_code"] == "MEACTIVE"
        assert data[0]["status"] == "active"

    def test_empty_when_no_vouchers_assigned(self, tenant, customer):
        c, token = _login(tenant, customer)
        resp = c.get("/api/clients/me/vouchers/", **auth_headers(token))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == []

    def test_status_used(self, tenant, customer):
        voucher = Voucher.objects.create(
            tenant=tenant, code="MEUSED01", type=Voucher.VoucherType.FIXED, value=5
        )
        ClientVoucher.objects.create(
            tenant=tenant, voucher=voucher, client=customer, used_at=timezone.now()
        )

        c, token = _login(tenant, customer)
        resp = c.get("/api/clients/me/vouchers/", **auth_headers(token))
        assert resp.json()[0]["status"] == "used"

    def test_status_expired(self, tenant, customer):
        voucher = Voucher.objects.create(
            tenant=tenant,
            code="MEEXPIR1",
            type=Voucher.VoucherType.PERCENT,
            value=10,
            valid_until=timezone.localdate() - datetime.timedelta(days=1),
        )
        ClientVoucher.objects.create(tenant=tenant, voucher=voucher, client=customer)

        c, token = _login(tenant, customer)
        resp = c.get("/api/clients/me/vouchers/", **auth_headers(token))
        assert resp.json()[0]["status"] == "expired"

    def test_cannot_see_vouchers_of_other_client_same_tenant(
        self, tenant, customer, other_customer
    ):
        voucher = Voucher.objects.create(
            tenant=tenant, code="NOTMINE1", type=Voucher.VoucherType.PERCENT, value=10
        )
        ClientVoucher.objects.create(
            tenant=tenant, voucher=voucher, client=other_customer
        )

        c, token = _login(tenant, customer)
        resp = c.get("/api/clients/me/vouchers/", **auth_headers(token))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == []

    def test_cannot_see_vouchers_of_other_tenant(
        self, tenant, customer, other_tenant, other_tenant_customer
    ):
        other_voucher = Voucher.objects.create(
            tenant=other_tenant,
            code="OTHTEN01",
            type=Voucher.VoucherType.PERCENT,
            value=10,
        )
        ClientVoucher.objects.create(
            tenant=other_tenant, voucher=other_voucher, client=other_tenant_customer
        )

        c, token = _login(tenant, customer)
        resp = c.get("/api/clients/me/vouchers/", **auth_headers(token))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == []

    def test_unauthenticated_cannot_list(self):
        c = APIClient()
        resp = c.get("/api/clients/me/vouchers/")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_staff_token_cannot_list_client_vouchers(self, tenant, customer):
        """Token sem scope=client (ex.: JWT de staff) não deve funcionar aqui."""
        from rest_framework_simplejwt.tokens import RefreshToken

        from users.models import CustomUser

        staff_user = CustomUser.objects.create_user(
            username="staff-me-vouchers",
            password="pass",
            email="staff-me-vouchers@example.com",
            tenant=tenant,
        )
        refresh = RefreshToken.for_user(staff_user)
        access = str(refresh.access_token)

        c = APIClient()
        resp = c.get("/api/clients/me/vouchers/", **auth_headers(access))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
