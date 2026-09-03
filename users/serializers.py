import logging
import secrets
from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, cast
from enum import Enum

from django.db import transaction
from django.apps import apps
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import CustomUser, UserFeatureFlags, Tenant, TenantStaffMember, CommLedger, TenantBusinessHours
from .services import FounderService
from salonix_backend.validators import (
    validate_phone_number,
    sanitize_text_input,
    sanitize_phone_number,
)


audit_logger = logging.getLogger("users.audit")


def _validate_optional_birthday(value):
    if value and value > timezone.localdate():
        raise serializers.ValidationError(
            "A data de aniversário não pode estar no futuro."
        )
    return value


class TenantStaffMemberRole(str, Enum):
    owner = "owner"
    manager = "manager"
    collaborator = "collaborator"


class TenantStaffMemberStatus(str, Enum):
    active = "active"
    invited = "invited"
    disabled = "disabled"


class CommLedgerTransactionType(str, Enum):
    purchase = "purchase"
    consumption = "consumption"
    expiration = "expiration"
    refund = "refund"
    bonus = "bonus"


class CommLedgerStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


def _generate_unique_tenant_slug(base_name: str) -> str:
    """Generate a unique slug keeping the value sanitized and within limits."""

    max_length = Tenant._meta.get_field("slug").max_length
    sanitized_base = sanitize_text_input(base_name, max_length=max_length) or "tenant"
    slug_base = slugify(sanitized_base) or "tenant"
    slug_base = slug_base.strip("-") or "tenant"
    slug_base = slug_base[:max_length]

    # Ensure we don't end up with an empty slug after trimming
    if not slug_base:
        slug_base = "tenant"

    candidate = slug_base
    suffix = 2
    while Tenant.objects.filter(slug=candidate).exists():
        suffix_str = f"-{suffix}"
        candidate = f"{slug_base[: max_length - len(suffix_str)]}{suffix_str}"
        suffix += 1
        if suffix > 99:
            raise serializers.ValidationError(
                "Não foi possível gerar um slug único para o tenant. Tente outro nome."
            )

    return candidate


