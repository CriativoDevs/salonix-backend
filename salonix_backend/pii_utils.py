"""
Utilitários para mascaramento de Informações Pessoalmente Identificáveis (PII).
Implementa padrões de mascaramento conforme requisitos LGPD/GDPR.
"""

import re
from typing import Any, Dict, Optional


def mask_email(email: Optional[str]) -> Optional[str]:
    """
    Mascara endereço de email para proteção de privacidade.

    Exemplos:
        - "john.doe@example.com" → "j***@example.com"
        - "a@test.com" → "a***@test.com"
        - None → None

    Args:
        email: Endereço de email a ser mascarado

    Returns:
        Email mascarado ou None se entrada for None
    """
    if not email:
        return None

    email = email.strip()
    if "@" not in email:
        return email

    local, domain = email.split("@", 1)

    # Mostrar apenas primeiro caractere + *** + domínio
    if len(local) >= 1:
        masked_local = local[0] + "***"
    else:
        masked_local = "***"

    return f"{masked_local}@{domain}"


def mask_phone(phone: Optional[str]) -> Optional[str]:
    """
    Mascara número de telefone para proteção de privacidade.

    Exemplos:
        - "+5511987654321" → "+55 119****4321"
        - "11987654321" → "119****4321"
        - "(11) 98765-4321" → "(11) 98***-4321"
        - None → None

    Args:
        phone: Número de telefone a ser mascarado

    Returns:
        Telefone mascarado ou None se entrada for None
    """
    if not phone:
        return None

    phone = phone.strip()

    # Remover caracteres não numéricos temporariamente para análise
    digits_only = re.sub(r"\D", "", phone)

    if len(digits_only) < 4:
        return "****"

    # Mostrar apenas últimos 4 dígitos
    masked_digits = "*" * (len(digits_only) - 4) + digits_only[-4:]

    # Tentar reconstruir formato original
    if phone.startswith("+"):
        # Formato internacional: +55 11 98765-4321
        if len(digits_only) > 10:
            country_code = digits_only[:2]  # 55
            area_code = digits_only[2:4]  # 11
            last_four = digits_only[-4:]
            return f"+{country_code} {area_code}****{last_four}"
        return f"+{masked_digits}"
    elif "(" in phone:
        # Formato (11) 98765-4321
        match = re.match(r"\((\d+)\)\s+(\d+)(.*)", phone)
        if match:
            area = match.group(1)
            first_digits = match.group(2)
            rest = match.group(3)
            return f"({area}) {first_digits[0]}***{rest}"
        return masked_digits

    return masked_digits


def mask_cpf(cpf: Optional[str]) -> Optional[str]:
    """
    Mascara CPF para proteção de privacidade.

    Exemplos:
        - "12345678901" → "***.***.***-01"
        - "123.456.789-01" → "***.***.***-01"
        - None → None

    Args:
        cpf: CPF a ser mascarado

    Returns:
        CPF mascarado ou None se entrada for None
    """
    if not cpf:
        return None

    cpf = cpf.strip()

    # Remover formatação
    cpf_digits = re.sub(r"\D", "", cpf)

    if len(cpf_digits) < 4:
        return "***"

    # Mostrar apenas últimos 2 dígitos
    last_two = cpf_digits[-2:]

    # Retornar no formato xxx.xxx.xxx-XX
    return f"***.***.**-{last_two}"


