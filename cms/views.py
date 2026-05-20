from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny

from cms.models import PublicPage, RoadmapItem
from cms.serializers import PublicPageListSerializer, PublicPageDetailSerializer, RoadmapItemSerializer


class PublicPageListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = PublicPageListSerializer

    def get_queryset(self):
        return PublicPage.objects.filter(status=PublicPage.STATUS_PUBLISHED)


class PublicPageDetailView(RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = PublicPageDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return PublicPage.objects.filter(status=PublicPage.STATUS_PUBLISHED)


class RoadmapListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = RoadmapItemSerializer

    def get_queryset(self):
        return RoadmapItem.objects.filter(is_visible=True)
