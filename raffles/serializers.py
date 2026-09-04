from rest_framework import serializers

from core.models import Service
from raffles.models import Raffle
from vouchers.models import Voucher
from vouchers.serializers import ClientVoucherSerializer


class RaffleSerializer(serializers.ModelSerializer):
    """Serializer de sorteio (BE-RAFFLE-01, #475).

    `tenant`, `status`, `winner` e `winner_voucher` nunca são aceites via
    payload de create/update — são sempre geridos pela view (`tenant` a
    partir do request autenticado, os demais só através de
    `POST .../draw/`). `participants` é somente leitura aqui (lista de ids)
    — a atribuição é feita via `POST .../add-participants/`, mesmo padrão
    de `ClientVoucherSerializer`/`VoucherViewSet.assign` não aceitarem
    atribuição direta pelo serializer principal.
    """

    participants = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    winner_voucher = ClientVoucherSerializer(read_only=True)

    class Meta:
        model = Raffle
        fields = [
            "id",
            "name",
            "prize_description",
            "prize_voucher_type",
            "prize_value",
            "prize_service",
            "status",
            "participants",
            "winner",
            "winner_voucher",
            "drawn_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "participants",
            "winner",
            "winner_voucher",
            "drawn_at",
            "created_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = self._resolve_tenant()
        if tenant is not None:
            self.fields["prize_service"].queryset = Service.objects.filter(
                tenant=tenant
            )

    def _resolve_tenant(self):
        request = self.context.get("request")
        if request is None:
            return None
        return getattr(request, "tenant", None) or getattr(
            getattr(request, "user", None), "tenant", None
        )

    def validate(self, attrs):
        prize_voucher_type = attrs.get(
            "prize_voucher_type", getattr(self.instance, "prize_voucher_type", None)
        )
        prize_service = attrs.get(
            "prize_service", getattr(self.instance, "prize_service", None)
        )
        prize_value = attrs.get(
            "prize_value", getattr(self.instance, "prize_value", None)
        )

        if prize_voucher_type == Voucher.VoucherType.FREE_SERVICE:
            if prize_service is None:
                raise serializers.ValidationError(
                    {
                        "prize_service": "Obrigatório para prêmios do tipo 'free_service'."
                    }
                )
        elif prize_value is None:
            raise serializers.ValidationError(
                {"prize_value": "Obrigatório para prêmios do tipo 'percent'/'fixed'."}
            )

        return attrs


class RaffleAddParticipantsSerializer(serializers.Serializer):
    """Payload de entrada para `POST /api/raffles/{id}/add-participants/`.

    Aceita `client_ids` (lista de ids de `SalonCustomer`) e/ou `all=true`
    (adiciona todos os clientes do tenant do sorteio). Ao menos um dos dois
    precisa ser informado.
    """

    client_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("all") and not attrs.get("client_ids"):
            raise serializers.ValidationError("Informe 'client_ids' ou 'all': true.")
        return attrs
