from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from inventory.models import InventoryItem, StockMovement


class InventoryItemSerializer(serializers.ModelSerializer):
    """Serializer de item de estoque (BE-STOCK-02, #465).

    O `tenant` nunca é aceite via payload — é sempre atribuído pela view a
    partir do request autenticado (isolamento multi-tenant).
    """

    class Meta:
        model = InventoryItem
        fields = ["id", "name", "unit", "quantity"]


class StockMovementSerializer(serializers.ModelSerializer):
    """Serializer de movimentação de estoque (BE-STOCK-03, #466).

    `tenant` nunca é aceite via payload — vem sempre do request autenticado
    (isolamento multi-tenant). `item` é restrito ao queryset informado pela
    view (itens do próprio tenant), evitando IDOR sobre itens de outro
    tenant.
    """

    class Meta:
        model = StockMovement
        fields = ["id", "item", "movement_type", "quantity", "notes", "created_at"]
        read_only_fields = ["id", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Restringe as opções de `item` aos itens do tenant do request, para
        # que nem a validação do campo revele/aceite itens de outro tenant.
        tenant = getattr(self.context.get("request"), "tenant", None) or getattr(
            getattr(self.context.get("request"), "user", None), "tenant", None
        )
        if tenant is not None:
            self.fields["item"].queryset = InventoryItem.objects.filter(tenant=tenant)

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"quantity": exc.messages if hasattr(exc, "messages") else [str(exc)]}
            )
