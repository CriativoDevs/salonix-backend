# BE-MARKETING-03: Auto-cadastro público de cliente + fix Founder/Basic — Design

**Issue:** #478 (BE-MARKETING-03)
**Branch:** `478-be-marketing-03`
**Depende de:** Nenhuma. Coordenar com FEW-MARKETING-04 (página de auto-cadastro no frontend).

## Contexto

Atualmente o registo de clientes requer que o tenant, manager ou staff crie o cliente manualmente na plataforma (`SalonCustomerViewSet`, autenticado). O objetivo é permitir que o tenant gere um link público único com o seu slug e partilhe-o (redes sociais, WhatsApp, etc.), para que os clientes se registem de forma autónoma, sem intervenção do tenant.

Além do escopo original da issue, esta tarefa também corrige um bug de validação de planos (Founder/Basic) já investigado e documentado em `docs/to_see.md` — combinado com o Pablo em 2026-07-09 para ser tratado nesta tarefa.

## Parte 1 — Endpoint público de auto-cadastro

### Arquitetura

Novo `PublicClientRegistrationView` (`APIView`, `permission_classes = [AllowAny]`) em `core/views.py`, registado em `core/urls.py` como:

```
POST /api/public/<slug:tenant_slug>/clients/register/
```

Segue o padrão já estabelecido por dois endpoints públicos existentes:
- `PublicTenantDetailView` (`core/views.py:504`) — lookup de tenant por slug + `is_active`.
- `PublicClientAccessLinkView` (`core/views.py:2476`) — captcha + throttle + criação/envio de magic link via `send_customer_pwa_invite`.

### Fluxo

1. `enforce_captcha_or_raise(request)` (`users/security.py:26`) — mesma validação de captcha usada no link de acesso. Falha → 400 `{"detail": "Captcha inválido."}`.
2. Buscar `Tenant.objects.get(slug=tenant_slug, is_active=True)`. Não encontrado → 404 genérico.
3. Se `not tenant.can_use_pwa_client()` → 404 genérico (mesmo tratamento de "não existe" — evita vazar que o tenant existe mas está sem PWA Cliente ativo).
4. Validar payload via novo `PublicClientRegistrationSerializer` (`core/serializers.py`):
   - `name` (obrigatório, sanitizado, reaproveita `validate_name` de `SalonCustomerSerializer`)
   - `email` (opcional, normalizado para lowercase)
   - `phone_number` (opcional, sanitizado + validado)
   - `marketing_opt_in` (opcional, default `False`)
   - Validação: pelo menos email ou telefone (reaproveita a mesma regra de `SalonCustomerSerializer.validate`).
5. Checar duplicidade de email no tenant: `SalonCustomer.objects.filter(tenant=tenant, email__iexact=email).exists()` (só quando `email` foi informado) → 400 `{"detail": "Este email já está registado."}`.
6. Criar `SalonCustomer(tenant=tenant, name=..., email=..., phone_number=..., marketing_opt_in=...)`.
7. Disparar `send_customer_pwa_invite(tenant=tenant, customer=customer, invited_by=None)` (`notifications/services.py:52`) — mesmo magic link (JWT via `create_client_access_data`) já usado quando staff adiciona um cliente manualmente com `auto_invite_enabled=True`. Aqui o envio é **incondicional** (não depende de `tenant.auto_invite_enabled`), já que o auto-cadastro é um pedido explícito do próprio cliente.
8. Responder `201`:
   ```json
   {"customer_id": 123, "message": "Cadastro realizado. Verifique o seu email para aceder."}
   ```
   Sem expor o link de acesso na resposta (mesmo padrão do `PublicClientAccessLinkView`, que também nunca retorna o link — só loga em modo DEBUG/dev).

### Proteção contra abuso

Novo throttle `UsersClientRegistrationThrottle` (`users/throttling.py`), scope `clients_registration`, seguindo o padrão de `_BaseUsersThrottle` (igual a `UsersClientAccessLinkThrottle`), chaveado por `tenant_slug` — limita abuso por salão específico sem penalizar outros tenants.

### Erros e status codes

| Cenário | Status |
|---|---|
| Registo válido | 201 |
| Tenant inexistente ou inativo | 404 |
| Tenant sem PWA Cliente ativo | 404 |
| Captcha inválido | 400 |
| Nome ausente / nem email nem telefone informado | 400 |
| Email já registado no tenant | 400 |
| Rate limit excedido | 429 |

## Parte 2 — Fix Founder/Basic

