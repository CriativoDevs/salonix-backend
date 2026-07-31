from django.contrib import admin

from inventory.admin import InventoryItemAdmin, StockMovementAdmin
from inventory.models import InventoryItem, StockMovement
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


def test_stock_movement_is_registered_in_default_admin_site():
    assert admin.site.is_registered(StockMovement)


def test_stock_movement_is_registered_in_custom_admin_site():
    assert StockMovement in admin_site._registry
    assert isinstance(admin_site._registry[StockMovement], StockMovementAdmin)


def test_stock_movement_admin_exposes_expected_list_display():
    model_admin = admin.site._registry[StockMovement]
    assert isinstance(model_admin, StockMovementAdmin)
    assert "tenant" in model_admin.list_display
    assert "quantity" in model_admin.list_display
    assert "movement_type" in model_admin.list_display


def test_stock_movement_admin_is_read_only():
    model_admin = admin.site._registry[StockMovement]
    assert model_admin.has_add_permission(None) is False
    assert model_admin.has_change_permission(None) is False
    assert model_admin.has_delete_permission(None) is False
