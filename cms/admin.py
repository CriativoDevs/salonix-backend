from django.contrib import admin
from django.utils.html import format_html
from cms.models import PublicPage, PageSEO, RoadmapItem


class PageSEOInline(admin.StackedInline):
    model = PageSEO
    extra = 1
    max_num = 1


@admin.register(PublicPage)
class PublicPageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "status_badge", "published_at", "scheduled_publish_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("title", "slug", "summary")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("published_at", "created_at", "updated_at", "image_preview")
    actions = ["publish_pages", "unpublish_pages"]
    inlines = [PageSEOInline]

    fieldsets = (
        ("Conteudo", {
            "fields": ("title", "slug", "summary", "content"),
        }),
        ("Imagem", {
            "fields": ("image", "image_preview"),
        }),
        ("Publicacao", {
            "fields": ("status", "scheduled_publish_at", "published_at"),
        }),
        ("Datas", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def status_badge(self, obj):
        if obj.status == PublicPage.STATUS_PUBLISHED:
            return format_html('<span style="color:green;font-weight:bold;">Publicada</span>')
        return format_html('<span style="color:orange;">Draft</span>')

    status_badge.short_description = "Status"
    status_badge.admin_order_field = "status"

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height:200px;border-radius:4px;" />', obj.image.url)
        return "-"

    image_preview.short_description = "Preview"

    @admin.action(description="Publicar paginas selecionadas")
    def publish_pages(self, request, queryset):
        for page in queryset:
            page.publish()
        self.message_user(request, f"{queryset.count()} pagina(s) publicada(s).")

    @admin.action(description="Despublicar paginas selecionadas")
    def unpublish_pages(self, request, queryset):
        for page in queryset:
            page.unpublish()
        self.message_user(request, f"{queryset.count()} pagina(s) movida(s) para draft.")


@admin.register(RoadmapItem)
class RoadmapItemAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "order", "is_visible", "visible_badge", "updated_at")
    list_filter = ("status", "is_visible")
    search_fields = ("title", "description")
    list_editable = ("order", "is_visible")
    actions = ["make_visible", "make_hidden"]

    fieldsets = (
        ("Conteudo", {
            "fields": ("title", "description", "status"),
        }),
        ("Visibilidade e Ordem", {
            "fields": ("is_visible", "order"),
        }),
    )

    def visible_badge(self, obj):
        if obj.is_visible:
            return format_html('<span style="color:green;font-weight:bold;">Visivel</span>')
        return format_html('<span style="color:gray;">Oculto</span>')

    visible_badge.short_description = "Visibilidade"
    visible_badge.admin_order_field = "is_visible"

    @admin.action(description="Tornar visiveis os itens selecionados")
    def make_visible(self, request, queryset):
        queryset.update(is_visible=True)
        self.message_user(request, f"{queryset.count()} item(ns) marcado(s) como visivel.")

    @admin.action(description="Ocultar os itens selecionados")
    def make_hidden(self, request, queryset):
        queryset.update(is_visible=False)
        self.message_user(request, f"{queryset.count()} item(ns) ocultado(s).")
