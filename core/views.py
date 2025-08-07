from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, CreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from core.email_utils import send_appointment_confirmation_email
from core.models import Appointment, Professional, Service, ScheduleSlot
from core.serializers import (
    AppointmentSerializer,
    ProfessionalSerializer,
    ServiceSerializer,
    ScheduleSlotSerializer,
)


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
        if not slot.is_available:
            raise ValidationError("Este horário já foi agendado.")

        slot.is_available = False
        slot.save()

        appointment = serializer.save(client=self.request.user)

        # Envia e-mail de confirmação
        try:
            send_appointment_confirmation_email(
                to_email=self.request.user.email,
                client_name=self.request.user.username
                or self.request.user.email.split("@")[0],
                service_name=appointment.service.name,
                date_time=appointment.slot.start_time,
            )
        except Exception as e:
            print("Falha ao enviar e-mail:", e)


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
