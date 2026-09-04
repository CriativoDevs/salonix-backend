import logging
import secrets

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.mixins import TenantIsolatedMixin
from core.models import SalonCustomer
from raffles.models import Raffle
from raffles.serializers import RaffleAddParticipantsSerializer, RaffleSerializer
from users.models import TenantStaffMember
from vouchers.models import ClientVoucher, Voucher

logger = logging.getLogger(__name__)


class RaffleViewSet(TenantIsolatedMixin, ModelViewSet):
    """CRUD de sorteios do tenant, com atribuição de participantes e
    execução do sorteio (BE-RAFFLE-01, #475).

    Permissões: mesmo critério de `VoucherViewSet` — list/retrieve para
    qualquer staff autenticado do tenant; create/update/destroy/
    add-participants/draw restritos a owner/manager, já que o sorteio gera
    automaticamente um voucher (afeta receita/descontos).
    """

    queryset = Raffle.objects.select_related(
        "prize_service", "winner", "winner_voucher"
    ).prefetch_related("participants")
    serializer_class = RaffleSerializer
    permission_classes = [IsAuthenticated]

    def _resolve_tenant(self):
        # Mesmo padrão de `VoucherViewSet`: tenant vem sempre da
        # sessão/membership do usuário autenticado, nunca de
        # header/query-param client-supplied.
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

    def get_object(self):
        # Usa o get_queryset() já escopado por tenant (TenantIsolatedMixin),
        # mesmo padrão de `VoucherViewSet.get_object`.
        queryset = self.filter_queryset(self.get_queryset())
        return get_object_or_404(
            queryset, pk=self.kwargs.get(self.lookup_field, self.kwargs.get("pk"))
        )

    def perform_create(self, serializer):
        tenant = self._resolve_tenant()
        if tenant is None and not self.request.user.is_superuser:
            raise ValidationError({"tenant": ["Tenant não encontrado para o usuário."]})

        self._require_owner_or_manager("criar sorteios")

        serializer.save(tenant=tenant)

        logger.info(
            "Raffle created",
            extra={
                "raffle_id": serializer.instance.id,
                "tenant_id": getattr(tenant, "id", None),
                "user_id": self.request.user.id,
            },
        )

    def perform_update(self, serializer):
        self._require_owner_or_manager("editar sorteios")
        serializer.save()

        logger.info(
            "Raffle updated",
            extra={
                "raffle_id": serializer.instance.id,
                "tenant_id": serializer.instance.tenant_id,
                "user_id": self.request.user.id,
            },
        )

    def perform_destroy(self, instance):
        self._require_owner_or_manager("remover sorteios")

        logger.info(
            "Raffle deleted",
            extra={
                "raffle_id": instance.id,
                "tenant_id": instance.tenant_id,
                "user_id": self.request.user.id,
            },
        )
        instance.delete()

    @action(detail=True, methods=["post"], url_path="add-participants")
    def add_participants(self, request, pk=None):
        """Adiciona participantes ao sorteio (BE-RAFFLE-01, #475).

        Aceita `client_ids` (lista de ids de `SalonCustomer` do mesmo
        tenant do sorteio) e/ou `all: true` (adiciona todos os clientes
        ativos do tenant). Rejeita clientes de outro tenant (IDOR) e
        qualquer alteração depois do sorteio já ter sido executado — nesse
        ponto a lista de participantes fica congelada, já que o vencedor
        já foi sorteado sobre ela.
        """
        self._require_owner_or_manager("adicionar participantes")

        raffle = self.get_object()

        if raffle.status != Raffle.Status.DRAFT:
            raise ValidationError(
                {
                    "status": [
                        "Não é possível alterar participantes de um sorteio já realizado."
                    ]
                }
            )

        input_serializer = RaffleAddParticipantsSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        client_ids = input_serializer.validated_data.get("client_ids") or []
        add_all = input_serializer.validated_data.get("all", False)

        if add_all:
            clients = SalonCustomer.objects.filter(
                tenant=raffle.tenant, is_active=True
            )
            raffle.participants.add(*clients)
        else:
            clients = list(
                SalonCustomer.objects.filter(id__in=client_ids, tenant=raffle.tenant)
            )
            found_ids = {client.id for client in clients}
            missing_ids = set(client_ids) - found_ids
            if missing_ids:
                raise ValidationError(
                    {
                        "client_ids": [
                            "Cliente(s) não encontrado(s) para este tenant: "
                            f"{sorted(missing_ids)}."
                        ]
                    }
                )
            raffle.participants.add(*clients)

        logger.info(
            "Raffle participants added",
            extra={
                "raffle_id": raffle.id,
                "tenant_id": raffle.tenant_id,
                "user_id": self.request.user.id,
                "participants_count": raffle.participants.count(),
            },
        )

        return Response(RaffleSerializer(raffle, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="draw")
    def draw(self, request, pk=None):
        """Executa o sorteio (BE-RAFFLE-01, #475).

        Só permitido em sorteios `draft` com ao menos 1 participante.
        Sorteia aleatoriamente (`secrets.choice`, não previsível/manipulável
        como o gerador padrão de `random`) 1 participante, gera um
        `Voucher` a partir dos dados de prêmio do sorteio e atribui ao
        vencedor via `ClientVoucher` (mesma lógica de
        `VoucherViewSet._assign_voucher_to_client`, mas sem checar
        duplicidade/max_uses aqui — o voucher é criado exclusivamente para
        este sorteio, sempre novo).

        Idempotência: sortear um sorteio já `drawn` retorna 400 sem
        recriar voucher nem trocar o vencedor — a verificação de status é
        feita antes de qualquer efeito colateral.
        """
        self._require_owner_or_manager("sortear")

        raffle = self.get_object()

        if raffle.status == Raffle.Status.DRAWN:
            raise ValidationError(
                {"status": ["Este sorteio já foi realizado e não pode ser repetido."]}
            )

        participants = list(raffle.participants.all())
        if not participants:
            raise ValidationError(
                {
                    "participants": [
                        "É necessário ao menos um participante para sortear."
                    ]
                }
            )

        winner = secrets.choice(participants)

        with transaction.atomic():
            voucher = Voucher.objects.create(
                tenant=raffle.tenant,
                type=raffle.prize_voucher_type,
                value=raffle.prize_value,
                service=raffle.prize_service,
                notes=f"Prêmio do sorteio '{raffle.name}'.",
            )
            client_voucher = ClientVoucher.objects.create(
                tenant=raffle.tenant, voucher=voucher, client=winner
            )
            raffle.winner = winner
            raffle.winner_voucher = client_voucher
            raffle.drawn_at = timezone.now()
            raffle.status = Raffle.Status.DRAWN
            raffle.save(
                update_fields=["winner", "winner_voucher", "drawn_at", "status"]
            )

        logger.info(
            "Raffle drawn",
            extra={
                "raffle_id": raffle.id,
                "tenant_id": raffle.tenant_id,
                "user_id": self.request.user.id,
                "winner_id": winner.id,
                "voucher_id": voucher.id,
            },
        )

        return Response(RaffleSerializer(raffle, context={"request": request}).data)
