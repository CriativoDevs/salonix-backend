import logging

from django.core.cache import cache
from rest_framework import generics, status, filters
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.exceptions import (
    ValidationError,
    AuthenticationFailed,
    PermissionDenied,
    Throttled,
)

from drf_spectacular.utils import (
    extend_schema,
    OpenApiExample,
    OpenApiResponse,
    OpenApiParameter,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes

from rest_framework.exceptions import NotFound
from django.http import StreamingHttpResponse
import json
import time
import secrets

from salonix_backend.error_handling import TenantError, ErrorCodes
from .models import UserFeatureFlags, Tenant, TenantStaffMember, CommLedger, CustomUser
from .services import CreditService, TenantService, FounderService
from .permissions import IsActiveTenant, RequiresMobileAccess

from .serializers import (
    EmailTokenObtainPairSerializer,
    EmailTokenRefreshSerializer,
    TenantMetaSerializer,
    TenantBrandingUpdateSerializer,
    TenantModulesUpdateSerializer,
    TenantProfileSerializer,
    UserRegistrationSerializer,
    UserFeatureFlagsSerializer,
    UserFeatureFlagsUpdateSerializer,
    TenantSelfServiceSerializer,
    UserSelfSerializer,
    UserSelfUpdateSerializer,
    TenantStaffMemberSerializer,
    StaffInviteSerializer,
    StaffAcceptInviteSerializer,
    StaffUpdateSerializer,
    CommLedgerSerializer,
    CreditBalanceSerializer,
    ConsumeCreditsSerializer,
    PurchaseCreditsSerializer,
    TenantNotificationsUpdateSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
)
from .throttling import (
    UsersAuthLoginThrottle,
    UsersAuthRegisterThrottle,
    UsersTenantMetaPublicThrottle,
)
from .security import enforce_captcha_or_raise
from .observability import (
    USERS_AUTH_EVENTS_TOTAL,
    USERS_THROTTLED_TOTAL,
    USERS_PASSWORD_RESET_EVENTS_TOTAL,
    USERS_SSE_EVENTS_TOTAL,
    USERS_STAFF_INVITE_EVENTS_TOTAL,
)
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.auth import get_user_model
from django.conf import settings
from core.email_utils import send_staff_invite_email
from .serializers import StaffContactUpdateSerializer
from .throttling import UsersPasswordResetThrottle as _UsersPasswordResetThrottle
from .throttling import (
    UsersStaffResendInviteThrottle,
)
from django.utils import timezone
from datetime import timedelta


bootstrap_logger = logging.getLogger("users.bootstrap")
security_logger = logging.getLogger("users.security")
logger = logging.getLogger(__name__)


def _me_tenant_cache_key(user_id: int, tenant_id: int, tenant_updated_at):
    updated_ts = "0"
    if tenant_updated_at:
        try:
            updated_ts = str(int(tenant_updated_at.timestamp()))
        except Exception:  # pragma: no cover - fallback caso timestamp falhe
            updated_ts = tenant_updated_at.isoformat()
    return f"users:me-tenant:{user_id}:{tenant_id}:{updated_ts}"


class UserRegistrationView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]
    throttle_classes = [UsersAuthRegisterThrottle]
    throttle_scope = "auth_register"

    @extend_schema(
        summary="Registro de usuário",
        description="Cria novo usuário/tenant. Requer captcha se CAPTCHA_ENABLED=True.",
        parameters=[
            OpenApiParameter(
                name="X-Captcha-Key",
                location=OpenApiParameter.HEADER,
                description="Chave do captcha (alternativa ao body)",
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="X-Captcha-Value",
                location=OpenApiParameter.HEADER,
                description="Valor do captcha (alternativa ao body)",
                required=False,
                type=OpenApiTypes.STR,
            ),
        ],
        request=UserRegistrationSerializer,
        responses={
            201: UserRegistrationSerializer,
            400: OpenApiResponse(description="Erro de validação ou Captcha inválido"),
            429: OpenApiResponse(
                description="Rate Limit Excedido (verificar header Retry-After)"
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        try:
            enforce_captcha_or_raise(request)
        except ValidationError:
            USERS_AUTH_EVENTS_TOTAL.labels(event="register", result="failure").inc()
            raise
        resp = super().post(request, *args, **kwargs)
        if resp.status_code in (status.HTTP_201_CREATED, status.HTTP_200_OK):
            USERS_AUTH_EVENTS_TOTAL.labels(event="register", result="success").inc()
            logger.info(
                "User registered successfully",
                extra={
                    "email": request.data.get("email"),
                    "status_code": resp.status_code,
                },
            )
        else:
            USERS_AUTH_EVENTS_TOTAL.labels(event="register", result="failure").inc()
            logger.warning(
                "User registration failed",
                extra={
                    "email": request.data.get("email"),
                    "status_code": resp.status_code,
                    "errors": resp.data,
                },
            )
        return resp

    def throttled(self, request, wait):  # pragma: no cover - DRF handles 429 response
        try:
            USERS_THROTTLED_TOTAL.labels(scope="auth_register").inc()
        finally:
            return super().throttled(request, wait)


class MeFeatureFlagsView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, RequiresMobileAccess]
    serializer_class = UserFeatureFlagsSerializer  # default para GET

    def get_object(self):
        flags, _ = UserFeatureFlags.objects.get_or_create(user=self.request.user)
        return flags

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return UserFeatureFlagsUpdateSerializer
        return UserFeatureFlagsSerializer


class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_classes = [UsersAuthLoginThrottle]
    throttle_scope = "auth_login"

    @extend_schema(
        summary="Login (JWT)",
        description="Obtém par de tokens (access/refresh) + contexto do tenant. Requer captcha se CAPTCHA_ENABLED=True.",
        parameters=[
            OpenApiParameter(
                name="X-Captcha-Key",
                location=OpenApiParameter.HEADER,
                description="Chave do captcha (alternativa ao body)",
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="X-Captcha-Value",
                location=OpenApiParameter.HEADER,
                description="Valor do captcha (alternativa ao body)",
                required=False,
                type=OpenApiTypes.STR,
            ),
        ],
        responses={
            200: EmailTokenObtainPairSerializer,
            400: OpenApiResponse(
                description="Credenciais inválidas ou Captcha inválido"
            ),
            401: OpenApiResponse(description="Não autorizado"),
            429: OpenApiResponse(
                description="Rate Limit Excedido (verificar header Retry-After)"
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        # Read X-App-Type header (admin/client/web)
        app_type = request.headers.get("X-App-Type", "web").lower()

        try:
            enforce_captcha_or_raise(request)
        except ValidationError:
            USERS_AUTH_EVENTS_TOTAL.labels(event="login", result="failure").inc()
            raise
        resp = super().post(request, *args, **kwargs)

        # Validate mobile app access if authentication succeeded
        if resp.status_code in (status.HTTP_201_CREATED, status.HTTP_200_OK):
            USERS_AUTH_EVENTS_TOTAL.labels(event="login", result="success").inc()
            logger.info(
                "User logged in successfully",
                extra={
                    "email": request.data.get("email"),
                    "status_code": resp.status_code,
                    "app_type": app_type,
                },
            )

            # Validate plan for mobile app access (admin/client)
            if app_type in ["admin", "client"]:
                user_email = request.data.get("email")
                try:
                    user = CustomUser.objects.get(email=user_email)
                    tenant = user.tenant

                    if not tenant:
                        USERS_AUTH_EVENTS_TOTAL.labels(
                            event=f"login_{app_type}_denied", result="failure"
                        ).inc()
                        return Response(
                            {"detail": "Usuário não possui tenant associado."},
                            status=status.HTTP_403_FORBIDDEN,
                        )

                    # Validate Admin App access (Pro+ required)
                    if app_type == "admin" and not tenant.can_use_native_admin():
                        USERS_AUTH_EVENTS_TOTAL.labels(
                            event="login_admin_denied", result="failure"
                        ).inc()
                        logger.warning(
                            "Admin app login denied - insufficient plan",
                            extra={
                                "tenant_id": tenant.id,
                                "tenant_slug": tenant.slug,
                                "current_plan": tenant.plan_tier,
                                "required_plan": "pro",
                                "user_email": user_email,
                            },
                        )
                        return Response(
                            {
                                "detail": "Seu plano não permite acesso ao Admin App. Upgrade para Pro para desbloquear.",
                                "plan_required": "pro",
                                "current_plan": tenant.plan_tier,
                                "upgrade_url": "/pricing",
                            },
                            status=status.HTTP_403_FORBIDDEN,
                        )

                    # Validate Client App access (Pro required)
                    if app_type == "client" and not tenant.can_use_native_client():
                        USERS_AUTH_EVENTS_TOTAL.labels(
                            event="login_client_denied", result="failure"
                        ).inc()
                        logger.warning(
                            "Client app login denied - insufficient plan",
                            extra={
                                "tenant_id": tenant.id,
                                "tenant_slug": tenant.slug,
                                "current_plan": tenant.plan_tier,
                                "required_plan": "pro",
                                "user_email": user_email,
                            },
                        )
                        return Response(
                            {
                                "detail": "Seu plano não permite acesso ao Client App. Upgrade para Pro para desbloquear.",
                                "plan_required": "pro",
                                "current_plan": tenant.plan_tier,
                                "upgrade_url": "/pricing",
                            },
                            status=status.HTTP_403_FORBIDDEN,
                        )

                    logger.info(
                        f"{app_type.capitalize()} app access granted",
                        extra={
                            "tenant_id": tenant.id,
                            "tenant_slug": tenant.slug,
                            "current_plan": tenant.plan_tier,
                            "user_email": user_email,
                        },
                    )

                except CustomUser.DoesNotExist:
                    logger.error(
                        f"User not found after successful auth: {user_email}",
                        extra={"email": user_email},
                    )
        else:
            USERS_AUTH_EVENTS_TOTAL.labels(event="login", result="failure").inc()
            logger.warning(
                "User login failed",
                extra={
                    "email": request.data.get("email"),
                    "status_code": resp.status_code,
                    "errors": resp.data,
                },
            )
        return resp

    def throttled(self, request, wait):  # pragma: no cover
        try:
            USERS_THROTTLED_TOTAL.labels(scope="auth_login").inc()
        finally:
            return super().throttled(request, wait)


class EmailTokenRefreshView(TokenRefreshView):
    serializer_class = EmailTokenRefreshSerializer
    permission_classes = [AllowAny]


class FounderAvailabilityView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [UsersTenantMetaPublicThrottle]
    throttle_scope = "tenant_meta_public"

    @extend_schema(
        summary="Disponibilidade do Plano Founder",
        description="Retorna a quantidade total, usada e restante de vagas para o plano Founder.",
        responses={
            200: OpenApiResponse(
                description="Dados de disponibilidade",
                examples=[
                    OpenApiExample(
                        "Exemplo",
                        value={
                            "total_limit": 500,
                            "used_count": 123,
                            "remaining_count": 377,
                        },
                    )
                ],
            )
        },
    )
    def get(self, request):
        availability = FounderService.get_availability()

        # Se usuário autenticado, verificar elegibilidade pessoal
        if (
            request.user
            and request.user.is_authenticated
            and hasattr(request.user, "tenant")
        ):
            tenant = request.user.tenant
            logger.info(
                f"[FounderAvailability] User {request.user.email} tenant {tenant.slug}: "
                f"is_founder={tenant.is_founder}, plan_tier={tenant.plan_tier}"
            )
            can_assign = FounderService.can_assign_founder(tenant)
            logger.info(
                f"[FounderAvailability] Tenant {tenant.slug} can_assign_founder: {can_assign}"
            )
            if not can_assign:
                # Se não for elegível (ex: já teve founder e cancelou), mostramos 0 vagas restantes para ele
                # Isso fará o frontend esconder o card do Founder
                original_remaining = availability["remaining_count"]
                availability["remaining_count"] = 0
                logger.info(
                    f"[FounderAvailability] Tenant {tenant.slug} NOT ELIGIBLE - "
                    f"Overriding remaining_count from {original_remaining} to 0"
                )

        return Response(availability, status=status.HTTP_200_OK)


class TenantMetaView(APIView):
    """
    GET /api/users/tenant/meta/
    PATCH /api/users/tenant/meta/

    Endpoint público para obter metadados do tenant (branding + feature flags).
    Aceita tenant via query parameter 'tenant' ou header 'X-Tenant-Slug'.

    PATCH requer autenticação e permite atualizar branding (logo, favicon_url, app_name).
    """

    def get_permissions(self):
        """Permissões dinâmicas: público para GET, autenticado para PATCH"""
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated(), IsActiveTenant()]

    def get_throttles(self):
        # throttle apenas no GET público
        if self.request.method == "GET":
            self.throttle_scope = "tenant_meta_public"
            return [UsersTenantMetaPublicThrottle()]
        return []

    def get_tenant(self, request):
        """Obter tenant baseado no request"""
        # Para GET: usar query param ou header
        if request.method == "GET":
            tenant_slug = request.GET.get("tenant") or request.headers.get(
                "X-Tenant-Slug"
            )
            if not tenant_slug:
                raise TenantError(
                    "Parâmetro 'tenant' ou header 'X-Tenant-Slug' é obrigatório",
                    code=ErrorCodes.VALIDATION_REQUIRED_FIELD,
                )
        else:
            # Para PATCH: usar tenant do usuário autenticado
            if not hasattr(request.user, "tenant") or not request.user.tenant:
                raise TenantError(
                    "Usuário não possui tenant associado",
                    code=ErrorCodes.BUSINESS_TENANT_NOT_FOUND,
                )
            return request.user.tenant

        try:
            return Tenant.objects.get(slug=tenant_slug, is_active=True)
        except Tenant.DoesNotExist:
            default_slug = (
                str(getattr(settings, "DEFAULT_TENANT_SLUG", "timelyone"))
                .strip()
                .lower()
            )
            normalized = str(tenant_slug).strip().lower()

            # Permite fallback para aliases comuns de staging
            # Isso resolve o problema de URLs como 'timelyone-staging.pythonanywhere.com'
            is_staging_alias = normalized in [
                "timelyone-staging",
                "staging",
                "staging-app",
            ]

            if normalized == default_slug or is_staging_alias:
                # Se for um alias conhecido ou o próprio default, usamos o default_slug
                target_slug = default_slug

                tenant, _created = Tenant.objects.get_or_create(
                    slug=target_slug,
                    defaults={
                        "name": "TimelyOne",
                        "is_active": True,
                    },
                )
                if not tenant.is_active:
                    tenant.is_active = True
                    tenant.save(update_fields=["is_active", "updated_at"])
                return tenant

            raise TenantError(
                f"Tenant '{tenant_slug}' não encontrado ou inativo",
                code=ErrorCodes.BUSINESS_TENANT_NOT_FOUND,
            )

    @extend_schema(
        responses=OpenApiResponse(
            response=TenantMetaSerializer,
            description="Retorna metadados do tenant. Cabeçalho de resposta: Content-Language",
        ),
        parameters=[
            OpenApiParameter(
                name="Accept-Language",
                location=OpenApiParameter.HEADER,
                required=False,
                type=OpenApiTypes.STR,
                description="Idioma preferido da resposta (suportado: pt-PT, en)",
            )
        ],
    )
    def get(self, request):
        """Retornar metadados do tenant especificado"""
        # TenantError será tratado automaticamente pelo custom_exception_handler
        tenant = self.get_tenant(request)

        try:
            from django.contrib.auth import get_user_model
            from payments.services import SubscriptionService

            User = get_user_model()
            any_user = User.objects.filter(tenant=tenant).order_by("id").first()
            if any_user:
                current = SubscriptionService.get_current_subscription(any_user) or {}
                plan_code = current.get("plan_code")
                if plan_code and tenant.plan_tier != plan_code:
                    old = tenant.plan_tier
                    tenant.plan_tier = plan_code
                    tenant.save(update_fields=["plan_tier", "updated_at"])
                    bootstrap_logger.info(
                        "tenant.meta.plan_sync",
                        extra={
                            "tenant_id": tenant.id,
                            "tenant_slug": tenant.slug,
                            "old_plan": old,
                            "new_plan": plan_code,
                        },
                    )
        except Exception:
            pass

        # Serializar dados do tenant
        serializer = TenantMetaSerializer(tenant)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def throttled(self, request, wait):  # pragma: no cover
        try:
            USERS_THROTTLED_TOTAL.labels(scope="tenant_meta_public").inc()
        finally:
            return super().throttled(request, wait)

    @extend_schema(
        request=TenantBrandingUpdateSerializer,
        responses=TenantMetaSerializer,
    )
    def patch(self, request):
        """Atualizar branding do tenant (logo, favicon_url, app_name)"""
        try:
            tenant = self.get_tenant(request)
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verificar se o usuário é dono do tenant
        if request.user.tenant != tenant:
            return Response(
                {"detail": "Você não tem permissão para alterar este tenant."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Serializar e validar dados
        serializer = TenantBrandingUpdateSerializer(
            tenant, data=request.data, partial=True
        )
        if not serializer.is_valid():
            logger.warning(
                "Tenant branding update failed validation",
                extra={"errors": serializer.errors, "tenant_id": tenant.id},
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from typing import Any, Dict, cast

        vdata = cast(Dict[str, Any], serializer.validated_data)

        # Validar permissão para ativar auto invite
        if "auto_invite_enabled" in vdata:
            desired_state = bool(vdata["auto_invite_enabled"])
            if desired_state and not tenant.pwa_client_enabled:
                return Response(
                    {
                        "detail": (
                            "Plano atual não permite convites automáticos. "
                            "Habilite o PWA Cliente para usar esta funcionalidade."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Limpar logo anterior se novo logo for enviado
        if vdata.get("logo"):
            if tenant.logo:
                tenant.logo.delete(save=False)
            vdata["logo_url"] = None

        serializer.save()

        logger.info(
            "Tenant branding updated successfully",
            extra={"tenant_id": tenant.id, "updated_fields": list(vdata.keys())},
        )

        response_serializer = TenantMetaSerializer(tenant)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class TenantProfileView(APIView):
    """
    GET /api/users/tenant/profile/
    PATCH /api/users/tenant/profile/

    Endpoint para obter/atualizar dados de contato do tenant (email/telefone).
    GET é público (resolve via 'tenant' ou 'X-Tenant-Slug'); PATCH exige owner/manager.
    """

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_throttles(self):
        if self.request.method == "GET":
            self.throttle_scope = "tenant_meta_public"
            return [UsersTenantMetaPublicThrottle()]
        return []

    def _resolve_tenant_for_get(self, request):
        tenant_slug = request.GET.get("tenant") or request.headers.get("X-Tenant-Slug")
        if not tenant_slug:
            raise TenantError(
                "Parâmetro 'tenant' ou header 'X-Tenant-Slug' é obrigatório",
                code=ErrorCodes.VALIDATION_REQUIRED_FIELD,
            )
        try:
            return Tenant.objects.get(slug=tenant_slug, is_active=True)
        except Tenant.DoesNotExist:
            raise TenantError(
                f"Tenant '{tenant_slug}' não encontrado ou inativo",
                code=ErrorCodes.BUSINESS_TENANT_NOT_FOUND,
            )

    def _resolve_tenant_for_patch(self, request):
        user = request.user
        tenant = getattr(user, "tenant", None)
        if not tenant:
            raise TenantError(
                "Usuário não possui tenant associado",
                code=ErrorCodes.BUSINESS_TENANT_NOT_FOUND,
            )
        if not (
            getattr(user, "is_superuser", False)
            or user.has_staff_role(
                TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
            )
        ):
            raise PermissionDenied(
                "Apenas owner ou manager podem atualizar perfil do tenant."
            )
        return tenant

    @extend_schema(
        responses=OpenApiResponse(
            response=TenantProfileSerializer,
            description="Retorna dados de contato do tenant. Cabeçalho de resposta: Content-Language",
        ),
        parameters=[
            OpenApiParameter(
                name="Accept-Language",
                location=OpenApiParameter.HEADER,
                required=False,
                type=OpenApiTypes.STR,
                description="Idioma preferido da resposta (suportado: pt-PT, en)",
            )
        ],
    )
    def get(self, request):
        tenant = self._resolve_tenant_for_get(request)
        try:
            owner_member = (
                TenantStaffMember.objects.select_related("user")
                .filter(tenant=tenant, role=TenantStaffMember.Role.OWNER)
                .first()
            )
            owner_email = getattr(getattr(owner_member, "user", None), "email", None)
        except Exception:
            owner_email = None
        serializer = TenantProfileSerializer(
            {
                "email": getattr(tenant, "contact_email", None) or owner_email,
                "phone": getattr(tenant, "contact_phone", None),
            }
        )
        return Response({"profile": serializer.data}, status=status.HTTP_200_OK)

    @extend_schema(request=TenantProfileSerializer, responses=TenantProfileSerializer)
    def patch(self, request):
        tenant = self._resolve_tenant_for_patch(request)

        payload = request.data or {}
        data = (
            payload.get("profile")
            if isinstance(payload.get("profile"), dict)
            else payload
        )

        serializer = TenantProfileSerializer(data=data)
        serializer.is_valid(raise_exception=True)

        validated = serializer.validated_data
        email = validated.get("email")
        phone = validated.get("phone")

        update_fields = []
        if email is not None:
            tenant.contact_email = email or None
            update_fields.append("contact_email")
        if phone is not None:
            tenant.contact_phone = phone or None
            update_fields.append("contact_phone")

        if update_fields:
            update_fields.append("updated_at")
            tenant.save(update_fields=update_fields)

        resp = {
            "profile": {
                "email": getattr(tenant, "contact_email", None),
                "phone": getattr(tenant, "contact_phone", None),
            }
        }
        return Response(resp, status=status.HTTP_200_OK)


class MeTenantView(APIView):
    permission_classes = [IsAuthenticated, IsActiveTenant, RequiresMobileAccess]
    CACHE_TTL = 30

    @extend_schema(
        responses=OpenApiResponse(
            response=TenantSelfServiceSerializer,
            description="Retorna metadados do tenant do usuário logado. Cabeçalho de resposta: Content-Language",
        ),
        parameters=[
            OpenApiParameter(
                name="Accept-Language",
                location=OpenApiParameter.HEADER,
                required=False,
                type=OpenApiTypes.STR,
                description="Idioma preferido da resposta (suportado: pt-PT, en)",
            )
        ],
    )
    def get(self, request):
        user = request.user
        tenant = getattr(user, "tenant", None)
        if getattr(user, "is_ops_user", False) or not tenant:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        # Sincronizar o plano do tenant com o serviço de subscrição antes de servir o bootstrap
        try:
            from payments.services import SubscriptionService

            current = SubscriptionService.get_current_subscription(user) or {}
            plan_code = current.get("plan_code")
            if plan_code and tenant.plan_tier != plan_code:
                old = tenant.plan_tier
                tenant.plan_tier = plan_code
                tenant.save(update_fields=["plan_tier", "updated_at"])
                bootstrap_logger.info(
                    "tenant.bootstrap.plan_sync",
                    extra={
                        "tenant_id": tenant.id,
                        "tenant_slug": tenant.slug,
                        "old_plan": old,
                        "new_plan": plan_code,
                    },
                )
        except Exception:
            pass

        cache_key = _me_tenant_cache_key(user.id, tenant.id, tenant.updated_at)
        payload = cache.get(cache_key)
        cached_hit = payload is not None

        if not cached_hit:
            payload = TenantSelfServiceSerializer(tenant).data
            cache.set(cache_key, payload, timeout=self.CACHE_TTL)

        bootstrap_logger.info(
            "Tenant bootstrap entregue",
            extra={
                "event": "tenant_bootstrap",
                "user_id": user.id,
                "user_email": getattr(user, "email", ""),
                "tenant_id": tenant.id,
                "tenant_slug": tenant.slug,
                "cached": cached_hit,
            },
        )

        return Response(payload, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Cancelar conta",
        description="Realiza o cancelamento (soft-delete) do tenant atual. Requer ser proprietário (Owner).",
        responses={
            204: OpenApiResponse(description="Conta cancelada com sucesso"),
            403: OpenApiResponse(
                description="Apenas o proprietário pode cancelar a conta"
            ),
            404: OpenApiResponse(description="Tenant não encontrado"),
        },
    )
    def delete(self, request):
        user = request.user
        tenant = getattr(user, "tenant", None)

        if not tenant:
            raise NotFound("Tenant não encontrado.")

        if not user.is_owner:
            raise PermissionDenied("Apenas o proprietário pode cancelar a conta.")

        TenantService.cancel_tenant(tenant, user)

        return Response(status=status.HTTP_204_NO_CONTENT)


class MeProfileView(APIView):
    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(
        responses=OpenApiResponse(
            response=UserSelfSerializer,
            description="Retorna perfil do usuário logado. Cabeçalho de resposta: Content-Language",
        ),
        parameters=[
            OpenApiParameter(
                name="Accept-Language",
                location=OpenApiParameter.HEADER,
                required=False,
                type=OpenApiTypes.STR,
                description="Idioma preferido da resposta (suportado: pt-PT, en)",
            )
        ],
    )
    def get(self, request):
        user = request.user
        serializer = UserSelfSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        description="Atualiza preferência de tema, status de onboarding, foto ou aniversário do usuário",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "theme_preference": {
                        "type": "string",
                        "enum": ["light", "dark", "system"],
                        "description": "Preferência de tema do usuário",
                    },
                    "onboarding_status": {
                        "type": "object",
                        "description": "Status do onboarding do usuário (JSON)",
                    },
                    "birthday": {
                        "type": "string",
                        "format": "date",
                        "nullable": True,
                        "description": "Data de aniversário opcional do usuário",
                    },
                },
                "required": [],
            }
        },
        responses={200: UserSelfSerializer},
    )
    def patch(self, request):
        user = request.user

        if not request.data:
            return Response(
                {"detail": "Nenhum campo para atualização informado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        theme_preference = request.data.get("theme_preference")
        if theme_preference is not None:
            valid_choices = [choice[0] for choice in CustomUser.ThemePreference.choices]
            if theme_preference not in valid_choices:
                return Response(
                    {
                        "detail": (
                            "theme_preference deve ser um dos valores: "
                            f"{', '.join(valid_choices)}"
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        onboarding_status = request.data.get("onboarding_status")
        if onboarding_status is not None and not isinstance(onboarding_status, dict):
            return Response(
                {"detail": "onboarding_status deve ser um objeto JSON"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = UserSelfUpdateSerializer(
            instance=user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        response_serializer = UserSelfSerializer(user)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class TenantModulesSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsActiveTenant, RequiresMobileAccess]

    @extend_schema(
        description=(
            "Atualiza módulos do tenant (ex.: PWA Cliente). Só permitido para owner/manager "
            "e plano Basic+."
        ),
        request=TenantModulesUpdateSerializer,
        responses={200: OpenApiResponse(description="ok")},
    )
    def patch(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise AuthenticationFailed("tenant_required")

        if request.user.staff_role not in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        ):
            raise PermissionDenied("Permissão negada.")

        serializer = TenantModulesUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        if "pwa_client_enabled" in v:
            desired = bool(v["pwa_client_enabled"])
            if desired and tenant.plan_tier not in (
                Tenant.PLAN_BASIC,
                Tenant.PLAN_PRO,
                Tenant.PLAN_FOUNDER,
            ):
                return Response(
                    {
                        "detail": (
                            "PWA Cliente disponível a partir do plano Basic. "
                            "Atualize seu plano para ativar."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            tenant.pwa_client_enabled = desired
            tenant.save(update_fields=["pwa_client_enabled", "updated_at"])

        return Response(
            {"pwa_client_enabled": tenant.pwa_client_enabled}, status=status.HTTP_200_OK
        )


class TenantStaffView(APIView):
    permission_classes = [IsAuthenticated, IsActiveTenant, RequiresMobileAccess]
    # Listar staff não deve ser afetado pelo throttle de convites
    serializer_class = TenantStaffMemberSerializer

    @extend_schema(
        responses={200: TenantStaffMemberSerializer(many=True)},
        description="Lista membros de equipe do tenant autenticado",
    )
    def get(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        if request.user.staff_role not in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        ):
            raise PermissionDenied("Permissão negada.")

        staff_qs = TenantStaffMember.objects.filter(tenant=tenant).select_related(
            "user"
        )
        serializer = TenantStaffMemberSerializer(staff_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=StaffInviteSerializer,
        responses=TenantStaffMemberSerializer,
        description="Convida um membro de staff. Retorna token e expiração no payload.",
    )
    def post(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        serializer = StaffInviteSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        staff_member = serializer.save()
        response_data = TenantStaffMemberSerializer(staff_member).data
        response_data["invite_token"] = serializer.invite_token
        response_data["invite_token_expires_at"] = staff_member.invite_token_expires_at

        # Envio de e-mail com link de aceite
        try:
            base = getattr(
                settings, "FRONTEND_BASE_URL", "http://localhost:5173"
            ).rstrip("/")
            token = serializer.invite_token or ""
            accept_url = f"{base}/staff/accept?token={token}"
            to_email = staff_member.user.email or ""
            inviter_name = (
                request.user.get_full_name()
                or request.user.email
                or request.user.username
            )
            if to_email:
                ok = send_staff_invite_email(
                    to_email=to_email,
                    accept_url=accept_url,
                    salon_name=tenant.name or "TimelyOne",
                    inviter_name=inviter_name,
                )
                USERS_STAFF_INVITE_EVENTS_TOTAL.labels(
                    event="invite", result="success" if ok else "failure"
                ).inc()
            else:
                USERS_STAFF_INVITE_EVENTS_TOTAL.labels(
                    event="invite", result="failure"
                ).inc()
        except Exception:
            USERS_STAFF_INVITE_EVENTS_TOTAL.labels(
                event="invite", result="failure"
            ).inc()

        return Response(response_data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=StaffUpdateSerializer,
        responses=TenantStaffMemberSerializer,
        description="Atualiza dados do membro de equipe (papel, status, etc.)",
    )
    def patch(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        member_id = request.data.get("id")
        if not member_id:
            raise ValidationError({"id": "Informe o identificador do membro."})

        try:
            staff_member = TenantStaffMember.objects.select_related("user").get(
                tenant=tenant, id=member_id
            )
        except TenantStaffMember.DoesNotExist as exc:
            raise NotFound("Membro de equipe não encontrado.") from exc

        if staff_member.role == TenantStaffMember.Role.OWNER:
            raise ValidationError("Owner não pode ser alterado por este endpoint.")

        if request.user.staff_role not in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        ):
            raise PermissionDenied("Permissão negada.")

        serializer = StaffUpdateSerializer(
            instance=staff_member, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        staff_member = serializer.save()
        response_data = TenantStaffMemberSerializer(staff_member).data
        return Response(response_data, status=status.HTTP_200_OK)

    def delete(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        member_id = request.data.get("id")
        if not member_id:
            raise ValidationError({"id": "Informe o identificador do membro."})

        try:
            staff_member = TenantStaffMember.objects.select_related("user").get(
                tenant=tenant, id=member_id
            )
        except TenantStaffMember.DoesNotExist as exc:
            raise NotFound("Membro de equipe não encontrado.") from exc

        if staff_member.role == TenantStaffMember.Role.OWNER:
            raise ValidationError("Owner não pode ser desativado.")

        if request.user.staff_role not in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        ):
            raise PermissionDenied("Permissão negada.")

        staff_member.mark_disabled()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TenantStaffResendInviteView(APIView):
    permission_classes = [IsAuthenticated, RequiresMobileAccess]
    throttle_classes = [UsersStaffResendInviteThrottle]
    throttle_scope = "users_staff_resend"

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        examples=[
            OpenApiExample("Payload", value={"id": 123}, request_only=True),
        ],
        responses=TenantStaffMemberSerializer,
        description="Reenvia convite para membro convidado. Gera novo token e expiração.",
    )
    def post(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        if request.user.staff_role not in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        ):
            raise PermissionDenied("Permissão negada.")

        member_id = request.data.get("id")
        if not member_id:
            raise ValidationError({"id": "Informe o identificador do membro."})

        try:
            staff_member = TenantStaffMember.objects.select_related("user").get(
                tenant=tenant, id=member_id
            )
        except TenantStaffMember.DoesNotExist as exc:
            raise NotFound("Membro de equipe não encontrado.") from exc

        if staff_member.role == TenantStaffMember.Role.OWNER:
            raise ValidationError("Owner não recebe convite.")

        if staff_member.status == TenantStaffMember.Status.ACTIVE:
            raise ValidationError("Membro já está ativo.")

        to_email = (staff_member.user.email or "").strip()
        if not to_email:
            return Response(
                {
                    "detail": "E-mail do membro ausente. Atualize o cadastro e tente novamente."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = secrets.token_urlsafe(48)
        expires_at = timezone.now() + timedelta(days=7)
        staff_member.set_invite(token, expires_at, invited_by=request.user)

        base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173").rstrip(
            "/"
        )
        accept_url = f"{base}/staff/accept?token={token}"
        inviter_name = (
            request.user.get_full_name() or request.user.email or request.user.username
        )

        try:
            ok = send_staff_invite_email(
                to_email=to_email,
                accept_url=accept_url,
                salon_name=tenant.name or "TimelyOne",
                inviter_name=inviter_name,
            )
            USERS_STAFF_INVITE_EVENTS_TOTAL.labels(
                event="invite", result="success" if ok else "failure"
            ).inc()
        except Exception:
            USERS_STAFF_INVITE_EVENTS_TOTAL.labels(
                event="invite", result="failure"
            ).inc()

        response_data = TenantStaffMemberSerializer(staff_member).data
        response_data["invite_token"] = token
        response_data["invite_token_expires_at"] = staff_member.invite_token_expires_at
        return Response(response_data, status=status.HTTP_200_OK)


class TenantStaffAcceptInviteView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        request=StaffAcceptInviteSerializer,
        responses=TenantStaffMemberSerializer,
        description="Aceita convite de membro de equipe e ativa o acesso",
    )
    def post(self, request):
        serializer = StaffAcceptInviteSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            staff_member = serializer.save()
            USERS_STAFF_INVITE_EVENTS_TOTAL.labels(
                event="accept", result="success"
            ).inc()
            response_data = TenantStaffMemberSerializer(staff_member).data
            return Response(response_data, status=status.HTTP_200_OK)
        except Exception:
            USERS_STAFF_INVITE_EVENTS_TOTAL.labels(
                event="accept", result="failure"
            ).inc()
            raise


class UsersPasswordResetThrottle(_UsersPasswordResetThrottle):
    pass


class TenantStaffAccessLinkView(APIView):
    permission_classes = [IsAuthenticated, RequiresMobileAccess]
    throttle_classes = [UsersPasswordResetThrottle]
    throttle_scope = "users_password_reset"

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        examples=[
            OpenApiExample("Payload", value={"id": 123}, request_only=True),
        ],
        responses=TenantStaffMemberSerializer,
        description="Envia link de acesso ao painel via redefinição de senha",
    )
    def post(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        if request.user.staff_role not in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        ):
            raise PermissionDenied("Permissão negada.")

        member_id = request.data.get("id")
        if not member_id:
            raise ValidationError({"id": "Informe o identificador do membro."})

        try:
            staff_member = TenantStaffMember.objects.select_related("user").get(
                tenant=tenant, id=member_id
            )
        except TenantStaffMember.DoesNotExist as exc:
            raise NotFound("Membro de equipe não encontrado.") from exc

        if staff_member.role == TenantStaffMember.Role.OWNER:
            raise ValidationError("Owner não recebe link.")

        if staff_member.status == TenantStaffMember.Status.DISABLED:
            raise ValidationError("Membro desativado.")

        to_email = (staff_member.user.email or "").strip()
        if not to_email:
            return Response(
                {
                    "detail": "E-mail do membro ausente. Atualize o cadastro e tente novamente."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Gerar token de redefinição de senha para acesso
        try:
            token_gen = PasswordResetTokenGenerator()
            token = token_gen.make_token(staff_member.user)
            uid = str(staff_member.user.pk)

            base = getattr(
                settings, "FRONTEND_BASE_URL", "http://localhost:5173"
            ).rstrip("/")
            link = f"{base}/reset-password?uid={uid}&token={token}"

            from core.email_utils import send_staff_access_link_email

            try:
                send_staff_access_link_email(
                    to_email=to_email,
                    access_url=link,
                    salon_name=tenant.name or "TimelyOne",
                )
            except Exception:
                pass

            from django.core.mail import EmailMultiAlternatives

            fail_silently = not (
                getattr(settings, "DEBUG", False)
                or getattr(settings, "ENV", "dev") == "dev"
            )

            subject = "Acesso ao painel • TimelyOne"
            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@localhost")
            text_body = (
                "Receba um link para acessar redefinindo sua senha.\n\n"
                f"Clique no link a seguir: {link}\n\n"
                "Se não foi você, ignore este e-mail."
            )
            html_body = f"""
            <div style=\"font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu, sans-serif; max-width:560px; margin:0 auto;\">
              <h2 style=\"margin:0 0 12px;\">Acesso ao painel</h2>
              <p style=\"margin:0 0 16px; color:#334155;\">Use o link abaixo para acessar o painel redefinindo sua senha.</p>
              <p style=\"margin:0 0 20px;\">
                <a href=\"{link}\" style=\"
                   display:inline-block; background:#0ea5e9; color:#fff; text-decoration:none;
                   padding:10px 16px; border-radius:8px; font-weight:600;\">Acessar</a>
              </p>
              <p style=\"margin:0 0 8px; color:#475569;\">Ou copie e cole este link no navegador:</p>
              <p style=\"margin:0 0 16px;\"><a href=\"{link}\">{link}</a></p>
              <p style=\"margin:24px 0 0; font-size:12px; color:#64748b;\">Se você não solicitou esta ação, pode ignorar este e-mail.</p>
            </div>
            """

            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=from_email,
                to=[to_email],
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=fail_silently)

            # Logar o link em dev para facilitar QA
            try:
                env_name = getattr(settings, "ENV", "dev")
            except Exception:
                env_name = "dev"
            if settings.DEBUG or env_name == "dev":
                security_logger.info(
                    f"Access link (dev): {link} | email={to_email}",
                    extra={
                        "event": "password_reset_link",
                        "email": to_email,
                        "link": link,
                        "request_id": getattr(request, "request_id", None),
                    },
                )

            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
                event="request", result="success"
            ).inc()
        except Exception:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
                event="request", result="failure"
            ).inc()

        response_data = TenantStaffMemberSerializer(staff_member).data
        response_data["access_link_sent"] = True
        return Response(response_data, status=status.HTTP_200_OK)


class TenantStaffContactUpdateView(APIView):
    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(
        request=StaffContactUpdateSerializer,
        responses=TenantStaffMemberSerializer,
        description="Atualiza informações de contato do membro de equipe",
    )
    def patch(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        if request.user.staff_role not in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        ):
            raise PermissionDenied("Permissão negada.")

        member_id = request.data.get("id")
        if not member_id:
            raise ValidationError({"id": "Informe o identificador do membro."})

        try:
            staff_member = TenantStaffMember.objects.select_related("user").get(
                tenant=tenant, id=member_id
            )
        except TenantStaffMember.DoesNotExist as exc:
            raise NotFound("Membro de equipe não encontrado.") from exc

        serializer = StaffContactUpdateSerializer(
            instance=staff_member, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        response_data = TenantStaffMemberSerializer(staff_member).data
        return Response(response_data, status=status.HTTP_200_OK)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [UsersPasswordResetThrottle]
    throttle_scope = "users_password_reset"
    serializer_class = PasswordResetRequestSerializer

    @extend_schema(
        summary="Solicitar Reset de Senha",
        description="Envia email com link de redefinição. Requer captcha se CAPTCHA_ENABLED=True.",
        parameters=[
            OpenApiParameter(
                name="X-Captcha-Key",
                location=OpenApiParameter.HEADER,
                description="Chave do captcha (alternativa ao body)",
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="X-Captcha-Value",
                location=OpenApiParameter.HEADER,
                description="Valor do captcha (alternativa ao body)",
                required=False,
                type=OpenApiTypes.STR,
            ),
        ],
        examples=[
            OpenApiExample(
                "Exemplo",
                value={"email": "user@example.com", "reset_url": "https://app/reset"},
                request_only=True,
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Solicitação processada (sempre OK para não vazar emails)"
            ),
            400: OpenApiResponse(description="Captcha inválido ou email ausente"),
            429: OpenApiResponse(description="Rate Limit Excedido"),
        },
    )
    def post(self, request):
        try:
            enforce_captcha_or_raise(request)
        except ValidationError:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
                event="request", result="failure"
            ).inc()
            return Response(
                {"detail": "captcha_invalid"}, status=status.HTTP_400_BAD_REQUEST
            )

        email = str(request.data.get("email", "")).strip().lower()
        if not email:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
                event="request", result="failure"
            ).inc()
            return Response(
                {"detail": "email_required"}, status=status.HTTP_400_BAD_REQUEST
            )

        User = get_user_model()
        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
                event="request", result="success"
            ).inc()
            # resposta neutra para não vazar existência
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        token_gen = PasswordResetTokenGenerator()
        token = token_gen.make_token(user)
        uid = str(user.pk)

        reset_url = (
            request.data.get("reset_url") or settings.STRIPE_CANCEL_URL
        )  # placeholder front URL
        # Montar link: {reset_url}?uid={uid}&token={token}
        link = f"{reset_url}?uid={uid}&token={token}"

        try:
            from django.core.mail import EmailMultiAlternatives

            fail_silently = not (
                getattr(settings, "DEBUG", False)
                or getattr(settings, "ENV", "dev") == "dev"
            )

            subject = "Recuperação de senha • TimelyOne"
            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@localhost")
            text_body = (
                "Recebemos um pedido para redefinir a sua senha.\n\n"
                f"Se foi você, clique no link a seguir: {link}\n\n"
                "Se não foi você, ignore este e-mail."
            )
            html_body = f"""
            <div style=\"font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu, sans-serif; max-width:560px; margin:0 auto;\">
              <h2 style=\"margin:0 0 12px;\">Redefinição de senha</h2>
              <p style=\"margin:0 0 16px; color:#334155;\">Recebemos um pedido para redefinir a sua senha.</p>
              <p style=\"margin:0 0 20px;\">
                <a href=\"{link}\" style=\"
                   display:inline-block; background:#0ea5e9; color:#fff; text-decoration:none;
                   padding:10px 16px; border-radius:8px; font-weight:600;\">Redefinir senha</a>
              </p>
              <p style=\"margin:0 0 8px; color:#475569;\">Ou copie e cole este link no navegador:</p>
              <p style=\"margin:0 0 16px;\"><a href=\"{link}\">{link}</a></p>
              <p style=\"margin:24px 0 0; font-size:12px; color:#64748b;\">Se você não solicitou esta ação, pode ignorar este e-mail.</p>
            </div>
            """

            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=from_email,
                to=[email],
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=fail_silently)
        except Exception as exc:
            # Mesmo com falha no envio, mantemos resposta neutra
            # Logar exceção para monitoramento em qualquer ambiente
            security_logger.error(
                "Falha ao enviar email de reset",
                extra={
                    "event": "password_reset_email_error",
                    "email": email,
                    "error": str(exc),
                    "request_id": getattr(request, "request_id", None),
                },
            )
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
                event="request", result="failure_send_email"
            ).inc()
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        # Logar o link de reset em ambiente de desenvolvimento para facilitar testes
        try:
            env_name = getattr(settings, "ENV", "dev")
        except Exception:
            env_name = "dev"
        if settings.DEBUG or env_name == "dev":
            # Alguns formatadores não mostram campos em 'extra'; incluir no próprio message
            security_logger.info(
                f"Password reset link (dev): {link} | email={email}",
                extra={
                    "event": "password_reset_link",
                    "email": email,
                    "link": link,
                    "request_id": getattr(request, "request_id", None),
                },
            )

        USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
            event="request", result="success"
        ).inc()
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer

    @extend_schema(
        description="Confirma o reset de senha com uid+token e define nova senha.",
        examples=[
            OpenApiExample(
                "Exemplo",
                value={"uid": "1", "token": "<token>", "new_password": "StrongPass123"},
                request_only=True,
            )
        ],
        responses={200: OpenApiResponse(description="password_updated", response=None)},
    )
    def post(self, request):
        uid = request.data.get("uid")
        token = request.data.get("token")
        new_password = request.data.get("new_password")
        if not uid or not token or not new_password:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
                event="confirm", result="failure"
            ).inc()
            return Response(
                {"detail": "missing_fields"}, status=status.HTTP_400_BAD_REQUEST
            )

        User = get_user_model()
        try:
            user = User.objects.get(pk=uid, is_active=True)
        except User.DoesNotExist:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
                event="confirm", result="failure"
            ).inc()
            raise AuthenticationFailed("invalid_token")

        token_gen = PasswordResetTokenGenerator()
        if not token_gen.check_token(user, token):
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
                event="confirm", result="failure"
            ).inc()
            raise AuthenticationFailed("invalid_token")

        if len(str(new_password)) < 8:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
                event="confirm", result="failure"
            ).inc()
            return Response(
                {"detail": "weak_password"}, status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])
        USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(
            event="confirm", result="success"
        ).inc()
        return Response({"status": "password_updated"}, status=status.HTTP_200_OK)


class CreditBalanceView(APIView):
    """Visualiza saldo e estatísticas de créditos de comunicação."""

    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(
        description="Obtém saldo atual e estatísticas de créditos de comunicação",
        responses={200: CreditBalanceSerializer},
    )
    def get(self, request):
        tenant = request.user.tenant
        credit_service = CreditService(tenant)

        balance = credit_service.get_credit_balance()
        stats = credit_service.get_credit_stats()

        data = {
            "current_balance": balance,
            "can_purchase_extra": tenant.can_purchase_extra_credits(),
            "has_auto_renewal": tenant.has_auto_credit_renewal(),
            **stats,
        }

        serializer = CreditBalanceSerializer(data)
        return Response(serializer.data)


class CreditHistoryView(APIView):
    """Lista histórico de transações de créditos."""

    permission_classes = [IsAuthenticated, RequiresMobileAccess]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["transaction_type", "status"]
    ordering_fields = ["created_at", "amount_eur"]

    @extend_schema(
        description="Lista histórico de transações de créditos de comunicação",
        responses={200: CommLedgerSerializer(many=True)},
    )
    def get(self, request):
        tenant = request.user.tenant
        credit_service = CreditService(tenant)

        queryset = credit_service.get_credit_history()

        # Date filtering
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)

        # Filter
        filter_backend = DjangoFilterBackend()
        queryset = filter_backend.filter_queryset(request, queryset, self)

        # Order
        ordering_filter = filters.OrderingFilter()
        queryset = ordering_filter.filter_queryset(request, queryset, self)

        # Paginate
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is not None:
            serializer = CommLedgerSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = CommLedgerSerializer(queryset, many=True)
        return Response(serializer.data)


class ConsumeCreditsView(APIView):
    """Consome créditos de comunicação."""

    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(
        description="Consome créditos de comunicação",
        request=ConsumeCreditsSerializer,
        responses={
            200: OpenApiResponse(description="Créditos consumidos com sucesso"),
            400: OpenApiResponse(description="Saldo insuficiente ou dados inválidos"),
        },
    )
    def post(self, request):
        serializer = ConsumeCreditsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = request.user.tenant
        credit_service = CreditService(tenant)

        amount = serializer.validated_data["amount"]
        description = serializer.validated_data.get("description", "Consumo de crédito")
        reference_id = serializer.validated_data.get("reference_id")

        try:
            transaction = credit_service.consume_credits(
                amount=amount,
                description=description,
                reference_id=reference_id,
                created_by=request.user,
            )
            return Response(
                {
                    "status": "success",
                    "transaction_id": transaction.id,
                    "new_balance": credit_service.get_credit_balance(),
                }
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PurchaseCreditsView(APIView):
    """Compra créditos de comunicação."""

    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(
        description="Compra créditos de comunicação",
        request=PurchaseCreditsSerializer,
        responses={
            200: OpenApiResponse(description="Créditos adicionados com sucesso"),
            400: OpenApiResponse(description="Dados inválidos"),
            403: OpenApiResponse(description="Compra de créditos não permitida"),
        },
    )
    def post(self, request):
        tenant = request.user.tenant

        if not tenant.can_purchase_extra_credits():
            return Response(
                {"detail": "Compra de créditos extras não permitida para este plano"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = PurchaseCreditsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        credit_service = CreditService(tenant)

        amount = serializer.validated_data["amount"]
        description = f"Compra de {amount}€ em créditos"
        reference_id = serializer.validated_data.get("reference_id")

        transaction = credit_service.add_credits(
            amount=amount,
            transaction_type="purchase",
            description=description,
            reference_id=reference_id,
            created_by=request.user,
        )

        return Response(
            {
                "status": "success",
                "transaction_id": transaction.id,
                "new_balance": credit_service.get_credit_balance(),
            }
        )


class RealtimeCreditsSSEView(APIView):
    """Stream de eventos de créditos via SSE (text/event-stream) por tenant.

    - Autenticação + entitlement mobile obrigatórios
    - Isolamento por tenant
    - Heartbeat periódico
    - Emite eventos quando há novas transações no ledger ou mudança de saldo
    """

    permission_classes = [IsAuthenticated, RequiresMobileAccess]

    @extend_schema(
        description=(
            "Stream SSE com atualizações de saldo/ledger por tenant. "
            "Content-Type: text/event-stream. Eventos: heartbeat, credit_update."
        ),
        responses={200: OpenApiResponse(description="text/event-stream")},
    )
    def get(self, request):
        user = request.user
        tenant = getattr(user, "tenant", None)
        if not tenant:
            raise AuthenticationFailed("tenant_required")

        # SSE acessível a qualquer usuário autenticado do tenant

        credit_service = CreditService(tenant)
        # Suporte a reconexão: lê Last-Event-ID do header
        last_ledger_id = None
        try:
            # DRF fornece request.headers; Django usa META com prefixo HTTP_
            hdr = (
                request.headers.get("Last-Event-ID")
                if hasattr(request, "headers")
                else None
            )
            if not hdr:
                hdr = request.META.get("HTTP_LAST_EVENT_ID")
            if hdr:
                last_ledger_id = int(hdr)
        except Exception:
            # Ignora header inválido e segue sem filtro inicial
            last_ledger_id = None

        def sse_event(event: str, data: dict | str, eid: str | None = None) -> str:
            payload = data if isinstance(data, str) else json.dumps(data)
            lines = []
            if eid:
                lines.append(f"id: {eid}")
            lines.append(f"event: {event}")
            lines.append(f"data: {payload}")
            return "\n".join(lines) + "\n\n"

        def event_stream():
            nonlocal last_ledger_id
            # Primeira emissão: estado inicial
            try:
                balance = credit_service.get_credit_balance()
                USERS_SSE_EVENTS_TOTAL.labels(
                    event="credit_update", result="emitted"
                ).inc()
                yield sse_event(
                    "credit_update",
                    {"balance": float(balance), "timestamp": int(time.time())},
                )
            except Exception:
                # Não interrompe o stream por erro inicial
                USERS_SSE_EVENTS_TOTAL.labels(event="error", result="emitted").inc()
                USERS_SSE_EVENTS_TOTAL.labels(event="heartbeat", result="emitted").inc()
                yield sse_event("heartbeat", "init")

            # Loop principal: heartbeat + detecção de novos eventos
            try:
                while True:
                    # Heartbeat a cada 15s
                    USERS_SSE_EVENTS_TOTAL.labels(
                        event="heartbeat", result="emitted"
                    ).inc()
                    yield sse_event("heartbeat", "ping")

                    # Detecta novas transações no ledger
                    try:
                        qs = CommLedger.objects.filter(tenant=tenant).order_by("id")
                        if last_ledger_id is not None:
                            qs = qs.filter(id__gt=last_ledger_id)
                        new_items = list(qs[:50])  # limita burst
                        if new_items:
                            last_ledger_id = new_items[-1].id
                            balance = credit_service.get_credit_balance()
                            for item in new_items:
                                USERS_SSE_EVENTS_TOTAL.labels(
                                    event="credit_update", result="emitted"
                                ).inc()
                                yield sse_event(
                                    "credit_update",
                                    {
                                        "balance": float(balance),
                                        "ledger": {
                                            "id": item.id,
                                            "type": item.transaction_type,
                                            "amount": float(item.amount_eur),
                                            "description": item.description,
                                            "created_at": int(
                                                item.created_at.timestamp()
                                            ),
                                        },
                                    },
                                    eid=str(item.id),
                                )
                                USERS_SSE_EVENTS_TOTAL.labels(
                                    event="credit_update", result="emitted"
                                ).inc()
                    except Exception:
                        # Em caso de erro transitório, mantém o stream vivo
                        USERS_SSE_EVENTS_TOTAL.labels(
                            event="error", result="emitted"
                        ).inc()
                        USERS_SSE_EVENTS_TOTAL.labels(
                            event="heartbeat", result="emitted"
                        ).inc()
                        yield sse_event("heartbeat", "error")

                    time.sleep(15)
            except GeneratorExit:
                USERS_SSE_EVENTS_TOTAL.labels(
                    event="disconnect", result="emitted"
                ).inc()
                raise

        response = StreamingHttpResponse(
            event_stream(), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class TenantNotificationsSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Atualiza toggles de canais de notificação (SMS, WhatsApp, Push Mobile). "
            "Push Mobile só pode ser ativado no plano Enterprise."
        ),
        request=TenantNotificationsUpdateSerializer,
        responses={200: OpenApiResponse(description="ok")},
    )
    def patch(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise AuthenticationFailed("tenant_required")

        if request.user.staff_role not in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        ):
            raise PermissionDenied("Permissão negada.")

        serializer = TenantNotificationsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        updates = set()
        if "sms_enabled" in v:
            tenant.sms_enabled = bool(v["sms_enabled"])
            updates.add("sms_enabled")
        if "whatsapp_enabled" in v:
            tenant.whatsapp_enabled = bool(v["whatsapp_enabled"])
            updates.add("whatsapp_enabled")
        if "push_mobile_enabled" in v:
            desired = bool(v["push_mobile_enabled"])
            if desired and tenant.plan_tier != Tenant.PLAN_PRO:
                return Response(
                    {
                        "detail": (
                            "Push Mobile só disponível para plano Pro. "
                            "Atualize seu plano para ativar."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            tenant.push_mobile_enabled = desired
            updates.add("push_mobile_enabled")

        if "push_web_enabled" in v:
            tenant.push_web_enabled = bool(v["push_web_enabled"])
            updates.add("push_web_enabled")

        if updates:
            tenant.save(update_fields=list(updates) + ["updated_at"])

        return Response(
            {
                "sms_enabled": tenant.sms_enabled,
                "whatsapp_enabled": tenant.whatsapp_enabled,
                "push_mobile_enabled": tenant.push_mobile_enabled,
                "push_web_enabled": tenant.push_web_enabled,
            },
            status=status.HTTP_200_OK,
        )
