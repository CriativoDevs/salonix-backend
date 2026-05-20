from django.contrib import admin
from django.utils.html import format_html
from cms.models import PublicPage, PageSEO


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
