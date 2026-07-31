import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from inventory.models import InventoryItem
from users.models import Tenant, TenantStaffMember

User = get_user_model()


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        slug="tenant-b-alerts",
        name="Tenant B Alerts",
        plan_tier=Tenant.PLAN_BASIC,
    )


@pytest.fixture
def staff_user(db, tenant_fixture):
    """Staff comum (não owner/manager) — alertas são leitura, disponível a
    qualquer staff autenticado do tenant (mesmo padrão de list)."""
    user = User.objects.create_user(
        username="staff-alerts", email="staff-alerts@test.com", password="testpass123"
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
        username="owner-alerts-2",
        email="owner-alerts-2@test.com",
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
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestInventoryAlerts:
    url = "/api/inventory/alerts/"

    def test_item_below_minimum_appears_in_alerts(self, api_client, staff_user, tenant_fixture):
        item = InventoryItem.objects.create(
            tenant=tenant_fixture,
            name="Luvas descartáveis",
            unit="cx",
            quantity=2,
            minimum_quantity=5,
        )
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        ids = [i["id"] for i in results]
        assert item.id in ids

    def test_item_equal_to_minimum_appears_in_alerts(
        self, api_client, staff_user, tenant_fixture
    ):
        item = InventoryItem.objects.create(
            tenant=tenant_fixture,
            name="Agulhas",
            unit="unidade",
            quantity=5,
            minimum_quantity=5,
        )
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        ids = [i["id"] for i in results]
        assert item.id in ids

    def test_item_above_minimum_does_not_appear(self, api_client, staff_user, tenant_fixture):
        item = InventoryItem.objects.create(
            tenant=tenant_fixture,
            name="Tinta preta",
            unit="frasco",
            quantity=20,
            minimum_quantity=5,
        )
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        ids = [i["id"] for i in results]
        assert item.id not in ids

    def test_item_with_zero_minimum_does_not_appear(
        self, api_client, staff_user, tenant_fixture
    ):
        item = InventoryItem.objects.create(
            tenant=tenant_fixture,
            name="Algodão",
            unit="pacote",
            quantity=0,
            minimum_quantity=0,
        )
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        ids = [i["id"] for i in results]
        assert item.id not in ids

    def test_item_with_null_minimum_does_not_appear(
        self, api_client, staff_user, tenant_fixture
    ):
        item = InventoryItem.objects.create(
            tenant=tenant_fixture,
            name="Shampoo",
            unit="frasco",
            quantity=0,
            minimum_quantity=None,
        )
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        ids = [i["id"] for i in results]
        assert item.id not in ids

    def test_alerts_do_not_include_other_tenant_items(
        self, api_client, staff_user, tenant_fixture, other_tenant
    ):
        InventoryItem.objects.create(
            tenant=other_tenant,
            name="Item do outro tenant",
            unit="unidade",
            quantity=1,
            minimum_quantity=10,
        )
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        names = [i["name"] for i in results]
        assert "Item do outro tenant" not in names

    def test_unauthenticated_cannot_access_alerts(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
