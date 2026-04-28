# Security Endpoint Checklist — BE-SEC-04

**Last Updated:** 2026-04-28

---

## Purpose

Guia rápido para garantir que novos endpoints REST implementados na plataforma seguem baseline OWASP API Top 10 / ASVS. Use este checklist **antes de submeter PR** no backend.

**Tempo esperado:** ~10 minutos por endpoint.

---

## Checklist Completo

### 1. Autorização & Acesso por Objeto/Tenant

- [ ] **Permissão declarada**: Endpoint tem `permission_classes` explícito (ex: `[IsAuthenticated]`, `[IsOwner]`)?
  - ❌ **Evitar**: `permission_classes = []` (implicitamente `AllowAny` em DRF 3.14+) — seja explícito
  - ✅ **Bom**: `permission_classes = [IsAuthenticated, IsOwner]`

- [ ] **Validação de tenant**: Se endpoint acessa dados de tenant (staff, profiles, config, billing):
  - [ ] ViewSet/APIView filtra queryset por `tenant` do usuário autenticado?
  - [ ] Ou: ViewSet/APIView valida no serializer ou `perform_*()` que objeto pertence ao tenant do usuário?
  - ❌ **Evitar**: `queryset = StaffMember.objects.all()` sem filtro
  - ✅ **Bom**: `queryset = StaffMember.objects.filter(tenant=self.request.user.tenant)` ou validação em `perform_update()`

- [ ] **Validação de role/status** (se aplicável):
  - [ ] Endpoint que muda billing (checkout, portal, credit purchase)? → Aplicar `_require_active_billing_owner(user)` ou equivalente
  - [ ] Endpoint que muda staff (invite, role elevation, status)? → Validar OWNER/MANAGER role no serializer
  - [ ] Endpoint OPS (block tenant, reset owner, update plan)? → Aplicar `permission_classes = [IsOpsAdmin]`
  - [ ] Endpoint de importação/exportação? → Aplicar `permission_classes = [IsAuthenticated]` + validação de tenant + throttle

- [ ] **Cross-tenant attack prevention**:
  - [ ] Se POST/PATCH/DELETE, valida que recurso sendo alterado pertence ao tenant do usuário?
  - ❌ **Evitar**: Permitir `user_id` ou `tenant_id` como parâmetro de entrada sem validação
  - ✅ **Bom**: Extrair tenant do `request.user.staff_member.tenant` (server-side source of truth)

---

### 2. Throttling & Rate-Limiting

- [ ] **Risco de abuso avaliado**:
  - [ ] É endpoint de auth / account recovery? → Throttle hard (ex: `5/hour`)
  - [ ] É endpoint de payment? → Throttle hard (ex: `5-10/hour`)
  - [ ] É endpoint de OPS? → Throttle medium (ex: `60/min`)
  - [ ] É endpoint de import/export ou background job submission? → Throttle medium (ex: `10/hour`)
  - [ ] É endpoint de public leitura (sem auth)? → Throttle soft (ex: `100/hour`)
  - [ ] É endpoint de leitura autenticado (baixa sensibilidade)? → Sem throttle (ou default)

- [ ] **Throttle declarado**:
  - [ ] `throttle_classes = [YourThrottle]` está no ViewSet ou APIView?
  - [ ] Ou: `get_throttles()` override aplica throttle seletivamente (ex: apenas mutations)?
  - ✅ **Bom**: `throttle_classes = [PaymentsCheckoutThrottle]` ou `get_throttles()` em class

- [ ] **Rate configurado em `settings.py`**:
  - [ ] `DEFAULT_THROTTLE_RATES['your_scope']` definido com rate sensível?
  - [ ] Relaxado em `ENV='dev'` ou `'test'` para não quebrar desenvolvimento?
  - ✅ **Bom**: `PAYMENTS_CHECKOUT_RATE = os.getenv('PAYMENTS_CHECKOUT_RATE', '5/hour' if ENV in ['staging', 'uat', 'prod'] else '100/hour')`

---

### 3. Error Handling & Response Contracts

