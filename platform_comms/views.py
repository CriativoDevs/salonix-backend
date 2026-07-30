from django.conf import settings
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_comms.models import PlatformAnnouncement, PlatformAnnouncementReceipt
from platform_comms.serializers import (
    PlatformAnnouncementReceiptSerializer,
    PlatformAnnouncementSerializer,
)


def _resolve_tenant(request):
    # Prioriza o tenant do usuário autenticado: é a fonte mais confiável
    # (request.tenant depende de middleware que pode não estar presente
    # em todos os contextos, ex.: testes que fixam request.tenant a um
    # tenant "default" independentemente do usuário autenticado).
    user = request.user
    return getattr(user, "tenant", None) or getattr(request, "tenant", None)


class PlatformAnnouncementListView(generics.ListAPIView):
    """
    GET /api/platform/announcements/

    Lista os comunicados da plataforma ativos (publicados, dentro da janela de
    exibição, no ambiente atual) e segmentados para o tenant do usuário
    autenticado. Nunca retorna comunicados de outros tenants.

    Cada comunicado retornado é marcado como "delivered" (BE-PLATFORM-02) para
    o usuário autenticado, de forma lazy: o receipt só é criado quando o
    usuário efetivamente lista o inbox, não no momento da publicação.
    """

    serializer_class = PlatformAnnouncementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        tenant = _resolve_tenant(self.request)
        if tenant is None:
            return PlatformAnnouncement.objects.none()

        environment = getattr(settings, "ENV", "dev")
        user = self.request.user
        return PlatformAnnouncement.objects.active_for_tenant(
            tenant, environment=environment
        ).prefetch_related(
            Prefetch(
                "receipts",
                queryset=PlatformAnnouncementReceipt.objects.filter(user=user),
                to_attr="user_receipts",
            )
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        self._mark_delivered(queryset)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def _mark_delivered(self, queryset):
        tenant = _resolve_tenant(self.request)
        if tenant is None:
            return
        user = self.request.user
        existing_ids = set(
            PlatformAnnouncementReceipt.objects.filter(
                user=user, announcement__in=queryset
            ).values_list("announcement_id", flat=True)
        )
        new_receipts = [
            PlatformAnnouncementReceipt(announcement=announcement, user=user, tenant=tenant)
            for announcement in queryset
            if announcement.pk not in existing_ids
        ]
        if new_receipts:
            PlatformAnnouncementReceipt.objects.bulk_create(
                new_receipts, ignore_conflicts=True
            )


class PlatformAnnouncementReceiptActionView(APIView):
    """Base para as ações de marcar lido/não lido/dispensado de um comunicado.

    Só permite agir sobre comunicados dentro do escopo ativo do tenant do
    usuário autenticado (mesma regra de `active_for_tenant` usada na listagem)
    — evita que um usuário altere o próprio estado de leitura de um
    comunicado que nunca deveria ter visto, o que vazaria a existência dele.
    """

    permission_classes = [IsAuthenticated]

    def get_announcement(self, pk):
        tenant = _resolve_tenant(self.request)
        if tenant is None:
            return None
        environment = getattr(settings, "ENV", "dev")
        queryset = PlatformAnnouncement.objects.active_for_tenant(
            tenant, environment=environment
        )
        return get_object_or_404(queryset, pk=pk)

    def get_or_create_receipt(self, announcement):
        tenant = _resolve_tenant(self.request)
        receipt, _ = PlatformAnnouncementReceipt.objects.get_or_create(
            announcement=announcement,
            user=self.request.user,
            defaults={"tenant": tenant},
        )
        return receipt

    def respond(self, receipt):
        serializer = PlatformAnnouncementReceiptSerializer(receipt)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PlatformAnnouncementMarkReadView(PlatformAnnouncementReceiptActionView):
    """POST /api/platform/announcements/<pk>/read/"""

    def post(self, request, pk):
        announcement = self.get_announcement(pk)
        receipt = self.get_or_create_receipt(announcement)
        receipt.mark_read()
        return self.respond(receipt)


class PlatformAnnouncementMarkUnreadView(PlatformAnnouncementReceiptActionView):
    """POST /api/platform/announcements/<pk>/unread/"""

    def post(self, request, pk):
        announcement = self.get_announcement(pk)
        receipt = self.get_or_create_receipt(announcement)
        receipt.mark_unread()
        return self.respond(receipt)


class PlatformAnnouncementMarkDismissedView(PlatformAnnouncementReceiptActionView):
    """POST /api/platform/announcements/<pk>/dismiss/"""

    def post(self, request, pk):
        announcement = self.get_announcement(pk)
        receipt = self.get_or_create_receipt(announcement)
        receipt.mark_dismissed()
        return self.respond(receipt)


class PlatformAnnouncementUnreadCountView(APIView):
    """
    GET /api/platform/announcements/unread-count/

    Conta quantos comunicados ativos (dentro do escopo do tenant do usuário)
    ainda não foram lidos nem dispensados. Usado para o badge do inbox.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = _resolve_tenant(request)
        if tenant is None:
            return Response({"unread_count": 0})

        environment = getattr(settings, "ENV", "dev")
        active_ids = list(
            PlatformAnnouncement.objects.active_for_tenant(
                tenant, environment=environment
            ).values_list("id", flat=True)
        )
        if not active_ids:
            return Response({"unread_count": 0})

        handled_ids = set(
            PlatformAnnouncementReceipt.objects.filter(
                user=request.user,
                announcement_id__in=active_ids,
                status__in=[
                    PlatformAnnouncementReceipt.STATUS_READ,
                    PlatformAnnouncementReceipt.STATUS_DISMISSED,
                ],
            ).values_list("announcement_id", flat=True)
        )
        unread_count = len(set(active_ids) - handled_ids)
        return Response({"unread_count": unread_count})
