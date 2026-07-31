import logging

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from core.mixins import TenantIsolatedMixin
from users.models import TenantStaffMember
from vouchers.models import Voucher
from vouchers.serializers import VoucherSerializer

logger = logging.getLogger(__name__)


class VoucherViewSet(TenantIsolatedMixin, ModelViewSet):
    """CRUD de vouchers do tenant (BE-VOUCHER-01, #470).

    Permissões:
    - list/retrieve: qualquer staff autenticado do tenant.
    - create/update/partial_update/destroy: apenas owner ou manager do
      tenant (diferente de `InventoryItemViewSet`, onde update é liberado
      a qualquer staff — aqui a issue pede explicitamente owner/manager
      também para edição, já que vouchers afetam receita/descontos).
    """

    queryset = Voucher.objects.select_related("service").all()
    serializer_class = VoucherSerializer
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

    def _require_owner_or_manager(self, action_description: str):
        if not (
            self.request.user.is_superuser
            or self.request.user.has_staff_role(
                TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
            )
        ):
            raise PermissionDenied(
                f"Apenas owner ou manager podem {action_description}."
            )

    def perform_create(self, serializer):
        tenant = self._resolve_tenant()
        if tenant is None and not self.request.user.is_superuser:
            raise ValidationError({"tenant": ["Tenant não encontrado para o usuário."]})

        self._require_owner_or_manager("criar vouchers")

        serializer.save(tenant=tenant)

        logger.info(
            "Voucher created successfully",
            extra={
                "voucher_id": serializer.instance.id,
                "tenant_id": getattr(tenant, "id", None),
                "user_id": self.request.user.id,
                "voucher_code": serializer.instance.code,
            },
        )

    def perform_update(self, serializer):
        self._require_owner_or_manager("editar vouchers")
        serializer.save()

        logger.info(
            "Voucher updated successfully",
            extra={
                "voucher_id": serializer.instance.id,
                "tenant_id": serializer.instance.tenant_id,
                "user_id": self.request.user.id,
            },
        )

    def perform_destroy(self, instance):
        self._require_owner_or_manager("remover vouchers")

        logger.info(
            "Voucher deleted",
            extra={
                "voucher_id": instance.id,
                "tenant_id": instance.tenant_id,
                "user_id": self.request.user.id,
            },
        )
        instance.delete()

    def get_object(self):
        # Usa o get_queryset() do TenantIsolatedMixin (já escopado por tenant)
        # em vez de Voucher.objects.all(), para que retrieve/update/destroy
        # tenham o mesmo isolamento que list/create.
        queryset = self.filter_queryset(self.get_queryset())
        return get_object_or_404(
            queryset, pk=self.kwargs.get(self.lookup_field, self.kwargs.get("pk"))
        )
