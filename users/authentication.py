from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from django.utils.translation import gettext_lazy as _


def is_staff_disabled(user) -> bool:
    """True se o usuario tem vinculo de equipe DESATIVADO.

    Politica BE-SEC-01: desativar o membro (mark_disabled) corta o acesso na
    autenticacao, no login e no refresh. Usuarios sem TenantStaffMember
    (legado/superuser) nao sao afetados aqui; a permissao de cada rota decide.
    """
    from users.models import TenantStaffMember

    return TenantStaffMember.objects.filter(
        user=user, status=TenantStaffMember.Status.DISABLED
    ).exists()


class JWTVersionAuthentication(JWTAuthentication):
    """
    Extensão do JWTAuthentication para validar a versão do token (jwt_version).
    Se o token tiver uma versão menor que a do usuário, ele é rejeitado.

    BE-SEC-01: recusa tokens scope=client (user_id == customer.id, que
    resolveria para o CustomUser de mesmo PK de qualquer tenant) e membros de
    equipe desativados. As rotas clients/me/* usam authentication_classes = []
    e leem o token manualmente (_get_client_from_jwt), logo nao passam por aqui.
    """

    def get_user(self, validated_token):
        if validated_token.get("scope") == "client":
            raise AuthenticationFailed(
                _("Token de cliente não é válido para esta rota."),
                code="client_token_not_allowed",
            )

        # Primeiro, obtém o usuário usando a lógica padrão (valida user_id, is_active, etc)
        user = super().get_user(validated_token)

        if is_staff_disabled(user):
            raise AuthenticationFailed(
                _("Acesso desativado. Contacte o responsável pelo estabelecimento."),
                code="staff_disabled",
            )

        # Agora valida a versão do token
        try:
            token_version = validated_token.get("jwt_version")

            # Se o usuário tem versão definida (padrão é 1)
            user_version = getattr(user, "jwt_version", 1)

            if token_version is not None:
                # Se token tem versão, deve ser >= versão do usuário
                if token_version < user_version:
                    raise AuthenticationFailed(
                        _(
                            "Sessão invalidada (versão do token antiga). Faça login novamente."
                        ),
                        code="token_version_mismatch",
                    )
            else:
                # Se token NÃO tem versão (legado/antigo) e usuário já está na v2+
                # Então o token é velho e deve ser descartado.
                if user_version > 1:
                    raise AuthenticationFailed(
                        _(
                            "Sessão invalidada (token sem versão). Faça login novamente."
                        ),
                        code="token_version_missing",
                    )

        except KeyError:
            # Em tese não deve acontecer se o token foi validado, mas por segurança
            pass

        return user
