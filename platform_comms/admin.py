from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.utils.encoding import force_str

from platform_comms.models import PlatformAnnouncement, PlatformAnnouncementReceipt


def _log_announcement_action(request, obj, message: str):
    """Registra uma entrada em `django.contrib.admin.models.LogEntry` (auditoria).

    BE-PLATFORM-02: reutiliza o LogEntry embutido do Django (já usado pelo
    próprio Admin para add/change/delete via formulário) em vez de criar um
    model de auditoria dedicado — é suficiente para o critério de aceite
    (quem, quando, o quê) e evita duplicar infraestrutura. As edições feitas
    pelo formulário padrão do Admin (criar/editar um comunicado) já são
    logadas automaticamente pelo Django; esta função cobre as ações em massa
    (publicar/arquivar), que usam `save()` individual e por isso não
    disparam o log automático do changeform.
    """
    LogEntry.objects.log_action(
        user_id=request.user.pk,
        content_type_id=ContentType.objects.get_for_model(PlatformAnnouncement).pk,
        object_id=obj.pk,
        object_repr=force_str(obj),
        action_flag=CHANGE,
        change_message=message,
    )


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
        updated = 0
        for obj in queryset:
            obj.publish()
            environments = ", ".join(obj.environments) if obj.environments else "todos"
            _log_announcement_action(
                request,
                obj,
                f"Publicado via ação em massa (público: {obj.audience_scope} - "
                f"{obj.get_audience_scope_display()}; ambientes: {environments}).",
            )
            updated += 1
        self.message_user(request, f"{updated} comunicado(s) publicado(s).")

    @admin.action(description="Arquivar comunicados selecionados")
    def archive_announcements(self, request, queryset):
        updated = 0
        for obj in queryset:
            obj.archive()
            _log_announcement_action(
                request, obj, "Arquivado via ação em massa."
            )
            updated += 1
        self.message_user(request, f"{updated} comunicado(s) arquivado(s).")


@admin.register(PlatformAnnouncementReceipt)
class PlatformAnnouncementReceiptAdmin(admin.ModelAdmin):
    """Admin somente-leitura para suporte/OPS investigarem entrega/leitura (BE-PLATFORM-02).

    Não é editável via Admin: o estado é gerenciado pelas apps através dos
    endpoints de inbox. Existe aqui só para dar visibilidade de quem recebeu/
    leu/dispensou um comunicado, sem precisar de acesso a shell/DB.
    """

    list_display = (
        "announcement",
        "user",
        "tenant",
        "status",
        "delivered_at",
        "read_at",
        "dismissed_at",
    )
    list_filter = ("status", "tenant")
    search_fields = ("announcement__title", "user__username", "user__email")
    readonly_fields = (
        "announcement",
        "user",
        "tenant",
        "status",
        "delivered_at",
        "read_at",
        "dismissed_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
