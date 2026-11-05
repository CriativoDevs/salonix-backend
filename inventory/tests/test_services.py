import pytest

from inventory.models import InventoryItem
from inventory.services import tenant_has_active_stock
from users.models import Tenant


@pytest.mark.django_db
class TestTenantHasActiveStock:
    def test_returns_false_when_tenant_is_none(self):
        assert tenant_has_active_stock(None) is False

    def test_returns_false_when_tenant_has_no_items(self, tenant_fixture):
        assert tenant_has_active_stock(tenant_fixture) is False

    def test_returns_true_when_tenant_has_at_least_one_item(self, tenant_fixture):
        InventoryItem.objects.create(
            tenant=tenant_fixture,
            name="Luvas",
            unit="cx",
            quantity=10,
        )
        assert tenant_has_active_stock(tenant_fixture) is True

    def test_does_not_leak_across_tenants(self, tenant_fixture):
        other_tenant = Tenant.objects.create(
            slug="tenant-b-services",
            name="Tenant B Services",
            plan_tier=Tenant.PLAN_BASIC,
        )
        InventoryItem.objects.create(
            tenant=other_tenant,
            name="Item do outro tenant",
            unit="unidade",
            quantity=5,
        )
        assert tenant_has_active_stock(tenant_fixture) is False
        assert tenant_has_active_stock(other_tenant) is True
