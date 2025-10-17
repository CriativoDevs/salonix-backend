from rest_framework.permissions import BasePermission, SAFE_METHODS

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


class HasProFeature(BasePermission):
    """
    Exemplo de permissão para endpoints premium.
    """

    def has_permission(self, request, view):
        ff = getattr(request.user, "featureflags", None)
        return bool(ff and ff.is_pro)
