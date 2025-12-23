from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.settings import api_settings

from ops.models import OpsAlert, OpsSupportAuditLog
from notifications.models import NotificationLog
from users.models import Tenant

User = get_user_model()
logger = logging.getLogger(__name__)


def _base_ops_token_claims(
    refresh: RefreshToken, ops_role: str, user_id: int
) -> Dict[str, Any]:
    refresh["scope"] = ops_role
    refresh["ops_role"] = ops_role
    refresh["tenant_slug"] = None
    refresh["tenant_id"] = None
    refresh["user_id"] = str(user_id)

    access = refresh.access_token
    access["scope"] = ops_role
    access["ops_role"] = ops_role
    access["tenant_slug"] = None
    access["tenant_id"] = None
    access["user_id"] = str(user_id)
    return {
        "refresh": refresh,
        "access": access,
    }


class OpsTokenObtainPairSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        username = attrs.get("username")
        password = attrs.get("password")

        if not username or not password:
            raise AuthenticationFailed("Credenciais inválidas.")

        # Tenta buscar por username primeiro, depois por email
        user = None
        if "@" in username:
            try:
                user = User.objects.get(email=username)
            except User.DoesNotExist:
                pass

        if not user:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                raise AuthenticationFailed("Credenciais inválidas.")

        if not user.check_password(password):
            raise AuthenticationFailed("Credenciais inválidas.")

        if not user.is_active:
            raise AuthenticationFailed("Conta inativa. Entre em contato com o suporte.")

        if not getattr(user, "is_ops_user", False):
            raise AuthenticationFailed("Acesso restrito ao console Ops.")

        ops_role = user.ops_role or User.OpsRoles.OPS_SUPPORT
        refresh = RefreshToken.for_user(user)
        tokens = _base_ops_token_claims(refresh, ops_role, user.id)

        self.user = user  # type: ignore[attr-defined]
        self.ops_role = ops_role  # type: ignore[attr-defined]

        return {
            "refresh": str(tokens["refresh"]),
            "access": str(tokens["access"]),
            "ops_role": ops_role,
            "user_id": str(user.id),
        }


class OpsTokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        raw_refresh = attrs.get("refresh")
        if not raw_refresh:
            raise AuthenticationFailed("Token de refresh é obrigatório.")

        try:
            refresh = RefreshToken(raw_refresh)
        except (TokenError, InvalidToken) as exc:
            logger.warning("Ops refresh token inválido", extra={"error": str(exc)})
            raise AuthenticationFailed("Token de refresh inválido.") from exc

        scope = refresh.get("scope")
        if scope not in (User.OpsRoles.OPS_ADMIN, User.OpsRoles.OPS_SUPPORT):
            raise AuthenticationFailed("Token não pertence ao console Ops.")

        user_id_raw = refresh.get("user_id")
        try:
            user_id = int(user_id_raw)
            user = User.objects.get(pk=user_id)
        except (ValueError, TypeError, User.DoesNotExist) as exc:
            raise AuthenticationFailed("Usuário não encontrado.") from exc

        if not user.is_active:
            raise AuthenticationFailed("Conta inativa.")

        # Recalcula ops_role atual do banco (pode ter mudado)
        current_ops_role = user.ops_role or User.OpsRoles.OPS_SUPPORT

        # Gera novos tokens com refresh rotation (novo par)
        refresh.set_jti()
        refresh.set_exp()
        tokens = _base_ops_token_claims(refresh, current_ops_role, user.id)

        self.user = user  # type: ignore[attr-defined]
        self.ops_role = current_ops_role  # type: ignore[attr-defined]

        return {
            "refresh": str(tokens["refresh"]),
            "access": str(tokens["access"]),
            "ops_role": current_ops_role,
        }


class OpsUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "username", "ops_role", "is_active", "last_login"]
        read_only_fields = fields


class OpsUserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["id", "email", "username", "password", "ops_role", "is_active"]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Este email já está em uso.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        # Ensure is_staff is True via model save() logic when ops_role is set
        user = User.objects.create_user(password=password, **validated_data)
        return user


class OpsUserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["email", "username", "ops_role", "is_active"]

    def validate_email(self, value):
        # Unique email check excluding current user
        user = self.instance
        if (
            User.objects.filter(email__iexact=value).exclude(pk=user.pk).exists()
            if user
            else User.objects.filter(email__iexact=value).exists()
        ):
            raise serializers.ValidationError("Este email já está em uso.")
        return value


