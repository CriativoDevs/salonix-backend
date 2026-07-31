from rest_framework import serializers

from core.models import Service
from vouchers.models import Voucher


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
