from rest_framework.permissions import BasePermission


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

        return (
            request.user
            and request.user.is_authenticated
            and (
                request.user == salon_user_from_professional
                or request.user == salon_user_from_service
            )
        )
