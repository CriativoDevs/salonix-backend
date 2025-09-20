from __future__ import annotations

import logging
from typing import Any, Dict

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.settings import api_settings

User = get_user_model()
logger = logging.getLogger(__name__)


def _base_ops_token_claims(refresh: RefreshToken, ops_role: str, user_id: int) -> Dict[str, Any]:
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
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        email = attrs.get("email")
        password = attrs.get("password")

        if not email or not password:
            raise AuthenticationFailed("Credenciais inválidas.")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise AuthenticationFailed("Credenciais inválidas.")

        if not user.check_password(password):
            raise AuthenticationFailed("Credenciais inválidas.")

        if not user.is_active:
            raise AuthenticationFailed(
                "Conta inativa. Entre em contato com o suporte."
            )

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
            user_id_int = int(user_id_raw)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise AuthenticationFailed("Token inválido: utilizador ausente.") from exc

        tokens = _base_ops_token_claims(refresh, scope, user_id_int)

        data: Dict[str, Any] = {
            "access": str(tokens["access"]),
            "ops_role": scope,
            "user_id": str(user_id_int),
        }

        if api_settings.ROTATE_REFRESH_TOKENS:
            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            if api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    refresh.blacklist()
                except AttributeError:
                    pass
            data["refresh"] = str(refresh)

        return data
