from rest_framework import status as drf_status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, CreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from core.email_utils import (
    send_appointment_confirmation_email,
    send_appointment_cancellation_email,
)
from core.models import Appointment, Professional, Service, ScheduleSlot
from core.serializers import (
    AppointmentSerializer,
    ProfessionalSerializer,
    ServiceSerializer,
    ScheduleSlotSerializer,
)

from django.db import transaction, models
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from users.permissions import IsSalonOwnerOfAppointment


class PublicServiceListView(ListAPIView):
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    permission_classes = []


class PublicProfessionalListView(ListAPIView):
    queryset = Professional.objects.filter(is_active=True)
    serializer_class = ProfessionalSerializer
    permission_classes = []


class PublicSlotListView(ListAPIView):
    serializer_class = ScheduleSlotSerializer
    permission_classes = []

    def get_queryset(self):
        professional_id = self.request.query_params.get("professional_id")
        if not professional_id:
            raise ValidationError({"professional_id": "Este parâmetro é obrigatório."})

        return ScheduleSlot.objects.filter(
            professional_id=professional_id, is_available=True
        ).order_by("start_time")


class AppointmentCreateView(CreateAPIView):
    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        slot = serializer.validated_data["slot"]
        if (not slot.is_available) or (slot.status != "available"):
            raise ValidationError(
                "Este horário já foi agendado ou não está disponível."
            )

        # marca como reservado via helper do model
        slot.mark_booked()

        appointment = serializer.save(client=self.request.user)

        # Envia e-mail de confirmação
        try:
            send_appointment_confirmation_email(
                to_email=self.request.user.email,
                client_name=(
                    self.request.user.get_full_name()
                    or self.request.user.username
                    or self.request.user.email.split("@")[0]
                ),
                service_name=appointment.service.name,
                date_time=appointment.slot.start_time,
            )
        except Exception as e:
            print("Falha ao enviar e-mail:", e)


class AppointmentCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        appointment = get_object_or_404(Appointment, pk=pk)

        if appointment.client != request.user:
            return Response(
                {"detail": "Você não tem permissão para cancelar este agendamento."},
                status=403,
            )

        if appointment.status == "cancelled":
            return Response(
                {"detail": "Este agendamento já foi cancelado."}, status=400
            )

        with transaction.atomic():
            appointment.status = "cancelled"
            appointment.cancelled_by = request.user
            appointment.slot.mark_available()  # já salva o slot
            appointment.save()

        # E-mail para cliente e salão (não bloqueia a resposta)
        try:
            send_appointment_cancellation_email(
                client_email=appointment.client.email,
                salon_email=appointment.professional.user.email,
                client_name=appointment.client.get_full_name()
                or appointment.client.username,
                service_name=appointment.service.name,
                date_time=appointment.slot.start_time,
            )
        except Exception as e:
            print("Erro ao enviar e-mail de cancelamento:", str(e))

        serializer = AppointmentSerializer(appointment)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)


class ServiceViewSet(ModelViewSet):
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Service.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ProfessionalViewSet(ModelViewSet):
    queryset = Professional.objects.all()
    serializer_class = ProfessionalSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ScheduleSlotViewSet(ModelViewSet):
    queryset = ScheduleSlot.objects.all()
    serializer_class = ScheduleSlotSerializer
    permission_classes = [IsAuthenticated]


class SalonAppointmentViewSet(ModelViewSet):
    """
    Endpoints para o SALÃO visualizar e editar seus agendamentos.
    - list/retrieve: vê apenas agendamentos do próprio salão
      (match por professional.user == request.user OU service.user == request.user)
    - update/partial_update: permite editar SOMENTE o campo 'notes'
      (cancelamento continua pelo endpoint específico de cancelamento).
    - destroy: opcionalmente podemos permitir apagar; por padrão vou desabilitar abaixo.
    """

    serializer_class = AppointmentSerializer
    permission_classes = [IsSalonOwnerOfAppointment]

    def get_queryset(self):
        user = self.request.user
        # Filtra por agendamentos cujo profissional OU serviço pertencem ao salão (user atual)
        return Appointment.objects.filter(
            models.Q(professional__user=user) | models.Q(service__user=user)
        ).select_related("client", "service", "professional", "slot")

    def update(self, request, *args, **kwargs):
        """Permite editar apenas 'notes' (PUT/PATCH)."""
        instance = self.get_object()
        notes = request.data.get("notes", None)
        # Se vier PUT com outros campos, bloqueamos; se vier PATCH sem 'notes', também bloqueamos
        only_notes = set(request.data.keys()) <= {"notes"} and notes is not None
        if not only_notes:
            return Response(
                {"detail": "Somente o campo 'notes' pode ser editado por aqui."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        instance.notes = notes
        instance.save(update_fields=["notes"])
        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        # Evitamos delete duro via API do salão (histórico importa).
        return Response(
            {
                "detail": "Exclusão de agendamentos não é permitida. Cancele o agendamento."
            },
            status=drf_status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class MyAppointmentsListView(ListAPIView):
    """
    Lista os agendamentos do usuário autenticado (como cliente).
    GET /api/me/appointments/
    """

    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return (
            Appointment.objects.filter(client=user)
            .select_related("client", "service", "professional", "slot")
            .order_by("-slot__start_time", "-created_at")
        )
