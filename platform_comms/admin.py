from django.contrib import admin

from platform_comms.models import PlatformAnnouncement


@admin.register(PlatformAnnouncement)
class PlatformAnnouncementAdmin(admin.ModelAdmin):
    """Admin para comunicados da plataforma (superuser/OPS).

    Permite publicar comunicados segmentados por tenant, plano ou ambiente,
    com janela de exibição (publish_at/expire_at).
    """

    list_display = (
        "title",
        "announcement_type",
        "priority",
        "status",
        "audience_scope",
        "publish_at",
        "expire_at",
        "created_by",
    )
    list_filter = (
        "status",
        "announcement_type",
        "priority",
        "audience_scope",
        "created_at",
    )
    search_fields = ("title", "body")
    filter_horizontal = ("tenants",)
    readonly_fields = ("created_by", "created_at", "updated_at")
    date_hierarchy = "publish_at"
    actions = ["publish_announcements", "archive_announcements"]

    fieldsets = (
        ("Conteúdo", {"fields": ("title", "body", "announcement_type", "priority")}),
        ("Status e janela de exibição", {"fields": ("status", "publish_at", "expire_at")}),
        (
            "Segmentação",
            {"fields": ("audience_scope", "tenants", "target_plans", "environments")},
        ),
        (
            "Metadados",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Publicar comunicados selecionados")
    def publish_announcements(self, request, queryset):
        updated = queryset.update(status=PlatformAnnouncement.STATUS_PUBLISHED)
        self.message_user(request, f"{updated} comunicado(s) publicado(s).")

    @admin.action(description="Arquivar comunicados selecionados")
    def archive_announcements(self, request, queryset):
        updated = queryset.update(status=PlatformAnnouncement.STATUS_ARCHIVED)
        self.message_user(request, f"{updated} comunicado(s) arquivado(s).")
