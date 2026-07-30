from django.contrib import admin

from inventory.models import InventoryItem


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    """Admin de itens de estoque (BE-STOCK-01).

    Somente leitura de suporte/OPS por agora — CRUD completo é feito pelo
    tenant via API, a implementar em BE-STOCK-02.
    """

    list_display = ("name", "tenant", "unit", "quantity", "updated_at")
    list_filter = ("unit",)
    search_fields = ("name", "tenant__name", "tenant__slug")
    readonly_fields = ("created_at", "updated_at")