- [ ] **Erros de permissão retornam HTTP 403 Forbidden** (não 404):
  - ❌ **Evitar**: Retornar `404 Not Found` para dados privados (information disclosure)
  - ✅ **Bom**: Retornar `403 Forbidden` com mensagem genérica

- [ ] **Mensagens de erro não revelam PII ou lógica interna**:
  - ❌ **Evitar**: `"User with email john@example.com not found"`
  - ✅ **Bom**: `"Recurso não encontrado ou você não tem permissão de acesso"`

- [ ] **Erros seguem contrato padrão**:
  - [ ] Erro middleware wraps exceptions em `{"error": {"code": "E###", "message": "...", "details": {}, "error_id": "..."}}`?
  - [ ] Ou: Se custom response, inclui `error_id` ou `code` para rastreamento?

- [ ] **Stack traces não vazam em resposta**:
  - ❌ **Evitar**: Retornar `traceback` em JSON em prod
  - ✅ **Bom**: Log em servidor; resposta contém apenas `error_id` genérico

---

### 4. Input Validation & Serializers

- [ ] **Serializer valida tipos de entrada**:
  - [ ] Fields têm tipos explícitos (`IntegerField`, `EmailField`, `DateTimeField`, etc)?
  - [ ] Campos obrigatórios têm `required=True`?
  - [ ] Campos opcionais têm `required=False, allow_null=True`?
  - ✅ **Bom**: `role = CharField(max_length=50, choices=STAFF_ROLES)`

- [ ] **Validação customizada para regras de negócio**:
  - [ ] Se alterando role de staff, serializer previne elevação de privilege?
  - [ ] Se criando recurso compartilhado, serializer valida que criar não excede quota?
  - ✅ **Bom**: `validate_role()` method que compara role atual vs. novo

- [ ] **Proteção contra mass assignment**:
  - [ ] Serializer tem `fields = (...)` ou `exclude = (...)` explícito?
  - ❌ **Evitar**: `fields = '__all__'` em serializer público
  - ✅ **Bom**: `fields = ['id', 'name', 'email', 'status']` (whitelist, não blacklist)

---

### 5. CORS / Security Headers / TLS

- [ ] **CORS não é wildcard**:
  - [ ] Se endpoint é `/api/*`, CORS não permite `Origin: *`
  - [ ] Ou: `CORS_ALLOW_ALL_ORIGINS=False` (padrão seguro em `settings.py`)
  - ✅ **Bom**: CORS list explícita ou origin validation baseado em domínio

- [ ] **Sem credenciais sensitivas em URL**:
  - ❌ **Evitar**: `GET /api/users?token=secret_token`
  - ✅ **Bom**: Token em header `Authorization: Bearer token` ou cookie HttpOnly

- [ ] **Security headers presentes** (validar em browser ou tester):
  - [ ] `Content-Security-Policy` header presente?
  - [ ] `X-Content-Type-Options: nosniff`?
  - [ ] `Strict-Transport-Security` (HSTS) em prod/staging?
  - [ ] `Permissions-Policy` bloqueando camera, geolocation, etc?
  - ✅ **Bom**: Middleware `SecurityHeadersMiddleware` em `salonix_backend/middleware.py`

---

### 6. Logging & Monitoring

- [ ] **Ações sensiveis sao logadas**:
  - [ ] CREATE/UPDATE/DELETE de dados PII, billing, staff?
  - [ ] Falhas de autenticação/autorização?
  - [ ] Mudanças de role ou status?
  - ✅ **Bom**: Use `RequestLoggingMiddleware` (X-Request-ID) + application-level logs em `perform_*()` ou serializer `save()`

- [ ] **Logs não incluem PII desnecessário**:
  - ❌ **Evitar**: Logar senha, token, SSN, CPF em plain text
  - ✅ **Bom**: Logar `user_id`, `tenant_id`, `action`, `timestamp`, `status_code` (sem dados privados)

- [ ] **Alertas configurados para anomalias**:
  - [ ] Múltiplas falhas de autenticação consecutivas? → Flag/alert
  - [ ] Taxa de throttle violações subindo? → Alert
  - ✅ **Bom**: Monitoring via Sentry ou logs estruturados

