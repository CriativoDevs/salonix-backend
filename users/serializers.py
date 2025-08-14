from django.contrib.auth.models import User
from rest_framework import serializers

from .models import CustomUser, UserFeatureFlags


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = CustomUser
        fields = ["id", "username", "email", "password", "salon_name", "phone_number"]

    def create(self, validated_data):
        user = CustomUser.objects.create_user(
            username=validated_data["username"],
            email=validated_data.get("email"),
            password=validated_data["password"],
            salon_name=validated_data.get("salon_name", ""),
            phone_number=validated_data.get("phone_number", ""),
        )
        return user


class UserFeatureFlagsSerializer(serializers.ModelSerializer):
    # Campos somente leitura – controlados por Stripe/adm
    is_pro = serializers.BooleanField(read_only=True)
    pro_status = serializers.CharField(read_only=True)
    pro_plan = serializers.CharField(read_only=True)
    pro_since = serializers.DateTimeField(read_only=True)
    pro_until = serializers.DateTimeField(read_only=True)
    trial_until = serializers.DateTimeField(read_only=True)

    class Meta:
        model = UserFeatureFlags
        fields = [
            "is_pro",
            "pro_status",
            "pro_plan",
            "pro_since",
            "pro_until",
            "trial_until",
            "sms_enabled",
            "email_enabled",
            "reports_enabled",
            "audit_log_enabled",
            "i18n_enabled",
            "updated_at",
            "created_at",
        ]
        read_only_fields = [
            "is_pro",
            "pro_status",
            "pro_plan",
            "pro_since",
            "pro_until",
            "trial_until",
            "updated_at",
            "created_at",
        ]


class UserFeatureFlagsUpdateSerializer(UserFeatureFlagsSerializer):
    """
    Para PATCH: permite editar apenas os módulos opcionais.
    """

    class Meta(UserFeatureFlagsSerializer.Meta):
        read_only_fields = UserFeatureFlagsSerializer.Meta.read_only_fields
