"""
Sistema de feature flags e permissions baseado em planos.
"""

from functools import wraps
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.response import Response


class RequiresFeatureFlag(BasePermission):
    """
    Permission que verifica se o tenant tem uma feature flag habilitada.
    """

    def __init__(self, feature_flag, error_message=None):
        self.feature_flag = feature_flag
        self.error_message = (
            error_message or f"Feature '{feature_flag}' não habilitada para este plano."
        )

    def has_permission(self, request, view):
        """Verifica se o tenant do usuário tem a feature flag habilitada"""
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return False

        if not hasattr(request.user, "tenant") or not request.user.tenant:
            return False

        tenant = request.user.tenant

        # Verificar diferentes tipos de feature flags
        if self.feature_flag == "reports":
            return tenant.can_use_reports()
        elif self.feature_flag == "pwa_client":
            return tenant.can_use_pwa_client()
        elif self.feature_flag == "white_label":
            return tenant.can_use_white_label()
        elif self.feature_flag == "native_apps":
            return tenant.can_use_native_apps()
        elif self.feature_flag == "advanced_notifications":
            return tenant.can_use_advanced_notifications()
        elif self.feature_flag == "sms":
            return tenant.sms_enabled and tenant.can_use_advanced_notifications()
        elif self.feature_flag == "whatsapp":
            return tenant.whatsapp_enabled and tenant.can_use_advanced_notifications()

        # Feature flags específicas
        feature_map = {
            "push_web": tenant.push_web_enabled,
            "push_mobile": tenant.push_mobile_enabled,
            "pwa_admin": tenant.pwa_admin_enabled,
            "rn_admin": tenant.rn_admin_enabled,
            "rn_client": tenant.rn_client_enabled,
        }

        return feature_map.get(self.feature_flag, False)


def requires_feature_flag(feature_flag, error_message=None):
    """
    Decorator para views que requer uma feature flag específica.

    Usage:
        @requires_feature_flag('reports')
        def my_view(request):
            ...
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            permission = RequiresFeatureFlag(feature_flag, error_message)

            if not permission.has_permission(request, None):
                error_msg = (
                    error_message
                    or f"Feature '{feature_flag}' não habilitada para este plano."
                )
                raise PermissionDenied(error_msg)

            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator


def requires_plan(min_plan, error_message=None):
    """
    Decorator que requer um plano mínimo.

    Usage:
        @requires_plan('standard')
        def my_view(request):
            ...
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not hasattr(request, "user") or not request.user.is_authenticated:
                raise PermissionDenied("Usuário não autenticado.")

            if not hasattr(request.user, "tenant") or not request.user.tenant:
                raise PermissionDenied("Usuário não possui tenant associado.")

            tenant = request.user.tenant
            plan_hierarchy = {
                "basic": 0,
                "standard": 1,
                "pro": 2,
            }

            current_plan_level = plan_hierarchy.get(tenant.plan_tier, 0)
            required_plan_level = plan_hierarchy.get(min_plan, 0)

            if current_plan_level < required_plan_level:
                error_msg = (
                    error_message
                    or f"Esta funcionalidade requer plano {min_plan.title()} ou superior."
                )
                raise PermissionDenied(error_msg)

            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator


class RequiresPlan(BasePermission):
    """
    Permission que verifica se o tenant tem um plano mínimo.
    """

    def __init__(self, min_plan, error_message=None):
        self.min_plan = min_plan
        self.error_message = (
            error_message
            or f"Esta funcionalidade requer plano {min_plan.title()} ou superior."
        )

    def has_permission(self, request, view):
        """Verifica se o tenant tem o plano mínimo necessário"""
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return False

        if not hasattr(request.user, "tenant") or not request.user.tenant:
            return False

        tenant = request.user.tenant
        plan_hierarchy = {
            "basic": 0,
            "standard": 1,
            "pro": 2,
        }

        current_plan_level = plan_hierarchy.get(tenant.plan_tier, 0)
        required_plan_level = plan_hierarchy.get(self.min_plan, 0)

        return current_plan_level >= required_plan_level


def check_feature_flag(tenant, feature_flag):
    """
    Função utilitária para verificar feature flags.

    Args:
        tenant: Instância do Tenant
        feature_flag: String com nome da feature flag

    Returns:
        bool: True se a feature está habilitada
    """
    if not tenant:
        return False

    # Verificações baseadas em métodos do modelo
    if feature_flag == "reports":
        return tenant.can_use_reports()
    elif feature_flag == "pwa_client":
        return tenant.can_use_pwa_client()
    elif feature_flag == "white_label":
        return tenant.can_use_white_label()
    elif feature_flag == "native_apps":
        return tenant.can_use_native_apps()
    elif feature_flag == "advanced_notifications":
        return tenant.can_use_advanced_notifications()

    # Feature flags diretas
    feature_map = {
        "push_web": tenant.push_web_enabled,
        "push_mobile": tenant.push_mobile_enabled,
        "sms": tenant.sms_enabled,
        "whatsapp": tenant.whatsapp_enabled,
        "pwa_admin": tenant.pwa_admin_enabled,
        "rn_admin": tenant.rn_admin_enabled,
        "rn_client": tenant.rn_client_enabled,
    }

    return feature_map.get(feature_flag, False)


def get_tenant_feature_summary(tenant):
    """
    Retorna um resumo das features disponíveis para um tenant.

    Args:
        tenant: Instância do Tenant

    Returns:
        dict: Resumo das features
    """
    if not tenant:
        return {}

    return {
        "plan_tier": tenant.plan_tier,
        "available_features": {
            "reports": check_feature_flag(tenant, "reports"),
            "pwa_client": check_feature_flag(tenant, "pwa_client"),
            "white_label": check_feature_flag(tenant, "white_label"),
            "native_apps": check_feature_flag(tenant, "native_apps"),
            "advanced_notifications": check_feature_flag(
                tenant, "advanced_notifications"
            ),
            "push_web": check_feature_flag(tenant, "push_web"),
            "push_mobile": check_feature_flag(tenant, "push_mobile"),
            "sms": check_feature_flag(tenant, "sms"),
            "whatsapp": check_feature_flag(tenant, "whatsapp"),
        },
        "enabled_notification_channels": tenant.get_enabled_notification_channels(),
    }