def mask_identifier(identifier: Optional[str], length: int = 10) -> Optional[str]:
    """
    Mascara identificador genérico (ID, passport, etc.).
    Mostra apenas últimos caracteres.

    Exemplos:
        - "ABC123456789" → "****6789"
        - "12345" → "****5"
        - None → None

    Args:
        identifier: Identificador a ser mascarado
        length: Número máximo de caracteres a mostrar no final

    Returns:
        Identificador mascarado ou None se entrada for None
    """
    if not identifier:
        return None

    identifier = str(identifier).strip()

    if len(identifier) <= length:
        return "****"

    show_chars = min(length // 2, len(identifier) // 2)
    masked = "*" * (len(identifier) - show_chars) + identifier[-show_chars:]

    return masked


def mask_pii_dict(
    data: Dict[str, Any], sensitive_fields: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Mascara campos PII em um dicionário.

    Args:
        data: Dicionário com dados que podem conter PII
        sensitive_fields: Mapa {field_name: field_type} onde field_type é:
                         "email", "phone", "cpf", "identifier", ou callable
                         Se None, usa padrão automático baseado em nomes

    Returns:
        Cópia do dicionário com campos sensíveis mascarados

    Exemplo:
        >>> data = {"email": "john@example.com", "phone": "+551198765432"}
        >>> mask_pii_dict(data, {"email": "email", "phone": "phone"})
        {"email": "j***@example.com", "phone": "+55 11****5432"}
    """
    if not data:
        return data

    # Padrão automático: detecta campos sensíveis por nome
    auto_sensitive = {
        "email": "email",
        "phone": "phone",
        "phone_number": "phone",
        "cpf": "cpf",
        "cpf_number": "cpf",
        "telephone": "phone",
        "user_email": "email",
        "owner_email": "email",
        "new_owner_email": "email",
    }

    fields_to_mask = sensitive_fields or auto_sensitive
    result = data.copy()

    for field_name, field_type in fields_to_mask.items():
        if field_name not in result:
            continue

        value = result[field_name]

        if callable(field_type):
            # Campo com função de mascaramento customizada
            result[field_name] = field_type(value)
        elif field_type == "email":
            result[field_name] = mask_email(value)
        elif field_type == "phone":
            result[field_name] = mask_phone(value)
        elif field_type == "cpf":
            result[field_name] = mask_cpf(value)
        elif field_type == "identifier":
            result[field_name] = mask_identifier(value)

    return result


def mask_user_repr(
    user_obj: Any, include_fields: Optional[list] = None
) -> Dict[str, Any]:
    """
    Gera representação mascarada de um usuário para logs.

    Args:
        user_obj: Objeto User (Django)
        include_fields: Campos a incluir na representação (padrão: id, username, email_masked)

    Returns:
        Dicionário com representação segura do usuário

    Exemplo:
        >>> user = User.objects.get(id=1)
        >>> mask_user_repr(user)
        {"user_id": 1, "username": "john_doe", "email": "j***@example.com"}
    """
    if not user_obj:
        return {}

    result = {
        "user_id": getattr(user_obj, "id", None),
        "username": getattr(user_obj, "username", None),
    }

    # Adicionar email mascarado se disponível
    if hasattr(user_obj, "email"):
        result["email"] = mask_email(user_obj.email)

    # Adicionar telefone mascarado se disponível
    if hasattr(user_obj, "phone_number"):
        result["phone"] = mask_phone(user_obj.phone_number)

    # Adicionar campos customizados se solicitado
    if include_fields:
        for field in include_fields:
            if hasattr(user_obj, field):
                value = getattr(user_obj, field)
                # Tentar mascarar se for email/telefone
                if field in ("email", "user_email", "owner_email"):
                    result[f"{field}_masked"] = mask_email(value)
                elif field in ("phone", "phone_number", "telephone"):
                    result[f"{field}_masked"] = mask_phone(value)
                else:
                    result[field] = value

    return result


# Lista de campos que NUNCA devem ser logados
FIELDS_NEVER_LOG = {
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "api_secret",
    "private_key",
    "auth_token",
    "session_id",
    "stripe_api_key",
    "stripe_secret",
    "cookie",
    "auth_cookie",
}


def is_sensitive_field(field_name: str) -> bool:
    """
    Verifica se um campo é sensível e não deve ser logado.

    Args:
        field_name: Nome do campo

    Returns:
        True se o campo é sensível, False caso contrário
    """
    field_lower = field_name.lower()
    return any(forbidden in field_lower for forbidden in FIELDS_NEVER_LOG)


def sanitize_log_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove ou mascara dados sensíveis de um objeto antes de logar.

    Args:
        data: Dicionário com dados a sanitizar

    Returns:
        Cópia do dicionário com dados sensíveis removidos ou mascarados
    """
    result = {}

    for key, value in data.items():
        # Campos que nunca devem ser logados são removidos
        if is_sensitive_field(key):
            result[key] = "[REDACTED]"
            continue

        # Tentar mascarar campos PII conhecidos
        if isinstance(value, str):
            if "email" in key.lower():
                result[key] = mask_email(value)
            elif "phone" in key.lower() or "telephone" in key.lower():
                result[key] = mask_phone(value)
            elif "cpf" in key.lower():
                result[key] = mask_cpf(value)
            else:
                result[key] = value
        else:
            result[key] = value

    return result
