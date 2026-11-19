"""
Custom permissions for Core app.
BE-ACCOUNT-CANCEL #396
"""

from rest_framework import permissions


def _is_client_token(request):
    token = request.auth
    return (
        token is not None
        and hasattr(token, "get")
        and token.get("scope") == "client"
    )


def _active_staff_member(request):
    """TenantStaffMember ATIVO do usuário, no tenant do próprio usuário.

    Status DISABLED/INVITED não dá acesso (mark_disabled não desativa o login),
    e o vínculo precisa ser do tenant do próprio usuário.
    """
    from users.models import TenantStaffMember

    user = request.user
    # O tenant do proprio usuario e a fonte confiavel (o vinculo de equipe e
    # 1:1 com o usuario). request.tenant so entra como fallback: nao vem de
    # input do cliente e, em JWT, costuma ser resolvido a partir do usuario.
    tenant = getattr(user, "tenant", None) or getattr(request, "tenant", None)
    if tenant is None:
        return None
    return TenantStaffMember.objects.filter(
        user=user, tenant=tenant, status=TenantStaffMember.Status.ACTIVE
    ).first()


class IsTenantStaff(permissions.BasePermission):
    """
    Permite apenas equipe ATIVA do estabelecimento (TenantStaffMember) ou
    superuser.

    Tokens JWT com scope=client sao recusados: eles carregam user_id igual ao
    id do cliente e, com a autenticacao padrao, resolveriam para o CustomUser
    de mesmo PK (de qualquer tenant).
    """

    message = "Acesso restrito à equipe do estabelecimento."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if _is_client_token(request):
            return False

        if getattr(user, "is_superuser", False):
            return True

        return _active_staff_member(request) is not None


class IsTenantOwnerOrManager(permissions.BasePermission):
    """Permite apenas owner/manager ATIVO do tenant (ou superuser)."""

    message = "Apenas owner ou manager podem executar esta ação."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if _is_client_token(request):
            return False

        if getattr(user, "is_superuser", False):
            return True

        from users.models import TenantStaffMember

        staff = _active_staff_member(request)
        return staff is not None and staff.role in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        )


class IsTenantOwner(permissions.BasePermission):
    """Permite apenas o owner ATIVO do tenant (ou superuser)."""

    message = "Apenas o owner pode executar esta ação."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if _is_client_token(request):
            return False

        if getattr(user, "is_superuser", False):
            return True

        from users.models import TenantStaffMember

        staff = _active_staff_member(request)
        return staff is not None and staff.role == TenantStaffMember.Role.OWNER


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
