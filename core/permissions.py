"""
Custom permissions for Core app.
BE-ACCOUNT-CANCEL #396
"""

from rest_framework import permissions


class IsTenantStaff(permissions.BasePermission):
    """
    Permite apenas equipe do estabelecimento (TenantStaffMember) ou superuser.

    Tokens JWT com scope=client sao recusados: eles carregam user_id igual ao
    id do cliente e, com a autenticacao padrao, resolveriam para o CustomUser
    de mesmo PK (de qualquer tenant).
    """

    message = "Acesso restrito à equipe do estabelecimento."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        token = request.auth
        if token is not None and hasattr(token, "get"):
            if token.get("scope") == "client":
                return False

        if getattr(user, "is_superuser", False):
            return True

        return getattr(user, "staff_role", None) is not None


class IsTenantOwnerOrManager(permissions.BasePermission):
    """Permite apenas owner/manager do tenant (ou superuser)."""

    message = "Apenas owner ou manager podem executar esta ação."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_superuser", False):
            return True

        from users.models import TenantStaffMember

        return user.has_staff_role(
            TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
        )


class IsOwner(permissions.BasePermission):
    """
    Permite apenas owners do tenant.
    Staff e managers são bloqueados.

    Usage:
        permission_classes = [IsAuthenticated, IsOwner]
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Verificar se user tem tenant associado
        if not hasattr(request.user, "tenant") or not request.user.tenant:
            return False

        # Buscar staff record para verificar role
        from users.models import TenantStaffMember

        try:
            staff = TenantStaffMember.objects.get(
                user=request.user, tenant=request.user.tenant
            )
            return staff.role == "owner"
        except TenantStaffMember.DoesNotExist:
            return False
