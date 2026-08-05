import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.mixins import TenantIsolatedMixin
from core.models import SalonCustomer
from users.models import TenantStaffMember
from vouchers.models import ClientVoucher, Voucher
from vouchers.serializers import (
    ClientVoucherSerializer,
    VoucherAssignSerializer,
    VoucherSerializer,
)
from vouchers.tasks import send_voucher_email_task

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

    def _get_client_in_tenant(self, voucher, client_id):
        # O cliente precisa pertencer ao mesmo tenant do voucher — busca
        # escopada ao tenant do voucher (nunca `SalonCustomer.objects.get`
        # direto, que permitiria atribuir/enviar a cliente de outro
        # tenant/IDOR).
        try:
            return SalonCustomer.objects.get(id=client_id, tenant=voucher.tenant)
        except SalonCustomer.DoesNotExist:
            raise ValidationError(
                {"client_id": ["Cliente não encontrado para este tenant."]}
            )

    def _assign_voucher_to_client(self, voucher, client) -> ClientVoucher:
        """Cria o `ClientVoucher`, respeitando duplicidade e `max_uses`
        (BE-VOUCHER-02, #471). Reaproveitado por `assign` e por `send_email`
        (BE-VOUCHER-04, #473) para não duplicar a lógica de atribuição.
        """
        if ClientVoucher.objects.filter(voucher=voucher, client=client).exists():
            raise ValidationError(
                {"client_id": ["Este voucher já foi atribuído a este cliente."]}
            )

        current_assignments = ClientVoucher.objects.filter(voucher=voucher).count()
        if current_assignments >= voucher.max_uses:
            raise ValidationError(
                {"voucher": ["Limite de atribuições (max_uses) atingido para este voucher."]}
            )

        return ClientVoucher.objects.create(
            tenant=voucher.tenant, voucher=voucher, client=client
        )

    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        """Atribui o voucher a um cliente do mesmo tenant (BE-VOUCHER-02, #471).

        Restrito a owner/manager, como create/update — atribuição de voucher
        afeta receita/descontos, mesmo critério já aplicado ao resto do
        `VoucherViewSet`. Rejeita atribuição duplicada ao mesmo cliente e
        respeita `max_uses`.
        """
        self._require_owner_or_manager("atribuir vouchers")

        voucher = self.get_object()

        input_serializer = VoucherAssignSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        client_id = input_serializer.validated_data["client_id"]

        client = self._get_client_in_tenant(voucher, client_id)
        client_voucher = self._assign_voucher_to_client(voucher, client)

        logger.info(
            "Voucher assigned to client",
            extra={
                "voucher_id": voucher.id,
                "client_id": client.id,
                "tenant_id": voucher.tenant_id,
                "user_id": self.request.user.id,
            },
        )

        return Response(
            ClientVoucherSerializer(client_voucher).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="send-email")
    def send_email(self, request, pk=None):
        """Envia o voucher por e-mail a um cliente do tenant (BE-VOUCHER-04, #473).

        Restrito a owner/manager, mesmo critério de `assign`/`create`/
        `update` — envolve comunicação com o cliente sobre voucher/desconto.

        Atribui o voucher ao cliente (reaproveitando `_assign_voucher_to_client`,
        a mesma lógica de `assign`) caso ainda não esteja atribuído — não
        duplica a atribuição em reenvios. O disparo do e-mail em si é sempre
        assíncrono (task Celery, `send_voucher_email_task`) e pode ser
        acionado novamente deliberadamente (ex.: cliente perdeu o e-mail),
        mesmo que `sent_at` já esteja preenchido — reenvio não é bloqueado,
        só a atribuição duplicada é.
        """
        self._require_owner_or_manager("enviar vouchers por email")

        voucher = self.get_object()

        input_serializer = VoucherAssignSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        client_id = input_serializer.validated_data["client_id"]

        client = self._get_client_in_tenant(voucher, client_id)

        if not client.email:
            raise ValidationError(
                {"client_id": ["Cliente não tem e-mail cadastrado."]}
            )

        client_voucher = ClientVoucher.objects.filter(
            voucher=voucher, client=client
        ).first()
        if client_voucher is None:
            client_voucher = self._assign_voucher_to_client(voucher, client)

        send_voucher_email_task.delay(client_voucher.id)

        logger.info(
            "Voucher email dispatched",
            extra={
                "voucher_id": voucher.id,
                "client_id": client.id,
                "client_voucher_id": client_voucher.id,
                "tenant_id": voucher.tenant_id,
                "user_id": self.request.user.id,
            },
        )

        return Response(
            ClientVoucherSerializer(client_voucher).data,
            status=status.HTTP_202_ACCEPTED,
        )