class TenantSelfServiceSerializer(serializers.ModelSerializer):
    feature_flags = serializers.SerializerMethodField()
    branding = serializers.SerializerMethodField()
    plan = serializers.SerializerMethodField()
    billing_pending = serializers.SerializerMethodField()
    onboarding_state = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "slug",
            "plan",
            "billing_pending",
            "onboarding_state",
            "timezone",
            "currency",
            "preferred_language",
            "feature_flags",
            "branding",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_onboarding_state(self, obj):
        """
        Retorna estado do onboarding do tenant.

        Estados possíveis:
        - "billing_pending": Tenant sem assinatura ativa (precisa escolher plano)
        - "completed": Tenant com assinatura ativa (acesso liberado), ou tenant
          em billing_mode=promotional (nunca passa por checkout Stripe --
          exigir Subscription ativa deixaria QUALQUER tenant promocional
          preso no onboarding indefinidamente, já que nunca terá uma)

        Returns:
            str: "billing_pending" ou "completed"
        """
        # Tenants promocionais não são cobrados via Stripe -- nunca terão uma
        # Subscription, então o onboarding tem que ser considerado concluído
        # independentemente de billing.
        if obj.is_promotional_billing():
            return "completed"

        try:
            Subscription = apps.get_model("payments", "Subscription")

            # Verifica se tem assinatura ativa ou em trial
            has_active_subscription = Subscription.objects.filter(
                user__tenant=obj, status__in=["active", "trialing"]
            ).exists()

            if has_active_subscription:
                return "completed"

            # Se não tem assinatura, precisa escolher plano
            return "billing_pending"

        except LookupError:
            # Se o model Subscription não existir (improvável), assume completed
            return "completed"

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_billing_pending(self, obj):
        try:
            Subscription = apps.get_model("payments", "Subscription")
            sub = (
                Subscription.objects.filter(user__tenant=obj)
                .order_by("-updated_at", "-created_at")
                .first()
            )

            if sub and sub.status in ["past_due", "unpaid", "incomplete"]:
                return True
            return False
        except LookupError:
            return False

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_feature_flags(self, obj):
        return obj.get_feature_flags_dict()

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_branding(self, obj):
        return {
            "logo_url": obj.get_logo_url,
            "favicon_url": getattr(obj, "favicon_url", None),
            "app_name": obj.app_name or obj.name,
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_plan(self, obj):
        return {
            "tier": obj.plan_tier,
            "billing_mode": obj.billing_mode,
            "promotional_expires_at": obj.promotional_expires_at,
            "promotional_converts_to_plan": obj.promotional_converts_to_plan,
            "addons_enabled": obj.addons_enabled,
        }


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    tenant = TenantSelfServiceSerializer(read_only=True)
    plan = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "username",
            "email",
            "password",
            "salon_name",
            "phone_number",
            "tenant",
            "plan",
        ]
        read_only_fields = ["id", "tenant"]

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

    def validate_email(self, value):
        """Normalizar e garantir unicidade do email."""
        if not value:
            return value

        normalized = CustomUser.objects.normalize_email(value.strip())
        if CustomUser.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError(
                "Já existe uma conta registada com este e-mail."
            )
        return normalized

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

    @transaction.atomic
    def create(self, validated_data):
        data = cast(Dict[str, Any], validated_data)

        salon_display_name = data.get("salon_name") or data.get("username", "")
        sanitized_display_name = sanitize_text_input(salon_display_name, max_length=255)
        if not sanitized_display_name:
            sanitized_display_name = sanitize_text_input(
                data["username"], max_length=255
            )

        tenant_slug = _generate_unique_tenant_slug(sanitized_display_name)

        # O servidor decide sozinho se o tenant é Founder, com base apenas
        # na disponibilidade de vagas — o `plan` enviado pelo cliente é
        # aceite (não quebra o contrato da API) mas não influencia esta
        # decisão.
        is_founder = FounderService.can_assign_founder()

        tenant = Tenant.objects.create(
            name=sanitized_display_name or data["username"],
            slug=tenant_slug,
            is_founder=is_founder,
        )

        user = CustomUser.objects.create_user(
            username=data["username"],
            email=data.get("email"),
            password=data["password"],
            salon_name=data.get("salon_name") or sanitized_display_name,
            phone_number=data.get("phone_number", ""),
            tenant=tenant,
        )

        TenantStaffMember.objects.create(
            tenant=tenant,
            user=user,
            role=TenantStaffMember.Role.OWNER,
            status=TenantStaffMember.Status.ACTIVE,
            activated_at=timezone.now(),
        )

        audit_logger.info(
            "Tenant self-service criado com sucesso",
            extra={
                "event": "tenant_self_service_created",
                "tenant_id": tenant.id,
                "tenant_slug": tenant.slug,
                "user_id": user.id,
                "owner_email": user.email,
            },
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


class TenantStaffMemberSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    photo = serializers.ImageField(source="user.photo", read_only=True)
    birthday = serializers.DateField(source="user.birthday", read_only=True)
    role = serializers.ChoiceField(choices=TenantStaffMemberRole, read_only=True)
    status = serializers.ChoiceField(choices=TenantStaffMemberStatus, read_only=True)

    class Meta:
        model = TenantStaffMember
        fields = [
            "id",
            "role",
            "status",
            "email",
            "username",
            "first_name",
            "last_name",
            "photo",
            "birthday",
            "invited_at",
            "activated_at",
            "deactivated_at",
            "created_at",
            "updated_at",
        ]


class StaffInviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=TenantStaffMemberRole, default=TenantStaffMemberRole.collaborator
    )
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    photo = serializers.ImageField(required=False, allow_null=True)
    birthday = serializers.DateField(required=False, allow_null=True)

    def validate_email(self, value):
        normalized = CustomUser.objects.normalize_email(value.strip())
        if not normalized:
            raise ValidationError("E-mail inválido.")
        return normalized

    def validate_photo(self, value):
        if value:
            from .validators import validate_profile_image

            validate_profile_image(value)
        return value

    def validate_birthday(self, value):
        return _validate_optional_birthday(value)

    def create(self, validated_data):
        request = self.context["request"]
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise ValidationError("Usuário autenticado não possui tenant associado.")

        role = validated_data.get("role")
        if request.user.staff_role not in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        ):
            raise ValidationError("Permissão negada para convidar membros de equipe.")
        if (
            role == TenantStaffMemberRole.manager
            and request.user.staff_role != TenantStaffMember.Role.OWNER
        ):
            raise ValidationError("Apenas owner pode convidar novos managers.")

        email = validated_data["email"]
        first_name = validated_data.get("first_name", "")
        last_name = validated_data.get("last_name", "")
        photo = validated_data.get("photo", serializers.empty)
        birthday = validated_data.get("birthday", serializers.empty)

        user = CustomUser.objects.filter(email__iexact=email).first()
        if user:
            update_fields = []
            if user.tenant_id and user.tenant_id != tenant.id:
                raise ValidationError("Usuário já pertence a outro tenant.")
            if not user.tenant_id:
                user.tenant = tenant
                update_fields.append("tenant")
            if first_name:
                user.first_name = first_name
                update_fields.append("first_name")
            if last_name:
                user.last_name = last_name
                update_fields.append("last_name")
            if photo is not serializers.empty:
                user.photo = photo
                update_fields.append("photo")
            if birthday is not serializers.empty:
                user.birthday = birthday
                update_fields.append("birthday")
            if update_fields:
                user.save(update_fields=list(dict.fromkeys(update_fields)))
        else:
            username_base = slugify(email.split("@")[0]) or "user"
            username = username_base
            suffix = 2
            while CustomUser.objects.filter(username=username).exists():
                username = f"{username_base}-{suffix}"
                suffix += 1

            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                tenant=tenant,
                password=CustomUser.objects.make_random_password(),
                first_name=first_name,
                last_name=last_name,
            )
            extra_fields = []
            if photo is not serializers.empty:
                user.photo = photo
                extra_fields.append("photo")
            if birthday is not serializers.empty:
                user.birthday = birthday
                extra_fields.append("birthday")
            user.set_unusable_password()
            extra_fields.append("password")
            user.save(update_fields=extra_fields)

        # Mapear role (Enum) para TextChoices do modelo
        model_role = (
            TenantStaffMember.Role.MANAGER
            if role == TenantStaffMemberRole.manager
            else TenantStaffMember.Role.COLLABORATOR
        )

        staff_member, _created = TenantStaffMember.objects.get_or_create(
            tenant=tenant,
            user=user,
            defaults={
                "role": model_role,
                "status": TenantStaffMember.Status.INVITED,
            },
        )

        if staff_member.role != TenantStaffMember.Role.OWNER:
            staff_member.role = model_role

        token = secrets.token_urlsafe(48)
        expires_at = timezone.now() + timedelta(days=7)
        staff_member.set_invite(token, expires_at, invited_by=request.user)

        self._invite_token = token
        self.instance = staff_member
        return staff_member

    @property
    def invite_token(self):
        return getattr(self, "_invite_token", None)


class StaffAcceptInviteSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(min_length=8)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    def validate_token(self, value):
        try:
            staff_member = TenantStaffMember.objects.select_related(
                "user", "tenant"
            ).get(invite_token=value)
        except TenantStaffMember.DoesNotExist as exc:
            raise ValidationError("Convite inválido ou já utilizado.") from exc

        if staff_member.status != TenantStaffMember.Status.INVITED:
            raise ValidationError("Convite já foi processado.")

        if (
            staff_member.invite_token_expires_at
            and timezone.now() > staff_member.invite_token_expires_at
        ):
            raise ValidationError("Convite expirado.")

        self._staff_member = staff_member
        return value

    def save(self, **kwargs):
        staff_member: TenantStaffMember = self._staff_member
        user = staff_member.user

        password = self.validated_data["password"]
        user.set_password(password)

        first_name = self.validated_data.get("first_name")
        last_name = self.validated_data.get("last_name")
        fields_to_update = ["password"]
        if first_name is not None:
            user.first_name = first_name
            fields_to_update.append("first_name")
        if last_name is not None:
            user.last_name = last_name
            fields_to_update.append("last_name")
        user.save(update_fields=fields_to_update)

        staff_member.mark_activated()
        return staff_member


class StaffUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=TenantStaffMemberRole, required=False)
    status = serializers.ChoiceField(choices=TenantStaffMemberStatus, required=False)

    def validate(self, attrs):
        if not attrs:
            raise ValidationError("Nenhuma alteração informada.")
        return attrs

    def update(self, instance: TenantStaffMember, validated_data):
        request = self.context["request"]
        role = validated_data.get("role")
        status = validated_data.get("status")

        if instance.role == TenantStaffMember.Role.OWNER:
            raise ValidationError("Owner não pode ter papel alterado.")

        update_fields = ["updated_at"]

        if role:
            if (
                request.user.staff_role != TenantStaffMember.Role.OWNER
                and role == TenantStaffMemberRole.manager
            ):
                raise ValidationError("Apenas owner pode promover para manager.")
            instance.role = (
                TenantStaffMember.Role.MANAGER
                if role == TenantStaffMemberRole.manager
                else TenantStaffMember.Role.COLLABORATOR
            )
            update_fields.append("role")

        if status:
            if status == TenantStaffMemberStatus.active:
                instance.status = TenantStaffMember.Status.ACTIVE
                instance.deactivated_at = None
                if "status" not in update_fields:
                    update_fields.append("status")
                update_fields.append("deactivated_at")
            else:
                instance.mark_disabled()
                return instance

        if len(update_fields) > 1:  # there is something to update besides updated_at
            instance.save(update_fields=list(dict.fromkeys(update_fields)))

        if instance.role == TenantStaffMember.Role.COLLABORATOR:
            instance.ensure_professional()
        elif status == TenantStaffMember.Status.ACTIVE:
            instance._set_professionals_active(active=True)

        return instance


class StaffContactUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    photo = serializers.ImageField(required=False, allow_null=True)
    birthday = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        instance: TenantStaffMember = self.instance
        if not attrs:
            raise ValidationError("Nenhuma alteração informada.")

        email = attrs.get("email")
        if email is not None:
            email = email.strip().lower()
            attrs["email"] = email

            if (
                instance
                and instance.role == TenantStaffMember.Role.OWNER
                and email != (instance.user.email or "").strip().lower()
            ):
                raise ValidationError(
                    "Owner não pode ter e-mail alterado por este endpoint."
                )

            user = instance.user if instance else None
            conflict = CustomUser.objects.filter(email__iexact=email)
            if user:
                conflict = conflict.exclude(id=user.id)
            if conflict.exists():
                raise ValidationError(
                    {"email": "E-mail já está em uso por outro usuário."}
                )

        return attrs

    def validate_photo(self, value):
        if value:
            from .validators import validate_profile_image

            validate_profile_image(value)
        return value

    def validate_birthday(self, value):
        return _validate_optional_birthday(value)

    def update(self, instance: TenantStaffMember, validated_data):
        user = instance.user
        email = validated_data.get("email")
        first_name = validated_data.get("first_name", serializers.empty)
        last_name = validated_data.get("last_name", serializers.empty)
        photo = validated_data.get("photo", serializers.empty)
        birthday = validated_data.get("birthday", serializers.empty)

        updates = []
        if email is not None and email != (user.email or "").strip().lower():
            user.email = email
            updates.append("email")
        if first_name is not serializers.empty:
            user.first_name = first_name
            updates.append("first_name")
        if last_name is not serializers.empty:
            user.last_name = last_name
            updates.append("last_name")
        if photo is not serializers.empty:
            user.photo = photo
            updates.append("photo")
        if birthday is not serializers.empty:
            user.birthday = birthday
            updates.append("birthday")

        if updates:
            user.save(update_fields=list(dict.fromkeys(updates)))

        return instance


class UserSelfSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    photo = serializers.ImageField(read_only=True)
    birthday = serializers.DateField(read_only=True)
    theme_preference = serializers.CharField(read_only=True)
    language_preference = serializers.CharField(read_only=True)
    onboarding_status = serializers.JSONField(read_only=True)
    is_owner = serializers.SerializerMethodField()
    staff_role = serializers.SerializerMethodField()

    def get_is_owner(self, instance):
        """Retorna True se o usuário é owner do tenant."""
        return instance.is_owner

    def get_staff_role(self, instance):
        """Retorna o role do usuário (owner, manager, collaborator) ou None."""
        return instance.staff_role

    def to_representation(self, instance):
        return {
            "id": instance.id,
            "username": instance.username or "",
            "email": instance.email or "",
            "first_name": instance.first_name or "",
            "last_name": instance.last_name or "",
            "photo": instance.photo.url if instance.photo else None,
            "birthday": instance.birthday.isoformat() if instance.birthday else None,
            "theme_preference": instance.theme_preference,
            "language_preference": getattr(instance, "language_preference", "system"),
            "onboarding_status": instance.onboarding_status,
            "is_owner": self.get_is_owner(instance),
            "staff_role": self.get_staff_role(instance),
        }


