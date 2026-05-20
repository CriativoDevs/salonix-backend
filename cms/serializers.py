from rest_framework import serializers
from cms.models import PublicPage, PageSEO


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
