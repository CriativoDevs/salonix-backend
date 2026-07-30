import logging

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from core.mixins import TenantIsolatedMixin
from inventory.models import InventoryItem
from inventory.serializers import InventoryItemSerializer
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