class UserSelfUpdateSerializer(serializers.Serializer):
    theme_preference = serializers.ChoiceField(
        choices=CustomUser.ThemePreference.choices, required=False
    )
    onboarding_status = serializers.JSONField(required=False)
    photo = serializers.ImageField(required=False, allow_null=True)
    birthday = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs:
            raise ValidationError("Nenhum campo para atualização informado")
        return attrs

    def validate_photo(self, value):
        if value:
            from .validators import validate_profile_image

            validate_profile_image(value)
        return value

    def validate_birthday(self, value):
        return _validate_optional_birthday(value)

    def update(self, instance: CustomUser, validated_data):
        updated_fields = []

        if "theme_preference" in validated_data:
            instance.theme_preference = validated_data["theme_preference"]
            updated_fields.append("theme_preference")

        if "onboarding_status" in validated_data:
            onboarding_status = validated_data["onboarding_status"]
            if not isinstance(onboarding_status, dict):
                raise ValidationError(
                    {"onboarding_status": "onboarding_status deve ser um objeto JSON"}
                )
            current_status = instance.onboarding_status or {}
            current_status.update(onboarding_status)
            instance.onboarding_status = current_status
            updated_fields.append("onboarding_status")

        if "photo" in validated_data:
            instance.photo = validated_data["photo"]
            updated_fields.append("photo")

        if "birthday" in validated_data:
            instance.birthday = validated_data["birthday"]
            updated_fields.append("birthday")

        if updated_fields:
            instance.save(update_fields=list(dict.fromkeys(updated_fields)))

        return instance


class EmailTokenObtainPairSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            raise AuthenticationFailed("Credenciais inválidas.")

        if not user.check_password(password):
            raise AuthenticationFailed("Credenciais inválidas.")

        if not user.is_active:
            raise AuthenticationFailed("Conta inativa. Entre em contato com o suporte.")

        if getattr(user, "is_ops_user", False):
            raise AuthenticationFailed(
                "Acesso restrito ao console Ops. Utilize o endpoint ops/auth/login."
            )

        refresh = RefreshToken.for_user(user)
        refresh["scope"] = "tenant"
        refresh["ops_role"] = None
        refresh["jwt_version"] = getattr(user, "jwt_version", 1)
        if user.tenant:
            refresh["tenant_slug"] = user.tenant.slug
            refresh["tenant_id"] = str(user.tenant_id)

        access_token = refresh.access_token
        access_token["scope"] = refresh["scope"]
        access_token["ops_role"] = refresh["ops_role"]
        access_token["jwt_version"] = refresh["jwt_version"]
        if user.tenant:
            access_token["tenant_slug"] = user.tenant.slug
            access_token["tenant_id"] = str(user.tenant_id)

        tenant_payload = None
        if user.tenant:
            tenant_payload = TenantSelfServiceSerializer(user.tenant).data

        return {
            "refresh": str(refresh),
            "access": str(access_token),
            "tenant": tenant_payload,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "photo": user.photo.url if user.photo else None,
                "birthday": user.birthday.isoformat() if user.birthday else None,
                "theme_preference": user.theme_preference,
                "language_preference": getattr(user, "language_preference", "system"),
                "staff_role": user.staff_role,
            },
        }


