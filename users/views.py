import logging

from django.core.cache import cache
from rest_framework import generics, status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.exceptions import ValidationError, AuthenticationFailed

from drf_spectacular.utils import extend_schema

from rest_framework.exceptions import NotFound

from salonix_backend.error_handling import TenantError, ErrorCodes
from .models import UserFeatureFlags, Tenant

from .serializers import (
    EmailTokenObtainPairSerializer,
    TenantMetaSerializer,
    TenantBrandingUpdateSerializer,
    UserRegistrationSerializer,
    UserFeatureFlagsSerializer,
    UserFeatureFlagsUpdateSerializer,
    TenantSelfServiceSerializer,
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
)
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle


bootstrap_logger = logging.getLogger("users.bootstrap")
security_logger = logging.getLogger("users.security")


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

    def post(self, request, *args, **kwargs):
        try:
            enforce_captcha_or_raise(request)
        except ValidationError:
            USERS_AUTH_EVENTS_TOTAL.labels(event="register", result="failure").inc()
            raise
        resp = super().post(request, *args, **kwargs)
        if resp.status_code in (status.HTTP_201_CREATED, status.HTTP_200_OK):
            USERS_AUTH_EVENTS_TOTAL.labels(event="register", result="success").inc()
        else:
            USERS_AUTH_EVENTS_TOTAL.labels(event="register", result="failure").inc()
        return resp

    def throttled(self, request, wait):  # pragma: no cover - DRF handles 429 response
        try:
            USERS_THROTTLED_TOTAL.labels(scope="auth_register").inc()
        finally:
            return super().throttled(request, wait)


class MeFeatureFlagsView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
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

    def post(self, request, *args, **kwargs):
        try:
            enforce_captcha_or_raise(request)
        except ValidationError:
            USERS_AUTH_EVENTS_TOTAL.labels(event="login", result="failure").inc()
            raise
        resp = super().post(request, *args, **kwargs)
        if resp.status_code in (status.HTTP_201_CREATED, status.HTTP_200_OK):
            USERS_AUTH_EVENTS_TOTAL.labels(event="login", result="success").inc()
        else:
            USERS_AUTH_EVENTS_TOTAL.labels(event="login", result="failure").inc()
        return resp

    def throttled(self, request, wait):  # pragma: no cover
        try:
            USERS_THROTTLED_TOTAL.labels(scope="auth_login").inc()
        finally:
            return super().throttled(request, wait)


class TenantMetaView(APIView):
    """
    GET /api/users/tenant/meta/
    PATCH /api/users/tenant/meta/

    Endpoint público para obter metadados do tenant (branding + feature flags).
    Aceita tenant via query parameter 'tenant' ou header 'X-Tenant-Slug'.

    PATCH requer autenticação e permite atualizar branding (logo, cores).
    """

    def get_permissions(self):
        """Permissões dinâmicas: público para GET, autenticado para PATCH"""
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

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
            raise TenantError(
                f"Tenant '{tenant_slug}' não encontrado ou inativo",
                code=ErrorCodes.BUSINESS_TENANT_NOT_FOUND,
            )

    @extend_schema(responses=TenantMetaSerializer)
    def get(self, request):
        """Retornar metadados do tenant especificado"""
        # TenantError será tratado automaticamente pelo custom_exception_handler
        tenant = self.get_tenant(request)

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
        """Atualizar branding do tenant (logo, cores)"""
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
        if serializer.is_valid():
            # Limpar logo anterior se novo logo for enviado
            from typing import Any, Dict, cast

            vdata = cast(Dict[str, Any], serializer.validated_data)
            if vdata.get("logo"):
                if tenant.logo:
                    tenant.logo.delete(save=False)  # Não salvar ainda
                # Limpar logo_url se logo for enviado
                vdata["logo_url"] = None

            serializer.save()

            # Retornar dados atualizados
            response_serializer = TenantMetaSerializer(tenant)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MeTenantView(APIView):
    permission_classes = [IsAuthenticated]
    CACHE_TTL = 30

    def get(self, request):
        user = request.user
        tenant = getattr(user, "tenant", None)
        if getattr(user, "is_ops_user", False) or not tenant:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

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


class UsersPasswordResetThrottle(ScopedRateThrottle):
    scope = "users_password_reset"


from drf_spectacular.utils import OpenApiExample, OpenApiResponse


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [UsersPasswordResetThrottle]
    throttle_scope = "users_password_reset"

    @extend_schema(
        description="Solicita um reset de senha. Resposta é neutra para não vazar existência.",
        examples=[
            OpenApiExample(
                "Exemplo",
                value={"email": "user@example.com", "reset_url": "https://app/reset"},
                request_only=True,
            )
        ],
        responses={200: OpenApiResponse(description="Always ok", response=None)},
    )
    def post(self, request):
        try:
            enforce_captcha_or_raise(request)
        except ValidationError:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(event="request", result="failure").inc()
            return Response({"detail": "captcha_invalid"}, status=status.HTTP_400_BAD_REQUEST)

        email = str(request.data.get("email", "")).strip().lower()
        if not email:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(event="request", result="failure").inc()
            return Response({"detail": "email_required"}, status=status.HTTP_400_BAD_REQUEST)

        User = get_user_model()
        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(event="request", result="success").inc()
            # resposta neutra para não vazar existência
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        token_gen = PasswordResetTokenGenerator()
        token = token_gen.make_token(user)
        uid = str(user.pk)

        reset_url = request.data.get("reset_url") or settings.STRIPE_CANCEL_URL  # placeholder front URL
        # Montar link: {reset_url}?uid={uid}&token={token}
        link = f"{reset_url}?uid={uid}&token={token}"

        try:
            from django.core.mail import EmailMultiAlternatives
            fail_silently = not (getattr(settings, "DEBUG", False) or getattr(settings, "ENV", "dev") == "dev")

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
            # Em dev, logar exceção para facilitar depuração SMTP
            if getattr(settings, "DEBUG", False) or getattr(settings, "ENV", "dev") == "dev":
                security_logger.exception(
                    "Falha ao enviar email de reset (dev)",
                    extra={
                        "event": "password_reset_email_error",
                        "email": email,
                        "error": str(exc),
                        "request_id": getattr(request, "request_id", None),
                    },
                )
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(event="request", result="success").inc()
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

        USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(event="request", result="success").inc()
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

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
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(event="confirm", result="failure").inc()
            return Response({"detail": "missing_fields"}, status=status.HTTP_400_BAD_REQUEST)

        User = get_user_model()
        try:
            user = User.objects.get(pk=uid, is_active=True)
        except User.DoesNotExist:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(event="confirm", result="failure").inc()
            raise AuthenticationFailed("invalid_token")

        token_gen = PasswordResetTokenGenerator()
        if not token_gen.check_token(user, token):
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(event="confirm", result="failure").inc()
            raise AuthenticationFailed("invalid_token")

        if len(str(new_password)) < 8:
            USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(event="confirm", result="failure").inc()
            return Response({"detail": "weak_password"}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save(update_fields=["password"])
        USERS_PASSWORD_RESET_EVENTS_TOTAL.labels(event="confirm", result="success").inc()
        return Response({"status": "password_updated"}, status=status.HTTP_200_OK)
