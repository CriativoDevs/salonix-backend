"""Testes de GET /api/salon/customers/{id}/vouchers/ (BE-VOUCHER-02, #471).

Lista os vouchers atribuídos a um cliente (`ClientVoucher`), aberto a
qualquer staff autenticado do tenant, com isolamento entre tenants.
"""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import SalonCustomer
from users.models import CustomUser, Tenant, TenantStaffMember
from vouchers.models import ClientVoucher, Voucher


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(
        name="Salão Vouchers",
        slug="salao-vouchers",
        plan_tier=Tenant.PLAN_BASIC,
    )


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        name="Outro Salão",
        slug="outro-salao-vouchers",
        plan_tier=Tenant.PLAN_BASIC,
    )


@pytest.fixture
def owner(db, tenant):
    user = CustomUser.objects.create_user(
        username="cv-owner", email="cv-owner@test.com", password="testpass123", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def staff(db, tenant):
    user = CustomUser.objects.create_user(
        username="cv-staff", email="cv-staff@test.com", password="testpass123", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant,
        user=user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def other_owner(db, other_tenant):
    user = CustomUser.objects.create_user(
        username="cv-owner2",
        email="cv-owner2@test.com",
        password="testpass123",
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
def customer(db, tenant):
    return SalonCustomer.objects.create(tenant=tenant, name="Cliente com Vouchers")


@pytest.fixture
def other_tenant_customer(db, other_tenant):
    return SalonCustomer.objects.create(tenant=other_tenant, name="Cliente de Outro Tenant")


@pytest.fixture
def api_client():
    return APIClient()


def vouchers_url(customer_obj):
    return reverse("salon-customers-vouchers", args=[customer_obj.id])


@pytest.mark.django_db
class TestSalonCustomerVouchersList:
    def test_owner_can_list_client_vouchers(self, api_client, owner, tenant, customer):
        voucher = Voucher.objects.create(
            tenant=tenant, code="ACTIVE01", type=Voucher.VoucherType.PERCENT, value=10
        )
        ClientVoucher.objects.create(tenant=tenant, voucher=voucher, client=customer)

        api_client.force_authenticate(user=owner)
        response = api_client.get(vouchers_url(customer))

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["voucher_code"] == "ACTIVE01"
        assert data[0]["status"] == "active"

    def test_staff_can_list_client_vouchers(self, api_client, staff, tenant, customer):
        voucher = Voucher.objects.create(
            tenant=tenant, code="ACTIVE02", type=Voucher.VoucherType.PERCENT, value=10
        )
        ClientVoucher.objects.create(tenant=tenant, voucher=voucher, client=customer)

        api_client.force_authenticate(user=staff)
        response = api_client.get(vouchers_url(customer))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1

    def test_empty_when_no_vouchers_assigned(self, api_client, owner, customer):
        api_client.force_authenticate(user=owner)
        response = api_client.get(vouchers_url(customer))
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_status_used(self, api_client, owner, tenant, customer):
        voucher = Voucher.objects.create(
            tenant=tenant, code="USEDONE1", type=Voucher.VoucherType.PERCENT, value=10
        )
        ClientVoucher.objects.create(
            tenant=tenant, voucher=voucher, client=customer, used_at=timezone.now()
        )

        api_client.force_authenticate(user=owner)
        response = api_client.get(vouchers_url(customer))
        assert response.json()[0]["status"] == "used"

    def test_status_expired(self, api_client, owner, tenant, customer):
        voucher = Voucher.objects.create(
            tenant=tenant,
            code="EXPIRED1",
            type=Voucher.VoucherType.PERCENT,
            value=10,
            valid_until=timezone.localdate() - datetime.timedelta(days=1),
        )
        ClientVoucher.objects.create(tenant=tenant, voucher=voucher, client=customer)

        api_client.force_authenticate(user=owner)
        response = api_client.get(vouchers_url(customer))
        assert response.json()[0]["status"] == "expired"

    def test_other_tenant_cannot_list_vouchers_of_foreign_customer(
        self, api_client, other_owner, tenant, customer
    ):
        voucher = Voucher.objects.create(
            tenant=tenant, code="ISOLATE1", type=Voucher.VoucherType.PERCENT, value=10
        )
        ClientVoucher.objects.create(tenant=tenant, voucher=voucher, client=customer)

        api_client.force_authenticate(user=other_owner)
        response = api_client.get(vouchers_url(customer))

        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_403_FORBIDDEN,
        )

    def test_unauthenticated_cannot_list(self, api_client, customer):
        response = api_client.get(vouchers_url(customer))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
