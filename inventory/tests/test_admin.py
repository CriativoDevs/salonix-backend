from django.contrib import admin

from inventory.admin import InventoryItemAdmin
from inventory.models import InventoryItem
from salonix_backend.admin import admin_site


def test_inventory_item_is_registered_in_default_admin_site():
    assert admin.site.is_registered(InventoryItem)


def test_inventory_item_is_registered_in_custom_admin_site():
    """O painel real usado em produção é o `TimelyOneAdminSite` customizado
    (ver `salonix_backend/admin.py`), não o `admin.site` padrão do Django.
    """
    assert InventoryItem in admin_site._registry
    assert isinstance(admin_site._registry[InventoryItem], InventoryItemAdmin)


def test_admin_exposes_expected_list_display():
    model_admin = admin.site._registry[InventoryItem]
    assert isinstance(model_admin, InventoryItemAdmin)
    assert "tenant" in model_admin.list_display
    assert "quantity" in model_admin.list_display
