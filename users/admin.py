from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.urls import reverse
from django.db import models
from django.forms import TextInput, Select
from .models import CustomUser, Tenant, UserFeatureFlags
from typing import Any, cast


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    """
    Admin personalizado para gestão de Tenants (Salões).
    """

    list_display = [
        "name",
        "slug",
        "plan_tier",
        "is_active",
        "users_count",
        "feature_summary",
        "created_at",
    ]
    list_filter = [
        "plan_tier",
        "is_active",
        "reports_enabled",
        "sms_enabled",
        "whatsapp_enabled",
        "created_at",
    ]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["created_at", "updated_at", "users_count", "feature_summary"]

    fieldsets = (
        (
            "Informações Básicas",
            {"fields": ("name", "slug", "is_active", "timezone", "currency")},
        ),
        ("Plano e Configurações", {"fields": ("plan_tier", "addons_enabled")}),
        (
            "Branding/White-label",
            {
                "fields": ("logo", "logo_url", "primary_color", "secondary_color"),
                "classes": ("collapse",),
            },
        ),
        (
            "Feature Flags - Módulos",
            {
                "fields": (
                    "reports_enabled",
                    "pwa_admin_enabled",
                    "pwa_client_enabled",
                    "rn_admin_enabled",
                    "rn_client_enabled",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Feature Flags - Notificações",
            {
                "fields": (
                    "push_web_enabled",
                    "push_mobile_enabled",
                    "sms_enabled",
                    "whatsapp_enabled",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Metadados",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "users_count",
                    "feature_summary",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    # Formulário personalizado para cores hex
    formfield_overrides = {
        models.CharField: {"widget": TextInput(attrs={"size": "10"})},
    }

    def users_count(self, obj):
        """Conta quantos usuários pertencem a este tenant."""
        count = obj.users.count()
        if count > 0:
            url = (
                reverse("admin:users_customuser_changelist")
                + f"?tenant__id__exact={obj.id}"
            )
            return format_html('<a href="{}">{} usuários</a>', url, count)
        return f"{count} usuários"

    users_count.short_description = "Usuários"

    def feature_summary(self, obj):
        """Resume as principais features ativas."""
        features = []
        if obj.reports_enabled or obj.can_use_reports():
            features.append("📊 Relatórios")
        if obj.sms_enabled:
            features.append("📱 SMS")
        if obj.whatsapp_enabled:
            features.append("💬 WhatsApp")
        if obj.can_use_white_label():
            features.append("🎨 White-label")
        if obj.can_use_native_apps():
            features.append("📲 Apps Nativos")

        return " | ".join(features) if features else "Recursos básicos"

    feature_summary.short_description = "Features Ativas"

    actions = ["activate_tenants", "deactivate_tenants", "upgrade_to_pro"]

    def activate_tenants(self, request, queryset):
        """Ativa tenants selecionados."""
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} tenant(s) ativado(s) com sucesso.")

    activate_tenants.short_description = "Ativar tenants selecionados"

    def deactivate_tenants(self, request, queryset):
        """Desativa tenants selecionados."""
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} tenant(s) desativado(s) com sucesso.")

    deactivate_tenants.short_description = "Desativar tenants selecionados"

    def upgrade_to_pro(self, request, queryset):
        """Upgrade para plano Pro com todas as features."""
        updated = queryset.update(
            plan_tier=Tenant.PLAN_PRO,
            reports_enabled=True,
            pwa_client_enabled=True,
            push_web_enabled=True,
            push_mobile_enabled=True,
        )
        self.message_user(request, f"{updated} tenant(s) upgradado(s) para Pro.")

    upgrade_to_pro.short_description = "Upgrade para plano Pro"


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """
    Admin personalizado para usuários com filtro por tenant.
    """

    model = CustomUser
    list_display = [
        "username",
        "email",
        "tenant_name",
        "salon_name",
        "ops_role",
        "is_staff",
        "is_active",
        "date_joined",
    ]
    list_filter = ["tenant", "ops_role", "is_staff", "is_active", "date_joined"]
    search_fields = ["username", "email", "salon_name", "tenant__name"]

    # Adicionar campos do tenant aos fieldsets
    base_fieldsets: list[Any] = list(UserAdmin.fieldsets or [])
    base_fieldsets.append(
        (
            "Informações do Salão",
            {"fields": ("tenant", "salon_name", "phone_number", "ops_role")},
        )
    )
    fieldsets = base_fieldsets

    def tenant_name(self, obj):
        """Exibe nome do tenant com link."""
        if obj.tenant:
            url = reverse("admin:users_tenant_change", args=[obj.tenant.pk])
            return format_html('<a href="{}">{}</a>', url, obj.tenant.name)
        return "-"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"


@admin.register(UserFeatureFlags)
class UserFeatureFlagsAdmin(admin.ModelAdmin):
    """
    Admin para feature flags de usuários (sistema legado).
    """

    list_display = [
        "user",
        "is_pro",
        "pro_status",
        "pro_plan",
        "reports_enabled",
        "sms_enabled",
        "updated_at",
    ]
    list_filter = [
        "is_pro",
        "pro_status",
        "pro_plan",
        "reports_enabled",
        "sms_enabled",
        "email_enabled",
    ]
    search_fields = ["user__username", "user__email"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Usuário", {"fields": ("user",)}),
        (
            "Plano Pro",
            {
                "fields": (
                    "is_pro",
                    "pro_status",
                    "pro_plan",
                    "pro_since",
                    "pro_until",
                    "trial_until",
                )
            },
        ),
        (
            "Módulos",
            {
                "fields": (
                    "sms_enabled",
                    "email_enabled",
                    "reports_enabled",
                    "audit_log_enabled",
                    "i18n_enabled",
                )
            },
        ),
        (
            "Metadados",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
