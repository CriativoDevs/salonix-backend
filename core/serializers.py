from rest_framework import serializers

from core.models import Service, Professional, ScheduleSlot, Appointment
from django.utils import timezone


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ["id", "user", "name", "price_eur", "duration_minutes"]
        read_only_fields = ["user"]


class ProfessionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Professional
        fields = ["id", "user", "name", "bio", "is_active"]
        read_only_fields = ["user"]


class ScheduleSlotSerializer(serializers.ModelSerializer):
    start_time = serializers.DateTimeField(format="%Y-%m-%d %H:%M")
    end_time = serializers.DateTimeField(format="%Y-%m-%d %H:%M")

    class Meta:
        model = ScheduleSlot
        fields = ["id", "professional", "start_time", "end_time", "is_available"]


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = [
            "id",
            "client",
            "service",
            "professional",
            "slot",
            "notes",
            "created_at",
        ]
        read_only_fields = ["client", "created_at"]

    def validate(self, data):
        request = self.context.get("request")
        user = request.user if request else None

        slot = data.get("slot")
        professional = data.get("professional")

        errors = {}

        # 1. Verifica se o slot está disponível
        if not slot.is_available:
            errors["slot"] = "Este horário já foi agendado."

        # 2. Verifica se o slot é do profissional informado
        if slot.professional != professional:
            errors["slot"] = "Este horário não pertence ao profissional informado."

        # 3. Verifica se o slot está no futuro
        if slot.start_time <= timezone.now():
            errors["slot"] = "Não é possível agendar horários no passado."

        # 4. Verifica se o cliente já tem um agendamento para o mesmo slot
        if user and Appointment.objects.filter(client=user, slot=slot).exists():
            errors["slot"] = "Você já tem um agendamento para este horário."

        if errors:
            raise serializers.ValidationError(errors)

        return data
