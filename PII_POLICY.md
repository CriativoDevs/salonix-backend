# PII (Personally Identifiable Information) Protection Policy

## Objetivo

Proteger dados pessoais em logs e auditoria conforme requisitos LGPD/GDPR através de mascaramento centralizado.

## Padrões de mascaramento

### Email
- **Padrão**: `u***@example.com` (primeiro caractere + *** + domínio)
- **Função**: `mask_email(email: str) -> str`
- **Exemplos**:
  - `"john.doe@example.com"` → `"j***@example.com"`
  - `"a@test.com"` → `"a***@test.com"`

### Telefone
- **Padrão**: Mostra apenas últimos 4 dígitos, mascara o resto
- **Função**: `mask_phone(phone: str) -> str`
- **Exemplos**:
  - `"+5511987654321"` → `"+55 11****4321"`
  - `"(11) 98765-4321"` → `"(11) 98***-4321"`
  - `"11987654321"` → `"11987****4321"`

### CPF
- **Padrão**: `***.***.**-XX` (mostra apenas últimos 2 dígitos)
- **Função**: `mask_cpf(cpf: str) -> str`
- **Exemplos**:
  - `"123.456.789-01"` → `"***.***.**-01"`
  - `"12345678901"` → `"***.***.**-01"`

### Identificadores genéricos
- **Padrão**: Mostra apenas últimos ~50% dos caracteres
- **Função**: `mask_identifier(identifier: str, length: int = 10) -> str`
- **Exemplos**:
  - `"ABC123456789"` → `"****6789"`

## Campos que NUNCA devem ser logados

Os seguintes campos devem ser completamente removidos ou marcados como `[REDACTED]`:

```
password
secret
token
access_token
refresh_token
api_key
api_secret
private_key
auth_token
session_id
stripe_api_key
stripe_secret
cookie
auth_cookie
```

**Função de validação**: `is_sensitive_field(field_name: str) -> bool`

## Como usar a biblioteca

### 1. Mascarar campos individuais

```python
from salonix_backend.pii_utils import mask_email, mask_phone, mask_cpf

# Email
masked_email = mask_email("john@example.com")  # "j***@example.com"

# Telefone
masked_phone = mask_phone("+5511987654321")    # "+55 11****4321"

# CPF
masked_cpf = mask_cpf("123.456.789-01")       # "***.***.**-01"
```

### 2. Mascarar dicionários completos

```python
from salonix_backend.pii_utils import mask_pii_dict

# Auto-detecção de campos sensíveis
data = {
    "email": "john@example.com",
    "phone": "11987654321",
    "name": "John Doe",
    "status": "active"
}

masked = mask_pii_dict(data)
# Resultado: email mascarado, phone mascarado, name e status preservados

# Com campos customizados
custom_fields = {
    "email": "email",
    "mobile": "phone",
    "id_number": "cpf"
}
masked = mask_pii_dict(data, custom_fields)
```

### 3. Representação segura de usuário em logs

```python
from salonix_backend.pii_utils import mask_user_repr

user = User.objects.get(id=123)
safe_repr = mask_user_repr(user)
# Resultado: {"user_id": 123, "username": "john_doe", "email": "j***@example.com"}

logger.info(f"Ação do usuário", extra={"user": safe_repr})
```

### 4. Sanitizar dados antes de logar

```python
from salonix_backend.pii_utils import sanitize_log_data

payload = {
    "email": "john@example.com",
    "password": "secret123",
    "name": "John",
    "api_key": "sk_live_xxx"
}

safe_payload = sanitize_log_data(payload)
# Resultado: email mascarado, password = [REDACTED], api_key = [REDACTED], name preservado

logger.error(f"Erro na operação", extra=safe_payload)
```

## Pontos de aplicação

### 1. OpsSupportAuditLog

**Antes (INSEGURO)**:
```python
OpsSupportAuditLog.objects.create(
    actor=request.user,
    action=OpsSupportAuditLog.Actions.UPDATE_PLAN,
    target_tenant=tenant,
    payload={"new_owner_email": email},  # ⚠️ PII EXPOSTO
)
```

**Depois (SEGURO)**:
```python
from salonix_backend.pii_utils import mask_email

OpsSupportAuditLog.objects.create(
    actor=request.user,
    action=OpsSupportAuditLog.Actions.UPDATE_PLAN,
    target_tenant=tenant,
    payload={"new_owner_email": mask_email(email)},  # ✅ PII MASCARADO
)
```

### 2. Logging de autenticação

**Antes (INSEGURO)**:
```python
logger.info(f"Email de cancelamento enviado para {request.user.email}")
```

**Depois (SEGURO)**:
```python
from salonix_backend.pii_utils import mask_email

logger.info(
    "Email de cancelamento enviado",
    extra={"user_email": mask_email(request.user.email)}
)
```

### 3. Logging de erros com contexto

**Antes (INSEGURO)**:
```python
logger.error(f"Erro ao processar cliente {client.email}: {e}")
```

**Depois (SEGURO)**:
```python
from salonix_backend.pii_utils import mask_email, sanitize_log_data

logger.error(
    "Erro ao processar cliente",
    extra={
        "client_email": mask_email(client.email),
        "error": str(e)
    }
)
```

## Testing

Todos os padrões de mascaramento estão cobertos por testes em `tests/test_pii_utils.py`:

```bash
# Rodar testes de PII
pytest tests/test_pii_utils.py -v

# Testes específicos
pytest tests/test_pii_utils.py::TestMaskEmail -v
pytest tests/test_pii_utils.py::TestSanitizeLogData -v
```

## Checklist para novos endpoints

Antes de mergear novos endpoints que lidam com dados pessoais:

- [ ] Nenhum PII é logado sem mascaramento
- [ ] Senhas/tokens/api_keys nunca aparecem em logs
- [ ] Audit payloads usam campos mascarados
- [ ] Mensagens de erro não expõem dados pessoais
- [ ] Testes validam que logs não contêm PII em texto puro

## Compliance

- **LGPD**: Protege dados pessoais de cidadãos brasileiros
- **GDPR**: Protege dados pessoais de cidadãos europeus
- **Retention**: Logs de auditoria mantêm apenas dados mascarados indefinidamente
