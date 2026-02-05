"""
Custom permissions for Core app.
BE-ACCOUNT-CANCEL #396
"""

from rest_framework import permissions


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
