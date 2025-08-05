from rest_framework import serializers
from core.models import Service, Professional, ScheduleSlot, Appointment


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ["id", "user", "name", "price_eur", "duration_minutes"]


class ProfessionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Professional
        fields = ["id", "user", "name", "bio", "is_active"]


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
        read_only_fields = ["created_at"]
