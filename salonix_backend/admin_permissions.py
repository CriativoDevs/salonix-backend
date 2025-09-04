from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from users.models import CustomUser, Tenant


class AdminPermissionMixin:
    """
    Mixin para adicionar controle de permissões nos admins.
    """

    def has_module_permission(self, request):
        """Verifica se o usuário pode acessar o módulo."""
        if request.user.is_superuser:
            return True

        # Staff pode ver apenas seus próprios dados
        return request.user.is_staff

    def get_queryset(self, request):
        """Filtra queryset baseado nas permissões do usuário."""
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Staff vê apenas dados do seu tenant
        if hasattr(self.model, "tenant") and request.user.tenant:
            return qs.filter(tenant=request.user.tenant)

        return qs

    def has_change_permission(self, request, obj=None):
        """Verifica permissão de edição."""
        if request.user.is_superuser:
            return True

        if not request.user.is_staff:
            return False

        # Staff só pode editar objetos do seu tenant
        if obj and hasattr(obj, "tenant"):
            return obj.tenant == request.user.tenant

        return True

    def has_delete_permission(self, request, obj=None):
        """Verifica permissão de exclusão."""
        if request.user.is_superuser:
            return True

        # Staff normalmente não pode deletar
        if not request.user.is_staff:
            return False

        # Apenas superuser pode deletar tenants e usuários
        if self.model in [Tenant, CustomUser]:
            return False

        # Staff pode deletar apenas objetos do seu tenant
        if obj and hasattr(obj, "tenant"):
            return obj.tenant == request.user.tenant

        return False

    def has_add_permission(self, request):
        """Verifica permissão de criação."""
        if request.user.is_superuser:
            return True

        if not request.user.is_staff:
            return False

        # Staff não pode criar tenants
        if self.model == Tenant:
            return False

        return True


def setup_admin_permissions():
    """
    Configura permissões personalizadas para o admin.
    """

    # Permissões customizadas
    custom_permissions = [
        {
            "codename": "view_all_tenants",
            "name": "Can view all tenants",
            "content_type": ContentType.objects.get_for_model(Tenant),
        },
        {
            "codename": "manage_tenant_features",
            "name": "Can manage tenant features",
            "content_type": ContentType.objects.get_for_model(Tenant),
        },
        {
            "codename": "view_system_stats",
            "name": "Can view system statistics",
            "content_type": ContentType.objects.get_for_model(Tenant),
        },
        {
            "codename": "manage_subscriptions",
            "name": "Can manage subscriptions",
            "content_type": ContentType.objects.get_for_model(Tenant),
        },
    ]

    for perm_data in custom_permissions:
        Permission.objects.get_or_create(
            codename=perm_data["codename"],
            name=perm_data["name"],
            content_type=perm_data["content_type"],
        )


def create_admin_groups():
    """
    Cria grupos de usuários para o admin.
    """
    from django.contrib.auth.models import Group, Permission

    # Grupo: Administradores Salonix
    admin_group, created = Group.objects.get_or_create(name="Salonix Admins")
    if created:
        # Adicionar todas as permissões customizadas
        custom_perms = Permission.objects.filter(
            codename__in=[
                "view_all_tenants",
                "manage_tenant_features",
                "view_system_stats",
                "manage_subscriptions",
            ]
        )
        admin_group.permissions.set(custom_perms)

    # Grupo: Gerentes de Tenant
    manager_group, created = Group.objects.get_or_create(name="Tenant Managers")
    if created:
        # Permissões limitadas para gerenciar apenas o próprio tenant
        tenant_perms = Permission.objects.filter(
            content_type__model__in=["service", "professional", "appointment"],
            codename__startswith="change_",
        )
        manager_group.permissions.set(tenant_perms)

    # Grupo: Suporte
    support_group, created = Group.objects.get_or_create(name="Support")
    if created:
        # Apenas visualização
        view_perms = Permission.objects.filter(codename__startswith="view_")
        support_group.permissions.set(view_perms)


def assign_user_to_admin_group(user_email, group_name):
    """
    Atribui um usuário a um grupo administrativo.
    """
    try:
        from django.contrib.auth.models import Group

        user = CustomUser.objects.get(email=user_email)
        group = Group.objects.get(name=group_name)
        user.groups.add(group)
        return True
    except (CustomUser.DoesNotExist, Group.DoesNotExist):
        return False


class AdminSecurityMiddleware:
    """
    Middleware para adicionar segurança extra ao admin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Log tentativas de acesso ao admin
        if request.path.startswith("/admin/"):
            import logging

            logger = logging.getLogger("salonix_backend.admin")

            if request.user.is_authenticated:
                logger.info(
                    f"Admin access: {request.user.username} -> {request.path}",
                    extra={
                        "user_id": request.user.id,
                        "tenant_id": (
                            request.user.tenant.slug if request.user.tenant else None
                        ),
                        "ip_address": self._get_client_ip(request),
                        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
                    },
                )
            else:
                logger.warning(
                    f"Unauthenticated admin access attempt: {request.path}",
                    extra={
                        "ip_address": self._get_client_ip(request),
                        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
                    },
                )

        response = self.get_response(request)
        return response

    def _get_client_ip(self, request):
        """Obtém IP do cliente."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR", "unknown")
        return ip
