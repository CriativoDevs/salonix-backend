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

from ops.models import (
    OpsAlert,
    OpsSupportAuditLog,
    OpsGlobalSetting,
    OpsNotificationTemplate,
)
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
        except TokenError:
            raise AuthenticationFailed("Token inválido ou expirado.")

        user_id = refresh.payload.get("user_id")
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise AuthenticationFailed("Usuário não encontrado.")

        if not user.is_active:
            raise AuthenticationFailed("Conta inativa.")

        if not getattr(user, "is_ops_user", False):
            raise AuthenticationFailed("Acesso restrito.")

        ops_role = user.ops_role or User.OpsRoles.OPS_SUPPORT

        # Rotacionar refresh token?
        # Por padrão simplejwt não rotaciona se ROTATE_REFRESH_TOKENS=False
        # Vamos gerar um novo par
        refresh.set_jti()
        refresh.set_exp()
        refresh.set_iat()

        tokens = _base_ops_token_claims(refresh, ops_role, user.id)

        return {
            "access": str(tokens["access"]),
            "refresh": str(tokens["refresh"]),
            "ops_role": ops_role,
        }


class OpsUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "ops_role",
            "last_login",
            "date_joined",
        ]
        read_only_fields = ["last_login", "date_joined"]


class OpsUserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "ops_role",
            "is_active",
        ]

    def create(self, validated_data: Dict[str, Any]) -> Any:
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.is_ops_user = True
        user.save()
        return user


class OpsUserUpdateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "ops_role",
            "is_active",
        ]
        read_only_fields = ["username"]

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class OpsMetricsOverviewSerializer(serializers.Serializer):
    totals = serializers.DictField()
    mrr_estimated = serializers.DictField()
    notification_daily = serializers.ListField()


class OpsTenantListSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()
    user_counts = serializers.SerializerMethodField()
    notification_consumption = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "slug",
            "plan_tier",
            "billing_mode",
            "promotional_expires_at",
            "promotional_converts_to_plan",
            "is_active",
            "created_at",
            "owner",
            "history",
            "user_counts",
            "notification_consumption",
        ]

    def get_user_counts(self, obj: Tenant) -> Dict[str, int]:
        total = obj.users.count()
        return {"total": total}

    def get_notification_consumption(self, obj: Tenant) -> Dict[str, int]:
        # This could be expensive for list view, but for now we implement it simply
        sms = NotificationLog.objects.filter(tenant=obj, channel="sms").count()
        whatsapp = NotificationLog.objects.filter(
            tenant=obj, channel="whatsapp"
        ).count()
        email = NotificationLog.objects.filter(tenant=obj, channel="email").count()
        return {
            "sms": sms,
            "whatsapp": whatsapp,
            "email": email,
            "total": sms + whatsapp + email,
        }

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

    def get_history(self, obj: Tenant) -> list | dict:
        return {}


class OpsTenantDetailSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()
    metrics = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "slug",
            "plan_tier",
            "billing_mode",
            "promotional_expires_at",
            "promotional_converts_to_plan",
            "is_active",
            "created_at",
            "owner",
            "history",
            "metrics",
        ]

    def get_metrics(self, obj: Tenant) -> Dict[str, Any]:
        # Mock metrics for tenant detail
        # Total notifications sent, alerts, etc.
        # This is expensive, so maybe fetch async or cache

        # Example: count notification logs
        total_notifs = NotificationLog.objects.filter(tenant=obj).count()

        # Breakdown by channel
        breakdown = (
            NotificationLog.objects.filter(tenant=obj)
            .values("channel")
            .annotate(count=Count("id"))
        )

        result = {"total_notifications": total_notifs}
        total = 0
        for item in breakdown:
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

    def validate_plan_tier(self, value):
        # BE-PLANS-01 (#481): plano bloqueado não pode ser atribuído nem via OPS.
        if Tenant.is_plan_blocked(value):
            raise serializers.ValidationError(
                "Este plano está bloqueado e não pode ser atribuído."
            )
        return value


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


class OpsGlobalSettingSerializer(serializers.ModelSerializer):
    updated_by_email = serializers.CharField(source="updated_by.email", read_only=True)

    class Meta:
        model = OpsGlobalSetting
        fields = [
            "id",
            "key",
            "value",
            "value_type",
            "description",
            "is_public",
            "updated_at",
            "updated_by",
            "updated_by_email",
        ]
        read_only_fields = ["id", "updated_at", "updated_by", "updated_by_email"]

    def create(self, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        return super().update(instance, validated_data)


class OpsNotificationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpsNotificationTemplate
        fields = [
            "id",
            "code",
            "channel",
            "subject",
            "body_text",
            "body_html",
            "is_active",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class OpsUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "ops_role",
            "is_active",
            "last_login",
            "date_joined",
        ]
        read_only_fields = ["id", "last_login", "date_joined"]


class OpsUserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "ops_role",
            "is_active",
        ]

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        return user

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Este email já está em uso.")
        return value


class OpsUserUpdateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "password",
            "ops_role",
            "is_active",
        ]

    def update(self, instance, validated_data):
        if "password" in validated_data:
            password = validated_data.pop("password")
            instance.set_password(password)
        return super().update(instance, validated_data)
