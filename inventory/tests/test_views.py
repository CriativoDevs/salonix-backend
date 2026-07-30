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
        slug="tenant-b",
        name="Tenant B",
        plan_tier=Tenant.PLAN_BASIC,
    )


@pytest.fixture
def owner_user(db, tenant_fixture):
    user = User.objects.create_user(
        username="owner1", email="owner1@test.com", password="testpass123"
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
        username="manager1", email="manager1@test.com", password="testpass123"
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
        username="staff1", email="staff1@test.com", password="testpass123"
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
        username="owner2",
        email="owner2@test.com",
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
def item_fixture(db, tenant_fixture):
    return InventoryItem.objects.create(
        tenant=tenant_fixture,
        name="Luvas descartáveis",
        unit="cx",
        quantity=10,
    )


@pytest.fixture
def other_item_fixture(db, other_tenant):
    return InventoryItem.objects.create(
        tenant=other_tenant,
        name="Item do outro tenant",
        unit="unidade",
        quantity=5,
    )


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestInventoryItemListCreate:
    url = "/api/inventory/items/"

    def test_owner_can_list_items(self, api_client, owner_user, item_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        names = [i["name"] for i in results]
        assert "Luvas descartáveis" in names

    def test_list_does_not_include_other_tenant_items(
        self, api_client, owner_user, item_fixture, other_item_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        names = [i["name"] for i in results]
        assert "Item do outro tenant" not in names

    def test_owner_can_create_item(self, api_client, owner_user, tenant_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url, {"name": "Tinta preta", "unit": "frasco", "quantity": 3}
        )
        assert response.status_code == status.HTTP_201_CREATED
        item = InventoryItem.objects.get(id=response.json()["id"])
        assert item.tenant == tenant_fixture
        assert item.name == "Tinta preta"

    def test_manager_can_create_item(self, api_client, manager_user):
        api_client.force_authenticate(user=manager_user)
        response = api_client.post(
            self.url, {"name": "Algodão", "unit": "pacote", "quantity": 1}
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_staff_cannot_create_item(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        response = api_client.post(
            self.url, {"name": "Shampoo", "unit": "frasco", "quantity": 2}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not InventoryItem.objects.filter(name="Shampoo").exists()

    def test_unauthenticated_cannot_list(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestInventoryItemRetrieveUpdate:
    def url(self, item):
        return f"/api/inventory/items/{item.id}/"

    def test_staff_can_retrieve_item(self, api_client, staff_user, item_fixture):
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url(item_fixture))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == item_fixture.name

    def test_staff_can_update_item(self, api_client, staff_user, item_fixture):
        api_client.force_authenticate(user=staff_user)
        response = api_client.patch(self.url(item_fixture), {"quantity": 25})
        assert response.status_code == status.HTTP_200_OK
        item_fixture.refresh_from_db()
        assert item_fixture.quantity == 25

    def test_owner_can_update_item(self, api_client, owner_user, item_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.put(
            self.url(item_fixture),
            {"name": "Luvas descartáveis", "unit": "cx", "quantity": 50},
        )
        assert response.status_code == status.HTTP_200_OK
        item_fixture.refresh_from_db()
        assert item_fixture.quantity == 50

    def test_other_tenant_cannot_retrieve_item(
        self, api_client, owner_user, other_item_fixture
    ):
        # owner_user pertence ao tenant padrão (tenant_fixture); o item
        # pertence a other_tenant. Mantém o mesmo sentido usado nos testes
        # de isolamento existentes em core/tests/test_multi_tenant.py, já
        # que o tenant padrão é o único mockado de forma estável no
        # middleware de testes (ver conftest.py).
        api_client.force_authenticate(user=owner_user)
        response = api_client.get(self.url(other_item_fixture))
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_403_FORBIDDEN,
        )

    def test_other_tenant_cannot_update_item(
        self, api_client, owner_user, other_item_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.patch(self.url(other_item_fixture), {"quantity": 999})
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_403_FORBIDDEN,
        )
        other_item_fixture.refresh_from_db()
        assert other_item_fixture.quantity != 999


@pytest.mark.django_db
class TestInventoryItemDestroy:
    def url(self, item):
        return f"/api/inventory/items/{item.id}/"

    def test_owner_can_delete_item(self, api_client, owner_user, item_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.delete(self.url(item_fixture))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not InventoryItem.objects.filter(id=item_fixture.id).exists()

    def test_manager_can_delete_item(self, api_client, manager_user, item_fixture):
        api_client.force_authenticate(user=manager_user)
        response = api_client.delete(self.url(item_fixture))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_staff_cannot_delete_item(self, api_client, staff_user, item_fixture):
        api_client.force_authenticate(user=staff_user)
        response = api_client.delete(self.url(item_fixture))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert InventoryItem.objects.filter(id=item_fixture.id).exists()

    def test_other_tenant_owner_cannot_delete_item(
        self, api_client, owner_user, other_item_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.delete(self.url(other_item_fixture))
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_403_FORBIDDEN,
        )
        assert InventoryItem.objects.filter(id=other_item_fixture.id).exists()
