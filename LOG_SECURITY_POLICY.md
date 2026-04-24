# Política de Segurança em Logging - BE-SEC-03

Documento de conformidade LGPD/GDPR para tratamento de dados pessoais em logs da aplicação Salonix.

---

## 1. Campos que NUNCA Devem Ser Logados

Estes campos contêm informações sensíveis que violam conformidade e devem ser redatados com `[REDACTED]`:

### Autenticação & Autorização
- `password`
- `token`
- `access_token`
- `refresh_token`
- `auth_token`
- `session_id`
- `cookie`
- `auth_cookie`

### APIs & Integrações
- `api_key`
- `api_secret`
- `private_key`
- `secret`
- `stripe_api_key`
- `stripe_secret`

**Implementação:** Função `is_sensitive_field()` em `salonix_backend/pii_utils.py` + `FIELDS_NEVER_LOG` set.

---

## 2. Padrões de Mascaramento de PII

### Email
**Padrão:** `primeiro_char***@dominio.com`

Exemplos:
- `john.doe@example.com` → `j***@example.com`
- `a@test.com` → `a***@test.com`

**Função:** `mask_email(email)` em `salonix_backend/pii_utils.py`

### Telefone
**Padrão:** Preservar país/DDD + mascarar resto

Exemplos:
- `+5511987654321` → `+55 119****4321` (país + DDD visível)
- `11987654321` → `119****4321`

**Função:** `mask_phone(phone)` em `salonix_backend/pii_utils.py`

### CPF
**Padrão:** `***.***.***-XX` (últimos 2 dígitos visíveis)

Exemplos:
- `123.456.789-01` → `***.***.**-01`

**Função:** `mask_cpf(cpf)` em `salonix_backend/pii_utils.py`

### Identificadores (ID, UUID)
**Padrão:** Mostrar ~50% dos últimos caracteres

**Função:** `mask_identifier(identifier)` em `salonix_backend/pii_utils.py`

---

## 3. Pontos de Logging Mascarados

### users/views.py (Autenticação)
| Ponto | Implementação |
|-------|---------------|
| Login - sucesso | `extra={"email": mask_email(...)}` |
| Login - erro | `extra={"email": mask_email(...)}` |
| Registro - sucesso | `extra={"email": mask_email(...)}` |
| Registro - erro | `extra={"email": mask_email(...)}` |

### ops/views.py (Admin)
| Ponto | Implementação |
|-------|---------------|
| Login OPS - falha auth | `extra={"email": mask_email(...)}` |
| Login OPS - erro validação | `extra={"email": mask_email(...)}` |
| Reset owner | `payload={"new_owner_email": mask_email(...)}` |

### core/views.py (Aplicação)
| Ponto | Implementação |
|-------|---------------|
| Cancelamento de conta | `extra={"user_email": mask_email(...)}` |
| Reativação de conta | `extra={"user_email": mask_email(...)}` |
| Feedback validação error | `data=sanitize_log_data(request.data)` |

### OpsSupportAuditLog (Audit Trail)
- Payloads sanitizados com `sanitize_log_data(payload)` antes de persistência
- Status: 1/20 pontos implementados (reset_owner)

---

## 4. Política de Retenção de Logs

### Logs de Segurança (security_logger)
- **Retenção:** 90 dias (conforme LGPD Art. 9)
- **Conteúdo:** Login, logout, mudança de senha, erros de autenticação
- **Acesso:** Owner + OPS Admin apenas
- **Limpeza:** Job automático (não implementado yet)

### Audit Logs (OpsSupportAuditLog)
- **Retenção:** 180 dias (para accountability administrativo)
- **Conteúdo:** Mudanças de plano, reset de senha, operações sensíveis
- **Acesso:** OPS Admin apenas
- **Limpeza:** Job automático (não implementado yet)

### Logs de Erro/Aplicação (logger)
- **Retenção:** 30 dias (logs transientes)
- **Conteúdo:** Stack traces, validações, operações de negócio
- **Acesso:** Engineering team + OPS Admin
- **Limpeza:** Job automático (não implementado yet)

### Logs de Billing/Pagamento
- **Retenção:** 365 dias (requisito fiscal)
- **Conteúdo:** Transações Stripe mascaradas, webhooks
- **Acesso:** Finance + OPS Admin
- **Limpeza:** Manual após audit

---

## 5. Função de Sanitização

### sanitize_log_data(data: Dict) → Dict

Sanitiza um dicionário de dados para logging seguro:

```python
from salonix_backend.pii_utils import sanitize_log_data

# Antes:
request_data = {
    "email": "user@example.com",
    "password": "SecretPass123!",
    "api_key": "sk_live_123abc",
}

# Depois:
safe_data = sanitize_log_data(request_data)
# Resultado:
# {
#     "email": "u***@example.com",  # Masked
#     "password": "[REDACTED]",      # Redacted
#     "api_key": "[REDACTED]",       # Redacted
# }

logger.info("User action", extra=safe_data)
```

---

## 6. Conformidade LGPD

### Artigos Aplicáveis
- **Art. 5:** Princípios - transparência, necessidade, finalidade
- **Art. 9:** Retenção mínima possível
- **Art. 11:** Acesso restrito a dados (need-to-know)

### Implementação Atual
✅ Mascaramento de PII em logs públicos
✅ Redação de secrets
✅ Função centralizada de sanitização
⏳ Retenção automática (Job não implementado)
⏳ Acesso restrito por role (em review)

---

## 7. Roteiro de Implementação Pendente

### Q1 2025
- [ ] Implementar cleanup jobs automáticos (Celery task)
- [ ] Completar mascaramento de OpsSupportAuditLog (20 audit logs restantes)
- [ ] Implementar acesso restrito a logs por role (ACL)

### Q2 2025
- [ ] Validação de conformidade em staging
- [ ] Audit de logs históricos (grep scan para PII residual)
- [ ] Documentação para Data Protection Officer (DPO)

---

## 8. Contato & Escalação

- **Responsável:** Backend Lead (Pablo)
- **Equipe de Compliance:** DPO (Data Protection Officer)
- **Revisão:** Semestral ou quando houver mudanças em retenção/acesso

---

**Última atualização:** 24 de abril de 2025
**Status:** Em implementação (Item 3 & 4 de 6)
**Próxima revisão:** Junho 2025
