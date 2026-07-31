from django.contrib import admin

from inventory.models import InventoryItem, StockMovement


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


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """Admin (leitura de suporte/OPS) de movimentações de estoque
    (BE-STOCK-03, #466). Histórico imutável: sem edição/remoção também no
    admin.
    """

    list_display = (
        "item",
        "tenant",
        "movement_type",
        "quantity",
        "created_at",
    )
    list_filter = ("movement_type",)
    search_fields = ("item__name", "tenant__name", "tenant__slug")
    readonly_fields = ("tenant", "item", "movement_type", "quantity", "notes", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
