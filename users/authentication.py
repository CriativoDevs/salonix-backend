from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
from django.utils.translation import gettext_lazy as _

class JWTVersionAuthentication(JWTAuthentication):
    """
    Extensão do JWTAuthentication para validar a versão do token (jwt_version).
    Se o token tiver uma versão menor que a do usuário, ele é rejeitado.
    """
    def get_user(self, validated_token):
        # Primeiro, obtém o usuário usando a lógica padrão (valida user_id, is_active, etc)
        user = super().get_user(validated_token)
        
        # Agora valida a versão do token
        try:
            token_version = validated_token.get("jwt_version")
            
            # Se o usuário tem versão definida (padrão é 1)
            user_version = getattr(user, "jwt_version", 1)

            if token_version is not None:
                # Se token tem versão, deve ser >= versão do usuário
                if token_version < user_version:
                    raise AuthenticationFailed(
                        _("Sessão invalidada (versão do token antiga). Faça login novamente."),
                        code="token_version_mismatch"
                    )
            else:
                # Se token NÃO tem versão (legado/antigo) e usuário já está na v2+
                # Então o token é velho e deve ser descartado.
                if user_version > 1:
                    raise AuthenticationFailed(
                        _("Sessão invalidada (token sem versão). Faça login novamente."),
                        code="token_version_missing"
                    )
                    
        except KeyError:
            # Em tese não deve acontecer se o token foi validado, mas por segurança
            pass
            
        return user
