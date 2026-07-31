import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from inventory.models import InventoryItem, StockMovement
from users.models import Tenant


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        slug="tenant-b-stock",
        name="Tenant B Stock",
        plan_tier=Tenant.PLAN_BASIC,
    )


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


@pytest.mark.django_db
class TestStockMovementModel:
    def test_create_in_movement_increments_item_quantity(
        self, tenant_fixture, item_fixture
    ):
        movement = StockMovement.objects.create(
            tenant=tenant_fixture,
            item=item_fixture,
            movement_type=StockMovement.MovementType.IN,
            quantity=5,
        )
        item_fixture.refresh_from_db()
        assert item_fixture.quantity == 15
        assert movement.pk is not None

    def test_create_out_movement_decrements_item_quantity(
        self, tenant_fixture, item_fixture
    ):
        StockMovement.objects.create(
            tenant=tenant_fixture,
            item=item_fixture,
            movement_type=StockMovement.MovementType.OUT,
            quantity=4,
        )
        item_fixture.refresh_from_db()
        assert item_fixture.quantity == 6

    def test_out_movement_cannot_make_quantity_negative(
        self, tenant_fixture, item_fixture
    ):
        with pytest.raises(ValidationError):
            StockMovement.objects.create(
                tenant=tenant_fixture,
                item=item_fixture,
                movement_type=StockMovement.MovementType.OUT,
                quantity=999,
            )
        item_fixture.refresh_from_db()
        assert item_fixture.quantity == 10

    def test_notes_optional(self, tenant_fixture, item_fixture):
        movement = StockMovement.objects.create(
            tenant=tenant_fixture,
            item=item_fixture,
            movement_type=StockMovement.MovementType.IN,
            quantity=1,
        )
        assert movement.notes in ("", None)

    def test_created_at_set(self, tenant_fixture, item_fixture):
        movement = StockMovement.objects.create(
            tenant=tenant_fixture,
            item=item_fixture,
            movement_type=StockMovement.MovementType.IN,
            quantity=1,
        )
        assert movement.created_at is not None

    def test_str_representation(self, tenant_fixture, item_fixture):
        movement = StockMovement.objects.create(
            tenant=tenant_fixture,
            item=item_fixture,
            movement_type=StockMovement.MovementType.IN,
            quantity=1,
        )
        assert item_fixture.name in str(movement)

    def test_isolation_between_tenants(
        self, tenant_fixture, other_tenant, item_fixture, other_item_fixture
    ):
        StockMovement.objects.create(
            tenant=tenant_fixture,
            item=item_fixture,
            movement_type=StockMovement.MovementType.IN,
            quantity=1,
        )
        StockMovement.objects.create(
            tenant=other_tenant,
            item=other_item_fixture,
            movement_type=StockMovement.MovementType.IN,
            quantity=1,
        )
        assert StockMovement.objects.filter(tenant=tenant_fixture).count() == 1
        assert StockMovement.objects.filter(tenant=other_tenant).count() == 1
