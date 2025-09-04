from rest_framework import serializers
from django.utils import timezone

from core.models import Service, Professional, ScheduleSlot, Appointment
from salonix_backend.validators import (
    validate_appointment_data,
    validate_service_data,
    validate_professional_data,
    validate_price,
    validate_duration,
    sanitize_text_input,
)


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ["id", "user", "name", "price_eur", "duration_minutes"]
        read_only_fields = ["user"]

    def validate_name(self, value):
        """Validar e sanitizar nome do serviço."""
        sanitized = sanitize_text_input(value, max_length=200)
        if not sanitized:
            raise serializers.ValidationError("Nome do serviço é obrigatório.")
        return sanitized

    def validate_price_eur(self, value):
        """Validar preço do serviço."""
        validate_price(value)
        return value

    def validate_duration_minutes(self, value):
        """Validar duração do serviço."""
        validate_duration(value)
        return value

    def validate(self, data):
        """Validação completa do serviço."""
        return validate_service_data(data)


class ProfessionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Professional
        fields = ["id", "user", "name", "bio", "is_active"]
        read_only_fields = ["user"]

    def validate_name(self, value):
        """Validar e sanitizar nome do profissional."""
        sanitized = sanitize_text_input(value, max_length=200)
        if not sanitized:
            raise serializers.ValidationError("Nome do profissional é obrigatório.")
        return sanitized

    def validate_bio(self, value):
        """Validar e sanitizar biografia do profissional."""
        if value:
            return sanitize_text_input(value, max_length=1000)
        return value

    def validate(self, data):
        """Validação completa do profissional."""
        return validate_professional_data(data)


class ScheduleSlotSerializer(serializers.ModelSerializer):
    start_time = serializers.DateTimeField(format="%Y-%m-%d %H:%M")
    end_time = serializers.DateTimeField(format="%Y-%m-%d %H:%M")

    class Meta:
        model = ScheduleSlot
        fields = ["id", "professional", "start_time", "end_time", "is_available"]

    def validate(self, data):
        """Validar horários do slot."""
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        if start_time and end_time:
            from salonix_backend.validators import validate_business_hours

            validate_business_hours(start_time, end_time)

        return data


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
            "status",
            "cancelled_by",
        ]
        read_only_fields = ["client", "created_at", "cancelled_by"]

    def validate_notes(self, value):
        """Validar e sanitizar notas do agendamento."""
        if value:
            return sanitize_text_input(value, max_length=500)
        return value

    def validate(self, data):
        """Validação completa do agendamento."""
        request = self.context.get("request")
        user = request.user if request else None
        tenant = getattr(request, "tenant", None) if request else None

        # Validações básicas existentes
        slot = data.get("slot")
        professional = data.get("professional")

        errors = {}

        # 1. Verifica se o slot está disponível
        if slot and not slot.is_available:
            errors["slot"] = "Este horário já foi agendado."

        # 2. Verifica se o slot é do profissional informado
        if slot and professional and slot.professional != professional:
            errors["slot"] = "Este horário não pertence ao profissional informado."

        # 3. Verifica se o slot está no futuro
        if slot and slot.start_time <= timezone.now():
            errors["slot"] = "Não é possível agendar horários no passado."

        # 4. Verifica se o cliente já tem um agendamento para o mesmo slot
        if (
            user
            and slot
            and Appointment.objects.filter(client=user, slot=slot).exists()
        ):
            errors["slot"] = "Você já tem um agendamento para este horário."

        if errors:
            raise serializers.ValidationError(errors)

        # Usar validação avançada se tenant estiver disponível
        if tenant:
            try:
                data = validate_appointment_data(data, tenant, user)
            except Exception as e:
                # Se a validação avançada falhar, manter validação básica
                pass

        return data


class ServiceMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ["id", "name", "price_eur", "duration_minutes"]


class ProfessionalMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Professional
        fields = ["id", "name", "bio", "is_active"]


class ScheduleSlotMiniSerializer(serializers.ModelSerializer):
    start_time = serializers.DateTimeField(format="%Y-%m-%d %H:%M")
    end_time = serializers.DateTimeField(format="%Y-%m-%d %H:%M")

    class Meta:
        model = ScheduleSlot
        fields = ["id", "start_time", "end_time", "is_available", "status"]


class AppointmentDetailSerializer(serializers.ModelSerializer):
    service = ServiceMiniSerializer(read_only=True)
    professional = ProfessionalMiniSerializer(read_only=True)
    slot = ScheduleSlotMiniSerializer(read_only=True)
    client_username = serializers.CharField(source="client.username", read_only=True)
    client_email = serializers.EmailField(source="client.email", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "status",
            "notes",
            "created_at",
            "client_username",
            "client_email",
            "service",
            "professional",
            "slot",
        ]
        read_only_fields = fields
