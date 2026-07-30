from rest_framework import serializers

from inventory.models import InventoryItem


class InventoryItemSerializer(serializers.ModelSerializer):
    """Serializer de item de estoque (BE-STOCK-02, #465).

    O `tenant` nunca é aceite via payload — é sempre atribuído pela view a
    partir do request autenticado (isolamento multi-tenant).
    """

    class Meta:
        model = InventoryItem
        fields = ["id", "name", "unit", "quantity"]
