from django.conf import settings
from django.core import signing
from django.utils import timezone
import uuid

def generate_client_access_payload(tenant, customer):
    """
    Gera o payload padrão para o token de acesso do cliente.
    """
    return {
        "tenant_id": getattr(tenant, "id", None),
        "customer_id": getattr(customer, "id", None),
        "ts": int(timezone.now().timestamp()),
        "jti": uuid.uuid4().hex,
    }

def generate_client_access_token(payload):
    """
    Assina o payload gerando o token seguro.
    """
    return signing.dumps(payload, salt="CLIENT_PWA_INVITE_SALT")

def generate_client_access_link(tenant, token):
    """
    Gera a URL completa de acesso do cliente.
    """
    base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
    slug = getattr(tenant, "slug", "").strip().lower()
    tenant_qs = f"tenant={slug}" if slug else ""
    sep = "&" if tenant_qs else ""
    return f"{base}/client/access?{tenant_qs}{sep}token={token}"

def create_client_access_data(tenant, customer):
    """
    Helper que gera tudo de uma vez: payload, token e link.
    Retorna uma tupla (payload, token, link).
    """
    payload = generate_client_access_payload(tenant, customer)
    token = generate_client_access_token(payload)
    link = generate_client_access_link(tenant, token)
    return payload, token, link