Ver investigação completa em `docs/to_see.md` (seção "Backend: regra Founder/Basic só é aplicada no frontend, nunca validada no backend"). Regra de negócio confirmada pelo Pablo: Founder é uma oferta exclusiva para os primeiros 500 tenants; uma vez esgotadas as vagas, nunca mais fica disponível; **Basic só fica disponível depois de esgotadas as vagas Founder, nunca antes**; um tenant que sai do Founder nunca mais pode voltar (já implementado corretamente via histórico de `Subscription` em `FounderService.can_assign_founder`); um tenant Founder pode alternar livremente entre mensal e anual sem perder o status.

### 1. `CreateCheckoutSession.post` (`payments/views.py:79`)

Antes de processar `requested_plan == "basic"`, se `FounderService.get_availability()["remaining_count"] > 0` e o tenant não é atualmente Founder nem tem histórico de Founder (i.e. `FounderService.can_assign_founder(tenant=tenant)` seria `True` para esse tenant caso pedisse Founder), rejeitar com 400:
```json
{"detail": "O plano Basic ainda não está disponível — restam vagas Founder."}
```

**Não** bloqueia um tenant que já é/foi Founder e está a fazer downgrade deliberado para Basic — essa transição é permitida (e irreversível, regra já existente).

### 2. `BillingService.get_billing_overview` (`payments/services.py:806`)

Passar `tenant=user.tenant` para `SubscriptionService.get_available_plans`, igual ao que `AvailablePlansView` (`payments/views.py:1171`) já faz corretamente.

### 3. `SubscriptionService.get_available_plans` (`payments/services.py:265`)

O campo `is_available` do plano `basic` deixa de ser sempre `True` (linha ~305). Passa a ser:
```python
is_available = (
    FounderService.get_availability()["remaining_count"] == 0
    or (tenant is not None and not FounderService.can_assign_founder(tenant=tenant))
)
```
Ou seja: `basic` fica disponível quando as vagas Founder esgotaram, **ou** quando o tenant já não é elegível para Founder (porque já é/foi Founder). `Pro` fica inalterado (fora de escopo, já bloqueado globalmente via `Tenant.is_plan_blocked`).

### 4. `UserRegistrationSerializer.create` (`users/serializers.py:262`)

Se `data.get("plan", "basic")` for `"basic"` (valor padrão quando o campo é omisso) e `FounderService.can_assign_founder(tenant=None)` for `True` (há vagas globais — tenant ainda não existe neste ponto do registo), rejeitar:
```python
raise serializers.ValidationError(
    {"plan": "O plano Basic ainda não está disponível — restam vagas Founder."}
)
```

### Impacto no frontend

Nenhuma alteração necessária no app nativo (`CreditsPlanScreen.tsx`) nem no PWA (`Plans.jsx`, `PlanOnboarding.jsx`, `RegisterCheckout.jsx`) — ambos já leem `is_available` do backend para desabilitar a opção correspondente. Corrigir o backend resolve os dois lados automaticamente. FEW-MARKETING-04 tratará apenas de eventuais ajustes de UI/copy no PWA, não da lógica de disponibilidade.

## Testes

### Auto-cadastro (`core/tests/test_public_client_registration.py`, novo)

- Registo válido → 201, `SalonCustomer` criado no tenant certo, `send_customer_pwa_invite` chamado (mock)
- Tenant inexistente → 404
- Tenant inativo (`is_active=False`) → 404
- Tenant existente mas com PWA Cliente desativado → 404
- Email duplicado no mesmo tenant (case-insensitive) → 400
- Mesmo email em tenants diferentes → permitido (isolamento por tenant)
- Captcha inválido → 400
- Nome ausente → 400
- Nem email nem telefone informado → 400
- Rate limit excedido → 429

### Founder/Basic (`payments/tests/`, `users/tests/`)

- `CreateCheckoutSession`: tenant novo (sem histórico Founder) pede `basic` com vagas Founder disponíveis → 400
- `CreateCheckoutSession`: tenant novo pede `basic` quando vagas Founder esgotadas → 200
- `CreateCheckoutSession`: tenant Founder pede `basic` (downgrade voluntário), mesmo com vagas Founder restantes → 200
- `BillingService.get_billing_overview`: `is_available` de `basic` reflete disponibilidade Founder + histórico do tenant
- `UserRegistrationSerializer`: registo novo com `plan="basic"` (ou omisso) rejeitado enquanto há vagas Founder
- `UserRegistrationSerializer`: registo novo aceito com `plan` omisso/`"basic"` quando vagas Founder esgotadas

Suíte completa do backend (`pytest`) roda no fim para garantir zero regressões.

## Fora de escopo

- Alterações no `salonix-frontend-web` (fica para FEW-MARKETING-04).
- Alterações no `salonix-mobile` (não são necessárias — confirmado no design).
- Plano `Pro` (já bloqueado globalmente, sem relação com a disponibilidade Founder/Basic).
