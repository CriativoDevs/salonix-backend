from __future__ import annotations

from rest_framework.permissions import BasePermission

from users.models import CustomUser


class IsOpsUser(BasePermission):
    """Permite acesso apenas para contas do console Ops."""

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "is_ops_user", False)
        )


class IsOpsAdmin(IsOpsUser):
    """Permite apenas usuários com role ops_admin."""

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return getattr(request.user, "ops_role", None) == CustomUser.OpsRoles.OPS_ADMIN


class IsOpsSupportOrAdmin(IsOpsUser):
    """Permite visualização para roles ops_support e ops_admin."""

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return getattr(request.user, "ops_role", None) in {
            CustomUser.OpsRoles.OPS_SUPPORT,
            CustomUser.OpsRoles.OPS_ADMIN,
        }
