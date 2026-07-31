import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from inventory.models import InventoryItem, StockMovement
from users.models import Tenant, TenantStaffMember

User = get_user_model()


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        slug="tenant-b-stock-views",
        name="Tenant B Stock Views",
        plan_tier=Tenant.PLAN_BASIC,
    )


@pytest.fixture
def owner_user(db, tenant_fixture):
    user = User.objects.create_user(
        username="owner-sm", email="owner-sm@test.com", password="testpass123"
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
        username="manager-sm", email="manager-sm@test.com", password="testpass123"
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
    user = User.objects.create_user(
        username="staff-sm", email="staff-sm@test.com", password="testpass123"
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
        username="owner2-sm",
        email="owner2-sm@test.com",
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
def movement_fixture(db, tenant_fixture, item_fixture):
    return StockMovement.objects.create(
        tenant=tenant_fixture,
        item=item_fixture,
        movement_type=StockMovement.MovementType.IN,
        quantity=3,
    )


@pytest.fixture
def other_movement_fixture(db, other_tenant, other_item_fixture):
    return StockMovement.objects.create(
        tenant=other_tenant,
        item=other_item_fixture,
        movement_type=StockMovement.MovementType.IN,
        quantity=2,
    )


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestStockMovementListCreate:
    url = "/api/inventory/movements/"

    def test_owner_can_create_in_movement(self, api_client, owner_user, item_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url, {"item": item_fixture.id, "movement_type": "in", "quantity": 5}
        )
        assert response.status_code == status.HTTP_201_CREATED
        item_fixture.refresh_from_db()
        assert item_fixture.quantity == 15

    def test_manager_can_create_out_movement(
        self, api_client, manager_user, item_fixture
    ):
        api_client.force_authenticate(user=manager_user)
        response = api_client.post(
            self.url, {"item": item_fixture.id, "movement_type": "out", "quantity": 4}
        )
        assert response.status_code == status.HTTP_201_CREATED
        item_fixture.refresh_from_db()
        assert item_fixture.quantity == 6

    def test_out_movement_rejects_negative_balance(
        self, api_client, owner_user, item_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url,
            {"item": item_fixture.id, "movement_type": "out", "quantity": 999},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        item_fixture.refresh_from_db()
        assert item_fixture.quantity == 10

    def test_staff_cannot_create_movement(self, api_client, staff_user, item_fixture):
        api_client.force_authenticate(user=staff_user)
        response = api_client.post(
            self.url, {"item": item_fixture.id, "movement_type": "in", "quantity": 1}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        item_fixture.refresh_from_db()
        assert item_fixture.quantity == 10

    def test_unauthenticated_cannot_create(self, api_client, item_fixture):
        response = api_client.post(
            self.url, {"item": item_fixture.id, "movement_type": "in", "quantity": 1}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_staff_can_list_movements(
        self, api_client, staff_user, movement_fixture
    ):
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        assert len(results) == 1

    def test_list_does_not_include_other_tenant_movements(
        self, api_client, owner_user, movement_fixture, other_movement_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        ids = [m["id"] for m in results]
        assert other_movement_fixture.id not in ids

    def test_unauthenticated_cannot_list(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cannot_create_movement_for_other_tenant_item(
        self, api_client, owner_user, other_item_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url,
            {"item": other_item_fixture.id, "movement_type": "in", "quantity": 1},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        other_item_fixture.refresh_from_db()
        assert other_item_fixture.quantity == 5


@pytest.mark.django_db
class TestStockMovementImmutable:
    def test_update_not_allowed(self, api_client, owner_user, movement_fixture):
        # A viewset só expõe list/create (nenhuma rota de detalhe é
        # registrada pelo router), então o DRF responde 404 em vez de 405 —
        # o efeito prático é o mesmo: não há caminho para editar o histórico.
        api_client.force_authenticate(user=owner_user)
        url = f"/api/inventory/movements/{movement_fixture.id}/"
        response = api_client.patch(url, {"quantity": 99})
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        movement_fixture.refresh_from_db()
        assert movement_fixture.quantity == 3

    def test_delete_not_allowed(self, api_client, owner_user, movement_fixture):
        api_client.force_authenticate(user=owner_user)
        url = f"/api/inventory/movements/{movement_fixture.id}/"
        response = api_client.delete(url)
        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        assert StockMovement.objects.filter(id=movement_fixture.id).exists()
