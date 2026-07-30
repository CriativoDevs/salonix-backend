from django.conf import settings
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from platform_comms.models import PlatformAnnouncement
from platform_comms.serializers import PlatformAnnouncementSerializer


class PlatformAnnouncementListView(generics.ListAPIView):
    """
    GET /api/platform/announcements/

    Lista os comunicados da plataforma ativos (publicados, dentro da janela de
    exibição, no ambiente atual) e segmentados para o tenant do usuário
    autenticado. Nunca retorna comunicados de outros tenants.
    """

    serializer_class = PlatformAnnouncementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # Prioriza o tenant do usuário autenticado: é a fonte mais confiável
        # (request.tenant depende de middleware que pode não estar presente
        # em todos os contextos, ex.: testes que fixam request.tenant a um
        # tenant "default" independentemente do usuário autenticado).
        tenant = getattr(user, "tenant", None) or getattr(self.request, "tenant", None)
        if tenant is None:
            return PlatformAnnouncement.objects.none()

        environment = getattr(settings, "ENV", "dev")
        return PlatformAnnouncement.objects.active_for_tenant(
            tenant, environment=environment
        )
