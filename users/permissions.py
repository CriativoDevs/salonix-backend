from rest_framework.permissions import BasePermission

from .models import TenantStaffMember


class IsSalonOwnerOfAppointment(BasePermission):
    """
    Permite acesso somente se o usuário autenticado for o dono do salão
    relacionado ao agendamento (via Professional.user ou Service.user).
    Usaremos esta permissão em endpoints que manipulam Appointment.
    """

    def has_object_permission(self, request, view, obj):
        # obj é uma instância de Appointment
        salon_user_from_professional = getattr(
            getattr(obj, "professional", None), "user", None
        )
        salon_user_from_service = getattr(getattr(obj, "service", None), "user", None)

        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        if (
            getattr(user, "tenant_id", None) is not None
            and getattr(obj, "tenant_id", None) == user.tenant_id
            and user.has_staff_role(
                TenantStaffMember.Role.OWNER,
                TenantStaffMember.Role.MANAGER,
            )
        ):
            return True

        return user == salon_user_from_professional or user == salon_user_from_service


class IsSelf(BasePermission):
    """
    Garante que o usuário só acesse/edite os próprios recursos.
    """

    def has_object_permission(self, request, view, obj):
        return getattr(obj, "user", None) == request.user or obj == request.user


class IsActiveTenant(BasePermission):
    """
    Permite acesso somente se o tenant do usuário estiver ativo.
    """

    message = "A conta do tenant está inativa."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Superusers e Ops ignoram essa regra
        if request.user.is_superuser or getattr(request.user, "is_ops_user", False):
            return True

        tenant = getattr(request.user, "tenant", None)
        if tenant and not tenant.is_active:
            return False

        return True


class HasProFeature(BasePermission):
    """
    Exemplo de permissão para endpoints premium.
    """

    def has_permission(self, request, view):
        ff = getattr(request.user, "featureflags", None)
        return bool(ff and ff.is_pro)


class RequiresMobileAccess(BasePermission):
    """
    Permite acesso somente se o tenant do usuário tiver permissão para usar
    o aplicativo nativo (Plano Standard ou superior).
    Retorna 403 com payload específico de upgrade se o plano for insuficiente.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Superusers sempre têm acesso
        if request.user.is_superuser:
            return True

        tenant = getattr(request.user, "tenant", None)

        if not tenant:
            # Se não tem tenant, teoricamente não deveria acessar endpoints de tenant,
            # mas deixamos passar aqui para outras permissions barrarem se necessário,
            # ou bloqueamos se for estritamente endpoint de tenant.
            # Como é uma verificação de "Mobile Access" que depende do plano do tenant,
            # se não tem tenant, não tem plano => bloqueia.
            return False

        if tenant.can_use_native_admin():
            return True

        # Se chegou aqui, não tem permissão.
        # Construir exceção com payload rico para o frontend/mobile
        from rest_framework.exceptions import PermissionDenied

        # Hack para passar dados extras no erro 403
        # O DRF padrão não suporta payload JSON arbitrário na PermissionDenied simples sem subclassing
        # Mas podemos injetar atributos na exceção se o exception handler suportar,
        # ou usar uma exceção customizada.
        # Vamos usar uma exceção customizada que o exception handler (se existir) possa tratar,
        # ou simplesmente raising PermissionDenied com dict (DRF suporta dict no detail).

        detail = {
            "detail": "Seu plano não permite acesso ao Admin App. Upgrade para Standard para desbloquear.",
            "plan_required": "standard",
            "current_plan": tenant.plan_tier,
            "upgrade_url": "/pricing",
            "code": "PLAN_UPGRADE_REQUIRED",
        }
        raise PermissionDenied(detail=detail, code="PLAN_UPGRADE_REQUIRED")
