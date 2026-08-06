from rest_framework import serializers

from core.models import Service
from vouchers.models import BirthdayVoucherConfig, ClientVoucher, Voucher


class VoucherSerializer(serializers.ModelSerializer):
    """Serializer de voucher (BE-VOUCHER-01, #470).

    `tenant` nunca é aceite via payload — é sempre atribuído pela view a
    partir do request autenticado (isolamento multi-tenant). `code` é
    opcional: se omitido, o próprio model gera um código único de 8
    caracteres ao salvar. `service` é restrito aos serviços do tenant do
    request, para evitar IDOR sobre serviços de outro tenant.
    """

    class Meta:
        model = Voucher
        fields = [
            "id",
            "code",
            "type",
            "value",
            "service",
            "max_uses",
            "valid_until",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"code": {"required": False}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = self._resolve_tenant()
        if tenant is not None:
            self.fields["service"].queryset = Service.objects.filter(tenant=tenant)

    def _resolve_tenant(self):
        request = self.context.get("request")
        if request is None:
            return None
        return getattr(request, "tenant", None) or getattr(
            getattr(request, "user", None), "tenant", None
        )

    def validate_code(self, value):
        return value.strip().upper() if value else value

    def validate(self, attrs):
        voucher_type = attrs.get(
            "type", getattr(self.instance, "type", None)
        )
        service = attrs.get(
            "service", getattr(self.instance, "service", None)
        )
        value = attrs.get("value", getattr(self.instance, "value", None))

        if voucher_type == Voucher.VoucherType.FREE_SERVICE:
            if service is None:
                raise serializers.ValidationError(
                    {"service": "Obrigatório para vouchers do tipo 'free_service'."}
                )
        elif value is None:
            raise serializers.ValidationError(
                {"value": "Obrigatório para vouchers do tipo 'percent'/'fixed'."}
            )

        code = attrs.get("code")
        if code:
            tenant = self._resolve_tenant()
            queryset = Voucher.objects.filter(tenant=tenant, code=code)
            if self.instance is not None:
                queryset = queryset.exclude(pk=self.instance.pk)
            if tenant is not None and queryset.exists():
                raise serializers.ValidationError(
                    {"code": "Já existe um voucher com este código."}
                )

        return attrs


class ClientVoucherSerializer(serializers.ModelSerializer):
    """Voucher atribuído a um cliente (BE-VOUCHER-02, #471).

    Somente leitura: a atribuição é criada via
    `VoucherViewSet.assign` (`POST /api/vouchers/{id}/assign/`), nunca
    diretamente por este serializer — por isso não expõe `client_id` como
    campo de escrita.
    """

    voucher_code = serializers.CharField(source="voucher.code", read_only=True)
    voucher_type = serializers.CharField(source="voucher.type", read_only=True)
    voucher_value = serializers.DecimalField(
        source="voucher.value", max_digits=10, decimal_places=2, read_only=True
    )
    status = serializers.CharField(read_only=True)

    class Meta:
        model = ClientVoucher
        fields = [
            "id",
            "voucher",
            "voucher_code",
            "voucher_type",
            "voucher_value",
            "client",
            "assigned_at",
            "used_at",
            "used_in_booking",
            "status",
        ]
        read_only_fields = fields


class VoucherAssignSerializer(serializers.Serializer):
    """Payload de entrada para `POST /api/vouchers/{id}/assign/`."""

    client_id = serializers.IntegerField()


class ApplyVoucherSerializer(serializers.Serializer):
    """Payload de entrada para `POST /api/salon/appointments/{id}/apply-voucher/`
    (BE-VOUCHER-03, #472).

    Identifica o voucher pelo `id` do `ClientVoucher` (a atribuição já
    existente ao cliente), não pelo `code` do `Voucher` nem por um novo
    `client_id` — o mesmo padrão já usado em `GET
    /api/customers/{id}/vouchers/`, que devolve esse `id` para o
    frontend escolher qual voucher aplicar. Evita uma segunda consulta
    por código/cliente e a ambiguidade de reaplicar um voucher expirado
    cujo código o operador digitou de memória.
    """

    client_voucher_id = serializers.IntegerField()


class BirthdayVoucherConfigSerializer(serializers.ModelSerializer):
    """Template do voucher automático de aniversário (BE-VOUCHER-05, #474).

    Cada tenant pode ter até `BirthdayVoucherConfig.MAX_TEMPLATES_PER_TENANT`
    templates salvos, com no máximo 1 `is_selected=True` por vez (o usado
    pelo job de envio). `tenant` nunca é aceite via payload — resolvido
    pela view a partir do request autenticado, mesmo padrão de
    `VoucherSerializer`. `service` é restrito aos serviços do tenant do
    request para evitar IDOR.
    """

    class Meta:
        model = BirthdayVoucherConfig
        fields = [
            "id",
            "voucher_type",
            "voucher_value",
            "service",
            "validity_days",
            "is_selected",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = self._resolve_tenant()
        if tenant is not None:
            self.fields["service"].queryset = Service.objects.filter(tenant=tenant)

    def _resolve_tenant(self):
        request = self.context.get("request")
        if request is None:
            return None
        return getattr(request, "tenant", None) or getattr(
            getattr(request, "user", None), "tenant", None
        )

    def validate(self, attrs):
        voucher_type = attrs.get(
            "voucher_type", getattr(self.instance, "voucher_type", None)
        )
        service = attrs.get("service", getattr(self.instance, "service", None))
        voucher_value = attrs.get(
            "voucher_value", getattr(self.instance, "voucher_value", None)
        )

        if voucher_type == Voucher.VoucherType.FREE_SERVICE:
            if service is None:
                raise serializers.ValidationError(
                    {"service": "Obrigatório para vouchers do tipo 'free_service'."}
                )
        elif voucher_value is None:
            raise serializers.ValidationError(
                {"voucher_value": "Obrigatório para vouchers do tipo 'percent'/'fixed'."}
            )

        if self.instance is None:
            tenant = self._resolve_tenant()
            if tenant is not None:
                existing_count = BirthdayVoucherConfig.objects.filter(
                    tenant=tenant
                ).count()
                if existing_count >= BirthdayVoucherConfig.MAX_TEMPLATES_PER_TENANT:
                    raise serializers.ValidationError(
                        {
                            "non_field_errors": [
                                "Cada tenant pode ter no máximo "
                                f"{BirthdayVoucherConfig.MAX_TEMPLATES_PER_TENANT} "
                                "templates de voucher de aniversário."
                            ]
                        }
                    )

        return attrs
