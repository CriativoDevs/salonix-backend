import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from users.models import Tenant, TenantStaffMember
from vouchers.models import Voucher

User = get_user_model()


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        slug="tenant-b",
        name="Tenant B",
        plan_tier=Tenant.PLAN_BASIC,
    )


@pytest.fixture
def owner_user(db, tenant_fixture):
    user = User.objects.create_user(
        username="voucher-owner1", email="voucher-owner1@test.com", password="testpass123"
    )
    TenantStaffMember.objects.create(
        tenant=tenant_fixture,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def manager_user(db, tenant_fixture):
    user = User.objects.create_user(
        username="voucher-manager1", email="voucher-manager1@test.com", password="testpass123"
    )
    TenantStaffMember.objects.create(
        tenant=tenant_fixture,
        user=user,
        role=TenantStaffMember.Role.MANAGER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def staff_user(db, tenant_fixture):
    """Staff comum (não owner/manager)."""
    user = User.objects.create_user(
        username="voucher-staff1", email="voucher-staff1@test.com", password="testpass123"
    )
    TenantStaffMember.objects.create(
        tenant=tenant_fixture,
        user=user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def other_owner_user(db, other_tenant):
    user = User.objects.create_user(
        username="voucher-owner2",
        email="voucher-owner2@test.com",
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
def voucher_fixture(db, tenant_fixture):
    return Voucher.objects.create(
        tenant=tenant_fixture,
        code="EXISTING",
        type=Voucher.VoucherType.PERCENT,
        value=15,
    )


@pytest.fixture
def other_voucher_fixture(db, other_tenant):
    return Voucher.objects.create(
        tenant=other_tenant,
        code="OTHERONE",
        type=Voucher.VoucherType.FIXED,
        value=5,
    )


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestVoucherListCreate:
    url = "/api/vouchers/"

    def test_owner_can_list_vouchers(self, api_client, owner_user, voucher_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        codes = [v["code"] for v in results]
        assert "EXISTING" in codes

    def test_staff_can_list_vouchers(self, api_client, staff_user, voucher_fixture):
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK

    def test_list_does_not_include_other_tenant_vouchers(
        self, api_client, owner_user, voucher_fixture, other_voucher_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        codes = [v["code"] for v in results]
        assert "OTHERONE" not in codes

    def test_owner_can_create_percent_voucher_with_explicit_code(
        self, api_client, owner_user, tenant_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url,
            {"code": "mycode12", "type": "percent", "value": "20.00"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        voucher = Voucher.objects.get(id=response.json()["id"])
        assert voucher.tenant == tenant_fixture
        # Código é normalizado para maiúsculas.
        assert voucher.code == "MYCODE12"

    def test_code_generated_automatically_when_omitted(self, api_client, owner_user):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url, {"type": "percent", "value": "10.00"}
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["code"]
        assert len(data["code"]) == 8

    def test_manager_can_create_voucher(self, api_client, manager_user):
        api_client.force_authenticate(user=manager_user)
        response = api_client.post(
            self.url, {"type": "fixed", "value": "5.00"}
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_staff_cannot_create_voucher(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        response = api_client.post(
            self.url, {"type": "fixed", "value": "5.00"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Voucher.objects.filter(type="fixed", value=5).exists()

    def test_unauthenticated_cannot_list(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cannot_create_duplicate_code_within_tenant(
        self, api_client, owner_user, voucher_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url,
            {"code": "existing", "type": "fixed", "value": "1.00"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "code" in response.json()["error"]["details"]

    def test_same_code_allowed_across_tenants(
        self, api_client, owner_user, other_voucher_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url,
            {"code": "otherone", "type": "fixed", "value": "1.00"},
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_free_service_voucher_requires_service(self, api_client, owner_user):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(self.url, {"type": "free_service"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "service" in response.json()["error"]["details"]

    def test_free_service_voucher_with_service(
        self, api_client, owner_user, tenant_fixture
    ):
        from core.models import Service

        service = Service.objects.create(
            tenant=tenant_fixture,
            user=owner_user,
            name="Corte",
            duration_minutes=30,
            price_eur=50,
        )
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url, {"type": "free_service", "service": service.id}
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["service"] == service.id
        assert data["value"] is None

    def test_percent_voucher_requires_value(self, api_client, owner_user):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(self.url, {"type": "percent"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "value" in response.json()["error"]["details"]

    def test_cannot_use_service_from_other_tenant(
        self, api_client, owner_user, other_tenant
    ):
        from core.models import Service

        other_service = Service.objects.create(
            tenant=other_tenant,
            user=User.objects.create_user(
                username="svc-owner", email="svc-owner@test.com", password="x"
            ),
            name="Serviço de outro tenant",
            duration_minutes=30,
            price_eur=10,
        )
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url, {"type": "free_service", "service": other_service.id}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "service" in response.json()["error"]["details"]


@pytest.mark.django_db
class TestVoucherRetrieveUpdate:
    def url(self, voucher):
        return f"/api/vouchers/{voucher.id}/"

    def test_staff_can_retrieve_voucher(self, api_client, staff_user, voucher_fixture):
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url(voucher_fixture))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["code"] == voucher_fixture.code

    def test_staff_cannot_update_voucher(self, api_client, staff_user, voucher_fixture):
        api_client.force_authenticate(user=staff_user)
        response = api_client.patch(self.url(voucher_fixture), {"value": "50.00"})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        voucher_fixture.refresh_from_db()
        assert voucher_fixture.value != 50

    def test_owner_can_update_voucher(self, api_client, owner_user, voucher_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.patch(self.url(voucher_fixture), {"value": "50.00"})
        assert response.status_code == status.HTTP_200_OK
        voucher_fixture.refresh_from_db()
        assert voucher_fixture.value == 50

    def test_manager_can_update_voucher(self, api_client, manager_user, voucher_fixture):
        api_client.force_authenticate(user=manager_user)
        response = api_client.patch(self.url(voucher_fixture), {"max_uses": 3})
        assert response.status_code == status.HTTP_200_OK
        voucher_fixture.refresh_from_db()
        assert voucher_fixture.max_uses == 3

    def test_other_tenant_cannot_retrieve_voucher(
        self, api_client, owner_user, other_voucher_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.get(self.url(other_voucher_fixture))
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_403_FORBIDDEN,
        )

    def test_other_tenant_cannot_update_voucher(
        self, api_client, owner_user, other_voucher_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.patch(self.url(other_voucher_fixture), {"value": "99.00"})
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_403_FORBIDDEN,
        )
        other_voucher_fixture.refresh_from_db()
        assert other_voucher_fixture.value != 99


@pytest.mark.django_db
class TestVoucherDestroy:
    def url(self, voucher):
        return f"/api/vouchers/{voucher.id}/"

    def test_owner_can_delete_voucher(self, api_client, owner_user, voucher_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.delete(self.url(voucher_fixture))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Voucher.objects.filter(id=voucher_fixture.id).exists()

    def test_manager_can_delete_voucher(self, api_client, manager_user, voucher_fixture):
        api_client.force_authenticate(user=manager_user)
        response = api_client.delete(self.url(voucher_fixture))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_staff_cannot_delete_voucher(self, api_client, staff_user, voucher_fixture):
        api_client.force_authenticate(user=staff_user)
        response = api_client.delete(self.url(voucher_fixture))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert Voucher.objects.filter(id=voucher_fixture.id).exists()

    def test_other_tenant_owner_cannot_delete_voucher(
        self, api_client, owner_user, other_voucher_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.delete(self.url(other_voucher_fixture))
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_403_FORBIDDEN,
        )
        assert Voucher.objects.filter(id=other_voucher_fixture.id).exists()