class OpsTenantSerializer(serializers.ModelSerializer):
    feature_flags = serializers.SerializerMethodField()
    user_counts = serializers.SerializerMethodField()
    notification_consumption = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._datetime_field = serializers.DateTimeField(format=None)

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "slug",
            "plan_tier",
            "is_active",
            "timezone",
            "currency",
            "addons_enabled",
            "created_at",
            "updated_at",
            "feature_flags",
            "user_counts",
            "notification_consumption",
            "history",
            "owner",
        ]
        read_only_fields = fields

    def get_feature_flags(self, obj: Tenant) -> Dict[str, Any]:
        return obj.get_feature_flags_dict()

    def get_user_counts(self, obj: Tenant) -> Dict[str, int]:
        # Exemplo simples, poderia ser otimizado
        return {
            "total": obj.users.count(),
            "active": obj.users.filter(is_active=True).count(),
        }

    def get_notification_consumption(self, obj: Tenant) -> Dict[str, int]:
        # Retorna contagem de notificações do mês atual
        now = timezone.now()
        start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Agrega por canal
        # Nota: isso pode ser pesado se tiver muitos logs, ideal ter tabela de métricas agregada
        # Mas para MVP Ops serve
        qs = NotificationLog.objects.filter(tenant=obj, created_at__gte=start_month)
        stats = qs.values("channel").annotate(count=Count("id"))

        result = {
            "sms": 0,
            "whatsapp": 0,
            "email": 0,
            "push": 0,
            "total": 0,
        }
        total = 0
        for item in stats:
            ch = item["channel"]
            c = item["count"]
            if ch in result:
                result[ch] = c
            total += c
        result["total"] = total
        return result

    def get_history(self, obj: Tenant) -> list | dict:
        # Exemplo: últimos 5 alertas ou ações de suporte
        # Por enquanto vazio ou mock
        return {}

    def get_owner(self, obj: Tenant) -> Optional[Dict[str, str]]:
        # Busca o owner atual
        owner_staff = obj.staff_members.filter(role="owner").first()
        if not owner_staff:
            return None

        owner = owner_staff.user
        return {
            "id": str(owner.id),
            "email": owner.email,
            "username": owner.username,
        }


class OpsTenantResetOwnerSerializer(serializers.Serializer):
    email = serializers.EmailField()
    username = serializers.CharField(required=False)
    name = serializers.CharField(required=False)

    def validate_email(self, value: str) -> str:
        # Verifica se email já existe em outro tenant?
        # Para simplificar, assumimos que o owner novo pode ser um user novo ou existente
        # Se existente, deve ser atualizado
        return value


class OpsTenantPlanUpdateSerializer(serializers.Serializer):
    plan_tier = serializers.ChoiceField(choices=Tenant.PLAN_CHOICES)
    addons_enabled = serializers.JSONField(required=False)
    force = serializers.BooleanField(required=False, default=False)


class OpsAlertSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    tenant_slug = serializers.CharField(source="tenant.slug", read_only=True)

    class Meta:
        model = OpsAlert
        fields = [
            "id",
            "category",
            "severity",
            "message",
            "is_resolved",
            "created_at",
            "resolved_at",
            "metadata",
            "tenant",
            "tenant_name",
            "tenant_slug",
        ]
        read_only_fields = ["created_at", "resolved_at", "tenant_name", "tenant_slug"]


class OpsResendNotificationSerializer(serializers.Serializer):
    notification_id = serializers.IntegerField()
    channel = serializers.CharField(required=False)


class OpsClearLockoutSerializer(serializers.Serializer):
    lockout_id = serializers.IntegerField(required=False)
    user_id = serializers.IntegerField(required=False)
    ip_address = serializers.IPAddressField(required=False)


class OpsSupportAuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True)
    actor_email = serializers.CharField(source="actor.email", read_only=True)
    target_tenant_name = serializers.CharField(
        source="target_tenant.name", read_only=True
    )
    target_user_email = serializers.CharField(
        source="target_user.email", read_only=True
    )

    class Meta:
        model = OpsSupportAuditLog
        fields = [
            "id",
            "action",
            "actor",
            "actor_name",
            "actor_email",
            "target_user",
            "target_user_email",
            "target_tenant",
            "target_tenant_name",
            "payload",
            "result",
            "created_at",
        ]
        read_only_fields = fields
