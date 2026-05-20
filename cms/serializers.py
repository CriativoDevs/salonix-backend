from rest_framework import serializers
from cms.models import PublicPage, PageSEO, RoadmapItem


class PageSEOSerializer(serializers.ModelSerializer):
    class Meta:
        model = PageSEO
        fields = ["meta_title", "meta_description"]


class PublicPageListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PublicPage
        fields = ["slug", "title", "summary", "image", "published_at"]


class PublicPageDetailSerializer(serializers.ModelSerializer):
    seo = PageSEOSerializer(read_only=True)

    class Meta:
        model = PublicPage
        fields = ["slug", "title", "summary", "content", "image", "published_at", "seo"]


class RoadmapItemSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = RoadmapItem
        fields = ["title", "description", "status", "status_display", "order"]