class EmailTokenRefreshSerializer(TokenRefreshSerializer):
    """Refresh de token com validação de jwt_version para tenant users."""

    def validate(self, attrs):
        raw_refresh = attrs.get("refresh")
        if not raw_refresh:
            raise AuthenticationFailed("Token de refresh é obrigatório.")

        try:
            refresh = RefreshToken(raw_refresh)
        except Exception:
            raise AuthenticationFailed("Token inválido ou expirado.")

        user_id = refresh.payload.get("user_id")
        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            raise AuthenticationFailed("Usuário não encontrado.")

        if not user.is_active:
            raise AuthenticationFailed("Conta inativa.")

        if getattr(user, "is_ops_user", False):
            raise AuthenticationFailed(
                "Acesso restrito ao console Ops. Utilize o endpoint ops/auth/refresh."
            )

        token_version = refresh.payload.get("jwt_version")
        user_version = getattr(user, "jwt_version", 1)

        if token_version is None:
            if user_version > 1:
                raise AuthenticationFailed(
                    "Sessão invalidada (token sem versão). Faça login novamente."
                )
        elif token_version < user_version:
            raise AuthenticationFailed(
                "Sessão invalidada (versão do token antiga). Faça login novamente."
            )

        return super().validate(attrs)


class TenantMetaSerializer(serializers.ModelSerializer):
    """
    Serializer para informações públicas do tenant (branding + feature flags).
    Usado pelo endpoint /api/users/tenant/meta/
    """

    feature_flags = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()
    auto_invite_enabled = serializers.BooleanField(read_only=True)
    profile = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "name",
            "slug",
            "logo_url",
            "favicon_url",
            "app_name",
            "timezone",
            "currency",
            "preferred_language",
            "address_street",
            "address_number",
            "address_complement",
            "address_neighborhood",
            "address_city",
            "address_state",
            "address_zip",
            "address_country",
            "plan_tier",
            "feature_flags",
            "auto_invite_enabled",
            "profile",
        ]
        read_only_fields = [
            "name",
            "slug",
            "logo_url",
            "favicon_url",
            "app_name",
            "timezone",
            "currency",
            "preferred_language",
            "address_street",
            "address_number",
            "address_complement",
            "address_neighborhood",
            "address_city",
            "address_state",
            "address_zip",
            "address_country",
            "plan_tier",
            "feature_flags",
            "auto_invite_enabled",
            "profile",
        ]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_feature_flags(self, obj):
        """Retorna feature flags calculadas baseadas no plano"""
        return obj.get_feature_flags_dict()

    @extend_schema_field(OpenApiTypes.URI)
    def get_logo_url(self, obj):
        """Retorna a URL do logo (upload ou URL externa)"""
        return obj.get_logo_url

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_profile(self, obj):
        owner_email = None
        try:
            owner_member = (
                TenantStaffMember.objects.select_related("user")
                .filter(tenant=obj, role=TenantStaffMember.Role.OWNER)
                .first()
            )
            owner_email = getattr(getattr(owner_member, "user", None), "email", None)
        except Exception:
            owner_email = None
        return {
            "email": getattr(obj, "contact_email", None) or owner_email,
            "phone": getattr(obj, "contact_phone", None),
        }


class TenantPublicSerializer(serializers.ModelSerializer):
    """
    Serializer para informações PÚBLICAS do tenant (sem feature flags ou dados sensíveis).
    Usado pelo endpoint /api/public/tenants/{slug}/

    SEGURANÇA: Expõe apenas dados que podem ser vistos por qualquer pessoa (incluindo não-autenticados).
    """

    logo_url = serializers.SerializerMethodField()
    profile = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "slug",
            "logo_url",
            "favicon_url",
            "app_name",
            "timezone",
            "currency",
            "preferred_language",
            "address_street",
            "address_number",
            "address_complement",
            "address_neighborhood",
            "address_city",
            "address_state",
            "address_zip",
            "address_country",
            "profile",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.URI)
    def get_logo_url(self, obj):
        """Retorna a URL do logo (upload ou URL externa)"""
        return obj.get_logo_url

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_profile(self, obj):
        """
        Retorna dados públicos de contato.
        Não expõe email do owner se contact_email não estiver definido.
        """
        return {
            "email": getattr(obj, "contact_email", None),
            "phone": getattr(obj, "contact_phone", None),
        }


class TenantProfileSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=32
    )

    def validate_phone(self, value):
        if value is None:
            return value
        raw = str(value).strip()
        cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
        if cleaned and cleaned.count("+") > 1:
            raise serializers.ValidationError("Telefone inválido.")
        if cleaned and cleaned.startswith("+"):
            digits = cleaned[1:]
            if len(digits) < 8:
                raise serializers.ValidationError("Telefone muito curto.")
        elif cleaned:
            if len(cleaned) < 8:
                raise serializers.ValidationError("Telefone muito curto.")
        return cleaned


class TenantBrandingUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer para atualização de branding do tenant.
    Permite upload de logo.
    """

    auto_invite_enabled = serializers.BooleanField(required=False)

    class Meta:
        model = Tenant
        fields = [
            "logo",
            "logo_url",
            "favicon_url",
            "app_name",
            "auto_invite_enabled",
            "address_street",
            "address_number",
            "address_complement",
            "address_neighborhood",
            "address_city",
            "address_state",
            "address_zip",
            "address_country",
        ]
        extra_kwargs = {
            "logo": {"required": False},
            "logo_url": {"required": False},
            "favicon_url": {"required": False},
            "app_name": {"required": False},
            "auto_invite_enabled": {"required": False},
            "address_street": {"required": False},
            "address_number": {"required": False},
            "address_complement": {"required": False},
            "address_neighborhood": {"required": False},
            "address_city": {"required": False},
            "address_state": {"required": False},
            "address_zip": {"required": False},
            "address_country": {"required": False},
        }

    def validate(self, data):
        """Validação customizada para branding"""
        # Não permitir logo e logo_url ao mesmo tempo
        if "logo" in data and data["logo"] and "logo_url" in data and data["logo_url"]:
            raise serializers.ValidationError(
                "Não é possível enviar 'logo' e 'logo_url' simultaneamente. Use apenas um."
            )

        return data


class TenantBusinessHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantBusinessHours
        fields = ["id", "day_of_week", "start_time", "end_time", "is_active"]

    def validate(self, data):
        start = data.get("start_time")
        end = data.get("end_time")
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"end_time": "Horário de fim deve ser posterior ao horário de início."}
            )
        return data


class TenantModulesUpdateSerializer(serializers.Serializer):
    pwa_client_enabled = serializers.BooleanField(required=False)


# ============================================================================
# Serializers para Sistema de Créditos de Comunicação
# ============================================================================


class CommLedgerSerializer(serializers.ModelSerializer):
    """Serializer para histórico de transações de crédito."""

    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True, allow_null=True
    )
    transaction_type = serializers.ChoiceField(
        choices=CommLedgerTransactionType, read_only=True
    )
    status = serializers.ChoiceField(choices=CommLedgerStatus, read_only=True)

    class Meta:
        model = CommLedger
        fields = [
            "id",
            "transaction_type",
            "amount_eur",
            "balance_before",
            "balance_after",
            "status",
            "description",
            "reference_id",
            "expires_at",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreditBalanceSerializer(serializers.Serializer):
    """Serializer para saldo de créditos do tenant."""

    current_balance = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    total_purchased = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    total_consumed = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    total_bonus = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    can_purchase_extra = serializers.BooleanField(read_only=True)
    has_auto_renewal = serializers.BooleanField(read_only=True)


class ConsumeCreditsSerializer(serializers.Serializer):
    """Serializer para consumir créditos."""

    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Quantidade de créditos a consumir em EUR",
    )
    description = serializers.CharField(
        max_length=255,
        help_text="Descrição da transação (ex: 'SMS para +351912345678')",
    )
    reference_id = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text="ID de referência externa (ex: message_id)",
    )


class PurchaseCreditsSerializer(serializers.Serializer):
    """Serializer para compra de créditos (futuro uso com Stripe)."""

    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=5.00,  # Mínimo 5 EUR
        help_text="Quantidade de créditos a comprar em EUR (mínimo 5.00)",
    )

    def validate_amount(self, value):
        """Validar valores permitidos para compra."""
        allowed_amounts = [5.00, 10.00, 25.00, 50.00, 100.00]
        if float(value) not in allowed_amounts:
            raise serializers.ValidationError(
                f"Valor deve ser um dos seguintes: {', '.join(map(str, allowed_amounts))} EUR"
            )
        return value


class TenantNotificationsUpdateSerializer(serializers.Serializer):
    sms_enabled = serializers.BooleanField(required=False)
    whatsapp_enabled = serializers.BooleanField(required=False)
    push_mobile_enabled = serializers.BooleanField(required=False)
    push_web_enabled = serializers.BooleanField(required=False)

    def validate(self, attrs):
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    reset_url = serializers.CharField(required=False, allow_blank=True)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8)
