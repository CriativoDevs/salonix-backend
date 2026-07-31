import logging

from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.mixins import CreateModelMixin, ListModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from core.mixins import TenantIsolatedMixin
from inventory.models import InventoryItem, StockMovement
from inventory.serializers import InventoryItemSerializer, StockMovementSerializer
from users.models import TenantStaffMember

logger = logging.getLogger(__name__)


class InventoryItemViewSet(TenantIsolatedMixin, ModelViewSet):
    """CRUD de itens de estoque (BE-STOCK-02, #465).

    Sem validação de limite por plano (decisão tomada: os planos ativos hoje
    são Basic/Founder, ambos com acesso igual ao estoque; ver BE-STOCK-01).

    Permissões:
    - list/retrieve/update/partial_update: qualquer staff autenticado do
      tenant.
    - create/destroy: apenas owner ou manager do tenant.
    """

    queryset = InventoryItem.objects.all()
    serializer_class = InventoryItemSerializer
    permission_classes = [IsAuthenticated]

    def _resolve_tenant(self):
        # Endpoint autenticado: o tenant vem sempre da sessão/membership do
        # usuário (request.tenant, setado pelo middleware a partir do JWT, ou
        # request.user.tenant). Nunca de header/query-param client-supplied —
        # isso permitiria a um staff de um tenant escolher outro tenant à
        # vontade (bypass de isolamento).
        return getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )

    def perform_create(self, serializer):
        tenant = self._resolve_tenant()
        if tenant is None and not self.request.user.is_superuser:
            raise ValidationError({"tenant": ["Tenant não encontrado para o usuário."]})

        if not (
            self.request.user.is_superuser
            or self.request.user.has_staff_role(
                TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
            )
        ):
            raise PermissionDenied(
                "Apenas owner ou manager podem criar itens de estoque."
            )

        serializer.save(tenant=tenant)

        logger.info(
            "Inventory item created successfully",
            extra={
                "inventory_item_id": serializer.instance.id,
                "tenant_id": getattr(tenant, "id", None),
                "user_id": self.request.user.id,
                "item_name": serializer.instance.name,
            },
        )

    def perform_destroy(self, instance):
        if not (
            self.request.user.is_superuser
            or self.request.user.has_staff_role(
                TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
            )
        ):
            raise PermissionDenied(
                "Apenas owner ou manager podem remover itens de estoque."
            )

        logger.info(
            "Inventory item deleted",
            extra={
                "inventory_item_id": instance.id,
                "tenant_id": instance.tenant_id,
                "user_id": self.request.user.id,
            },
        )
        instance.delete()

    def get_object(self):
        # Usa o get_queryset() do TenantIsolatedMixin (já escopado por tenant)
        # em vez de InventoryItem.objects.all(), para que retrieve/update/
        # destroy tenham o mesmo isolamento que list/create.
        queryset = self.filter_queryset(self.get_queryset())
        return get_object_or_404(
            queryset, pk=self.kwargs.get(self.lookup_field, self.kwargs.get("pk"))
        )


class InventoryAlertListView(TenantIsolatedMixin, ListAPIView):
    """Itens de estoque abaixo do mínimo configurado (BE-STOCK-04, #467).

    Retorna apenas itens do tenant autenticado com `minimum_quantity`
    definido (não nulo) e maior que zero, cuja `quantity` atual está no
    mínimo ou abaixo dele. Itens sem mínimo configurado (0 ou null) nunca
    aparecem — não há como "alertar" sobre um limite que não foi definido.

    Endpoint de leitura, disponível a qualquer staff autenticado do tenant
    (mesmo padrão de `list` em `InventoryItemViewSet`). Sem gate de plano —
    decisão de escopo revisada em relação à issue original (que previa
    exclusividade do plano Pro, hoje bloqueado/não vendável).
    """

    queryset = InventoryItem.objects.all()
    serializer_class = InventoryItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(
            minimum_quantity__isnull=False,
            minimum_quantity__gt=0,
            quantity__lte=F("minimum_quantity"),
        )


class StockMovementViewSet(
    TenantIsolatedMixin, ListModelMixin, CreateModelMixin, GenericViewSet
):
    """Histórico de movimentações de estoque (BE-STOCK-03, #466).

    Log imutável: apenas `list` e `create` são expostos (sem update/delete),
    para que uma movimentação já registrada nunca seja alterada. Ao criar,
    o próprio model (`StockMovement.save`) atualiza `InventoryItem.quantity`
    e rejeita saídas que deixariam o saldo negativo.

    Permissões:
    - list: qualquer staff autenticado do tenant.
    - create: apenas owner ou manager (mesmo padrão de `InventoryItemViewSet`,
      já que afeta o saldo de estoque).

    Sem gate de plano: disponível a todos os tenants (decisão de escopo,
    ver docstring de `StockMovement`).
    """

    queryset = StockMovement.objects.select_related("item").all()
    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated]

    def _resolve_tenant(self):
        # Mesmo padrão do InventoryItemViewSet: tenant só a partir de
        # request.tenant/request.user.tenant, nunca de header/query-param.
        return getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )

    def perform_create(self, serializer):
        tenant = self._resolve_tenant()
        if tenant is None and not self.request.user.is_superuser:
            raise ValidationError({"tenant": ["Tenant não encontrado para o usuário."]})

        if not (
            self.request.user.is_superuser
            or self.request.user.has_staff_role(
                TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
            )
        ):
            raise PermissionDenied(
                "Apenas owner ou manager podem registrar movimentações de estoque."
            )

        item = serializer.validated_data.get("item")
        if item is not None and item.tenant_id != getattr(tenant, "id", None):
            raise ValidationError({"item": ["Item não encontrado para este tenant."]})

        serializer.save(tenant=tenant)

        logger.info(
            "Stock movement created successfully",
            extra={
                "stock_movement_id": serializer.instance.id,
                "tenant_id": getattr(tenant, "id", None),
                "user_id": self.request.user.id,
                "item_id": serializer.instance.item_id,
                "movement_type": serializer.instance.movement_type,
                "quantity": serializer.instance.quantity,
            },
        )