---

### 7. Testing & Validation

- [ ] **Testes de autorização**:
  - [ ] Teste que usuário sem permissão retorna 403?
  - [ ] Teste que usuário de outro tenant não acessa dados?
  - [ ] Teste que role não pode ser elevado indevidamente?
  - ✅ **Bom**: `test_create_staff_requires_owner.py` + `test_cross_tenant_isolation.py`

- [ ] **Testes de throttle**:
  - [ ] Teste que muitos requests em pouco tempo retornam 429?
  - ✅ **Bom**: `test_payment_throttle_is_applied.py`

- [ ] **Testes de validação**:
  - [ ] Teste com input inválido (tipo errado, string muito longa)?
  - [ ] Teste com missing required field?
  - ✅ **Bom**: `test_create_staff_invalid_role.py`

- [ ] **Testes de error handling**:
  - [ ] Teste que erro retorna mensagem genérica (não revela PII)?
  - ✅ **Bom**: `test_error_response_does_not_leak_pii.py`

---

## Exemplo Prático: Novo Endpoint

### Cenário
Adicionar endpoint POST `/api/tenants/{tenant_id}/invitations` que cria um convite de staff.

### Checklist Preenchido

```python
# 1. Autorização & Acesso por Objeto/Tenant
✅ permission_classes = [IsAuthenticated]  # Explícito
✅ serializer valida que user.staff_member.role == OWNER  # Role check
✅ serializer filtra tenant do request.user (não from URL param)

# 2. Throttling & Rate-Limiting
✅ Risco: MEDIUM — convite pode ser spam
✅ throttle_classes = [StaffInvitationThrottle]  # scope='staff_invitation'
✅ DEFAULT_THROTTLE_RATES['staff_invitation'] = '20/hour'  # 20 convites/hora

# 3. Error Handling
✅ Permissão fail → 403 (não 404)
✅ Mensagem genérica: "Você não tem permissão para criar convites"

# 4. Input Validation
✅ Serializer valida email, role choices, etc.
✅ fields = ['email', 'role', 'expires_at']  (whitelist)

# 5. CORS / Headers
✅ CORS não é wildcard (settings.py)
✅ SecurityHeadersMiddleware ativa (path-aware CSP)

# 6. Logging
✅ Log: "Staff invitation created: user={}, tenant={}, target_email={}, timestamp={}"
✅ Sem plain-text password ou token nos logs

# 7. Testing
✅ test_staff_invitation_requires_owner()
✅ test_staff_invitation_cross_tenant_forbidden()
✅ test_staff_invitation_throttle()
✅ test_invalid_email_rejected()
```

---

## Integracao com Fluxo de PR

### Code Review Checklist (adicionar à PR template)

```markdown
## Security Review

- [ ] Novo endpoint segue Security Endpoint Checklist (`docs/SECURITY_ENDPOINT_CHECKLIST.md`)?
- [ ] Testes de autorização inclusos (permissão, tenant, role)?
- [ ] Throttle/rate-limit configurado (se aplicável)?
- [ ] Mensagens de erro não revelam PII?
- [ ] Validação de entrada completa (tipos, choices, max length)?
- [ ] Logs presentes e sem dados sensitivos?
```

### Referência Rápida em Terminal

Para lembrete rápido, adicione alias ao `.bashrc` / `.zshrc`:

```bash
alias be-sec-checklist='cat /Users/pablo/Project/salonix/salonix-backend/docs/SECURITY_ENDPOINT_CHECKLIST.md | less'
```

---

## Links Relacionados

- [Sensitive Endpoints Inventory](./SENSITIVE_ENDPOINTS_INVENTORY.md) — Catálogo de endpoints de alto risco
- [BE_RULES.md](../BE_RULES.md) — Convenções e padrões do backend
- [Django Security](https://docs.djangoproject.com/en/5.2/topics/security/)
- [OWASP API Top 10](https://owasp.org/www-project-api-security/)

---

## Changelog

| Data | Versão | Mudança |
|------|--------|---------|
| 2026-04-28 | 1.0 | Inicial — baseado em BE-SEC-04 itens 1-4 |
