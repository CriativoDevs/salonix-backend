from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken

from .models import CustomUser, UserFeatureFlags, Tenant
from salonix_backend.validators import (
    validate_phone_number,
    sanitize_text_input,
    sanitize_phone_number,
)


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = CustomUser
        fields = ["id", "username", "email", "password", "salon_name", "phone_number"]

    def validate_username(self, value):
        """Validar e sanitizar nome de usuário."""
        sanitized = sanitize_text_input(value, max_length=150)
        if not sanitized:
            raise serializers.ValidationError("Nome de usuário é obrigatório.")

        # Verificar se não contém apenas espaços
        if not sanitized.strip():
            raise serializers.ValidationError(
                "Nome de usuário não pode ser apenas espaços."
            )

        return sanitized

    def validate_salon_name(self, value):
        """Validar e sanitizar nome do salão."""
        if value:
            return sanitize_text_input(value, max_length=255)
        return value

    def validate_phone_number(self, value):
        """Validar e sanitizar número de telefone."""
        if value:
            sanitized = sanitize_phone_number(value)
            validate_phone_number(sanitized)
            return sanitized
        return value

    def validate_password(self, value):
        """Validar força da senha."""
        if len(value) < 8:
            raise serializers.ValidationError("Senha deve ter pelo menos 8 caracteres.")

        # Verificar se tem pelo menos uma letra e um número
        has_letter = any(c.isalpha() for c in value)
        has_number = any(c.isdigit() for c in value)

        if not (has_letter and has_number):
            raise serializers.ValidationError(
                "Senha deve conter pelo menos uma letra e um número."
            )

        return value

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


class EmailTokenObtainPairSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            raise AuthenticationFailed("Incorrect credentials")

        if not user.check_password(password):
            raise AuthenticationFailed("User account is disabled.")

        if not user.is_active:
            raise AuthenticationFailed(
                "No active account found with the given credentials"
            )

        refresh = RefreshToken.for_user(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }


class TenantMetaSerializer(serializers.ModelSerializer):
    """
    Serializer para informações públicas do tenant (branding + feature flags).
    Usado pelo endpoint /api/users/tenant/meta/
    """

    feature_flags = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "name",
            "slug",
            "logo_url",
            "primary_color",
            "secondary_color",
            "timezone",
            "currency",
            "plan_tier",
            "feature_flags",
        ]
        read_only_fields = [
            "name",
            "slug",
            "logo_url",
            "primary_color",
            "secondary_color",
            "timezone",
            "currency",
            "plan_tier",
            "feature_flags",
        ]

    def get_feature_flags(self, obj):
        """Retorna feature flags calculadas baseadas no plano"""
        return obj.get_feature_flags_dict()

    def get_logo_url(self, obj):
        """Retorna a URL do logo (upload ou URL externa)"""
        return obj.get_logo_url


class TenantBrandingUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer para atualização de branding do tenant.
    Permite upload de logo e atualização de cores.
    """

    class Meta:
        model = Tenant
        fields = [
            "logo",
            "logo_url",
            "primary_color",
            "secondary_color",
        ]
        extra_kwargs = {
            "logo": {"required": False},
            "logo_url": {"required": False},
            "primary_color": {"required": False},
            "secondary_color": {"required": False},
        }

    def validate(self, data):
        """Validação customizada para branding"""
        # Não permitir logo e logo_url ao mesmo tempo
        if "logo" in data and data["logo"] and "logo_url" in data and data["logo_url"]:
            raise serializers.ValidationError(
                "Não é possível enviar 'logo' e 'logo_url' simultaneamente. Use apenas um."
            )

        return data
