from rest_framework import serializers

from platform_comms.models import PlatformAnnouncement, PlatformAnnouncementReceipt


class PlatformAnnouncementSerializer(serializers.ModelSerializer):
    """Serializer de leitura para as apps (web/pwa/mobile).

    Expõe apenas os campos de conteúdo/classificação — nada de segmentação
    interna (tenants, target_plans, environments) para não vazar detalhes de
    configuração da plataforma. `is_read`/`read_at` refletem o receipt do
    usuário autenticado (BE-PLATFORM-02), populado via `Prefetch` na view
    para evitar N+1.
    """

    type_display = serializers.CharField(source="get_announcement_type_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    is_read = serializers.SerializerMethodField()
    read_at = serializers.SerializerMethodField()

    class Meta:
        model = PlatformAnnouncement
        fields = [
            "id",
            "title",
            "body",
            "announcement_type",
            "type_display",
            "priority",
            "priority_display",
            "publish_at",
            "expire_at",
            "is_read",
            "read_at",
        ]
        read_only_fields = fields

    def _user_receipt(self, obj):
        receipts = getattr(obj, "user_receipts", None)
        if receipts:
            return receipts[0]
        return None

    def get_is_read(self, obj) -> bool:
        receipt = self._user_receipt(obj)
        return bool(receipt and receipt.status == PlatformAnnouncementReceipt.STATUS_READ)

    def get_read_at(self, obj):
        receipt = self._user_receipt(obj)
        return receipt.read_at if receipt else None


class PlatformAnnouncementReceiptSerializer(serializers.ModelSerializer):
    """Serializer de escrita/leitura para as ações de marcar lido/não lido/dispensado."""

    class Meta:
        model = PlatformAnnouncementReceipt
        fields = [
            "id",
            "announcement",
            "status",
            "delivered_at",
            "read_at",
            "dismissed_at",
            "updated_at",
        ]
        read_only_fields = fields
