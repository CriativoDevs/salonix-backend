import pytest
from django.db import IntegrityError

from inventory.models import InventoryItem
from users.models import Tenant


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        slug="tenant-b",
        name="Tenant B",
        plan_tier=Tenant.PLAN_BASIC,
    )


def make_item(tenant, **overrides):
    defaults = dict(
        tenant=tenant,
        name="Luvas descartáveis",
        unit="cx",
        quantity=10,
    )
    defaults.update(overrides)
    return InventoryItem.objects.create(**defaults)


@pytest.mark.django_db
class TestInventoryItemModel:
    def test_create_item(self, tenant_fixture):
        item = make_item(tenant_fixture)
        assert item.pk is not None
        assert item.tenant == tenant_fixture
        assert item.name == "Luvas descartáveis"
        assert item.unit == "cx"
        assert item.quantity == 10
        assert item.created_at is not None
        assert item.updated_at is not None

    def test_str_representation(self, tenant_fixture):
        item = make_item(tenant_fixture, name="Agulhas")
        assert "Agulhas" in str(item)

    def test_quantity_defaults_to_zero(self, tenant_fixture):
        item = InventoryItem.objects.create(
            tenant=tenant_fixture, name="Tinta preta", unit="frasco"
        )
        assert item.quantity == 0

    def test_unique_name_per_tenant(self, tenant_fixture):
        make_item(tenant_fixture, name="Luvas")
        with pytest.raises(IntegrityError):
            make_item(tenant_fixture, name="Luvas")

    def test_same_name_allowed_across_tenants(self, tenant_fixture, other_tenant):
        item_a = make_item(tenant_fixture, name="Luvas")
        item_b = make_item(other_tenant, name="Luvas")
        assert item_a.pk != item_b.pk
        assert item_a.tenant != item_b.tenant

    def test_isolation_between_tenants(self, tenant_fixture, other_tenant):
        make_item(tenant_fixture, name="Item A")
        make_item(other_tenant, name="Item B")

        tenant_items = InventoryItem.objects.filter(tenant=tenant_fixture)
        other_items = InventoryItem.objects.filter(tenant=other_tenant)

        assert list(tenant_items.values_list("name", flat=True)) == ["Item A"]
        assert list(other_items.values_list("name", flat=True)) == ["Item B"]

    def test_deleting_tenant_cascades_items(self, tenant_fixture):
        item = make_item(tenant_fixture)
        item_id = item.pk
        tenant_fixture.delete()
        assert not InventoryItem.objects.filter(pk=item_id).exists()

    def test_ordering_defaults_to_name(self, tenant_fixture):
        make_item(tenant_fixture, name="Zinco")
        make_item(tenant_fixture, name="Algodão")
        names = list(InventoryItem.objects.filter(tenant=tenant_fixture).values_list(
            "name", flat=True
        ))
        assert names == ["Algodão", "Zinco"]
