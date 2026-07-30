from rest_framework import serializers

from platform_comms.models import PlatformAnnouncement


class PlatformAnnouncementSerializer(serializers.ModelSerializer):
    """Serializer de leitura para as apps (web/pwa/mobile).

    Expõe apenas os campos de conteúdo/classificação — nada de segmentação
    interna (tenants, target_plans, environments) para não vazar detalhes de
    configuração da plataforma.
    """

    type_display = serializers.CharField(source="get_announcement_type_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)

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
        ]
        read_only_fields = fields
