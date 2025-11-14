import logging

from django.core.cache import cache
from rest_framework import generics, status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.exceptions import ValidationError, AuthenticationFailed, PermissionDenied

from drf_spectacular.utils import extend_schema

from rest_framework.exceptions import NotFound
from django.http import StreamingHttpResponse
import json
import time

from salonix_backend.error_handling import TenantError, ErrorCodes
from .models import UserFeatureFlags, Tenant, TenantStaffMember, CommLedger
from .services import CreditService

from .serializers import (
    EmailTokenObtainPairSerializer,
    TenantMetaSerializer,
    TenantBrandingUpdateSerializer,
    UserRegistrationSerializer,
    UserFeatureFlagsSerializer,
    UserFeatureFlagsUpdateSerializer,
    TenantSelfServiceSerializer,
    UserSelfSerializer,
    TenantStaffMemberSerializer,
    StaffInviteSerializer,
    StaffAcceptInviteSerializer,
    StaffUpdateSerializer,
    CommLedgerSerializer,
    CreditBalanceSerializer,
    ConsumeCreditsSerializer,
    PurchaseCreditsSerializer,
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
        if not serializer.is_valid():
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

        response_serializer = TenantMetaSerializer(tenant)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


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


class MeProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        serializer = UserSelfSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        description="Atualiza preferência de tema do usuário",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "theme_preference": {
                        "type": "string",
                        "enum": ["light", "dark", "system"],
                        "description": "Preferência de tema do usuário"
                    }
                },
                "required": ["theme_preference"]
            }
        },
        responses={200: UserSelfSerializer}
    )
    def patch(self, request):
        user = request.user
        theme_preference = request.data.get('theme_preference')
        
        if not theme_preference:
            return Response(
                {"detail": "theme_preference é obrigatório"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validar se o valor é válido
        from .models import CustomUser
        valid_choices = [choice[0] for choice in CustomUser.ThemePreference.choices]
        if theme_preference not in valid_choices:
            return Response(
                {"detail": f"theme_preference deve ser um dos valores: {', '.join(valid_choices)}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user.theme_preference = theme_preference
        user.save(update_fields=['theme_preference'])
        
        serializer = UserSelfSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class TenantStaffView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        if request.user.staff_role not in (
            TenantStaffMember.Role.OWNER,
            TenantStaffMember.Role.MANAGER,
        ):
            raise PermissionDenied("Permissão negada.")

        staff_qs = TenantStaffMember.objects.filter(tenant=tenant).select_related("user")
        serializer = TenantStaffMemberSerializer(staff_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise NotFound("Tenant não encontrado para o usuário autenticado.")

        serializer = StaffInviteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        staff_member = serializer.save()
        response_data = TenantStaffMemberSerializer(staff_member).data
        response_data["invite_token"] = serializer.invite_token
        response_data["invite_token_expires_at"] = staff_member.invite_token_expires_at
        return Response(response_data, status=status.HTTP_201_CREATED)

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


class TenantStaffAcceptInviteView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = StaffAcceptInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        staff_member = serializer.save()
        response_data = TenantStaffMemberSerializer(staff_member).data
        return Response(response_data, status=status.HTTP_200_OK)


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


class CreditBalanceView(APIView):
    """Visualiza saldo e estatísticas de créditos de comunicação."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Obtém saldo atual e estatísticas de créditos de comunicação",
        responses={200: CreditBalanceSerializer}
    )
    def get(self, request):
        tenant = request.user.tenant
        credit_service = CreditService(tenant)
        
        balance = credit_service.get_credit_balance()
        stats = credit_service.get_credit_stats()
        
        data = {
            'current_balance': balance,
            'can_purchase_extra': tenant.can_purchase_extra_credits(),
            'has_auto_renewal': tenant.has_auto_credit_renewal(),
            **stats
        }
        
        serializer = CreditBalanceSerializer(data)
        return Response(serializer.data)


class CreditHistoryView(APIView):
    """Lista histórico de transações de créditos."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Lista histórico de transações de créditos de comunicação",
        responses={200: CommLedgerSerializer(many=True)}
    )
    def get(self, request):
        tenant = request.user.tenant
        credit_service = CreditService(tenant)
        
        history = credit_service.get_credit_history()
        serializer = CommLedgerSerializer(history, many=True)
        return Response(serializer.data)


class ConsumeCreditsView(APIView):
    """Consome créditos de comunicação."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Consome créditos de comunicação",
        request=ConsumeCreditsSerializer,
        responses={
            200: OpenApiResponse(description="Créditos consumidos com sucesso"),
            400: OpenApiResponse(description="Saldo insuficiente ou dados inválidos")
        }
    )
    def post(self, request):
        serializer = ConsumeCreditsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        tenant = request.user.tenant
        credit_service = CreditService(tenant)
        
        amount = serializer.validated_data['amount']
        description = serializer.validated_data.get('description', 'Consumo de crédito')
        reference_id = serializer.validated_data.get('reference_id')
        
        try:
            transaction = credit_service.consume_credits(
                amount=amount,
                description=description,
                reference_id=reference_id,
                created_by=request.user
            )
            return Response({
                'status': 'success',
                'transaction_id': transaction.id,
                'new_balance': credit_service.get_credit_balance()
            })
        except ValueError as e:
            return Response(
                {'detail': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )


class PurchaseCreditsView(APIView):
    """Compra créditos de comunicação."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Compra créditos de comunicação",
        request=PurchaseCreditsSerializer,
        responses={
            200: OpenApiResponse(description="Créditos adicionados com sucesso"),
            400: OpenApiResponse(description="Dados inválidos"),
            403: OpenApiResponse(description="Compra de créditos não permitida")
        }
    )
    def post(self, request):
        tenant = request.user.tenant
        
        if not tenant.can_purchase_extra_credits():
            return Response(
                {'detail': 'Compra de créditos extras não permitida para este plano'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = PurchaseCreditsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        credit_service = CreditService(tenant)
        
        amount = serializer.validated_data['amount']
        description = f"Compra de {amount}€ em créditos"
        reference_id = serializer.validated_data.get('reference_id')
        
        transaction = credit_service.add_credits(
            amount=amount,
            transaction_type='purchase',
            description=description,
            reference_id=reference_id,
            created_by=request.user
        )
        
        return Response({
            'status': 'success',
            'transaction_id': transaction.id,
            'new_balance': credit_service.get_credit_balance()
        })


class RealtimeCreditsSSEView(APIView):
    """Stream de eventos de créditos via SSE (text/event-stream) por tenant.

    - Autenticação obrigatória
    - Isolamento por tenant
    - Heartbeat periódico
    - Emite eventos quando há novas transações no ledger ou mudança de saldo
    """
    permission_classes = [IsAuthenticated]

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

        credit_service = CreditService(tenant)
        # Suporte a reconexão: lê Last-Event-ID do header
        last_ledger_id = None
        try:
            # DRF fornece request.headers; Django usa META com prefixo HTTP_
            hdr = request.headers.get("Last-Event-ID") if hasattr(request, "headers") else None
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
                USERS_SSE_EVENTS_TOTAL.labels(event="credit_update", result="emitted").inc()
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
                    USERS_SSE_EVENTS_TOTAL.labels(event="heartbeat", result="emitted").inc()
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
                                USERS_SSE_EVENTS_TOTAL.labels(event="credit_update", result="emitted").inc()
                                yield sse_event(
                                    "credit_update",
                                    {
                                        "balance": float(balance),
                                        "ledger": {
                                            "id": item.id,
                                            "type": item.transaction_type,
                                            "amount": float(item.amount_eur),
                                            "description": item.description,
                                            "created_at": int(item.created_at.timestamp()),
                                        },
                                    },
                                    eid=str(item.id),
                                )
                                USERS_SSE_EVENTS_TOTAL.labels(event="credit_update", result="emitted").inc()
                    except Exception:
                        # Em caso de erro transitório, mantém o stream vivo
                        USERS_SSE_EVENTS_TOTAL.labels(event="error", result="emitted").inc()
                        USERS_SSE_EVENTS_TOTAL.labels(event="heartbeat", result="emitted").inc()
                        yield sse_event("heartbeat", "error")

                    time.sleep(15)
            except GeneratorExit:
                USERS_SSE_EVENTS_TOTAL.labels(event="disconnect", result="emitted").inc()
                raise

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
