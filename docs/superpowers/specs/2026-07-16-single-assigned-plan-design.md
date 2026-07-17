# Plano Único Atribuído no Registo — Design

**Repos afetados:**
- `salonix-backend` (branch `be-plans-04-single-assigned-plan`)
- `salonix-frontend-web` (branch `few-plans-04-single-assigned-plan`)
- `salonix-mobile` (branch `86-mob-parity-01`, reaproveitado) — sem mudanças de código, herda automaticamente

## Contexto

Sucessor direto da `be-plans-03-single-plan-display` (já em produção). Ao testar manualmente, o Pablo identificou que a regra implementada ali — "só mostrar o plano atual quando há uma subscrição Stripe `active`/`past_due`" — é incompleta: um tenant em trial (sem subscrição Stripe ainda) ou com `billing_mode="promotional"` (atribuído manualmente via Django Admin, sem nunca passar pelo Stripe) continua a ver as duas opções de plano lado a lado, mesmo já tendo um plano efetivamente atribuído.

Confirmado com o Pablo que **não é crítico para clientes reais** — `billing_mode="promotional"` nunca é definido programaticamente em lado nenhum do código, é exclusivamente uma ação manual no Django Admin (confirmado por grep em todo o backend). Mas o caso do trial genuíno **afeta todos os clientes reais durante os primeiros 14 dias**, e foi isso que motivou a regra mais simples abaixo.

## Regra nova (substitui a anterior)

O plano do tenant é decidido **uma única vez, no momento do registo**, com base na disponibilidade de vagas Founder nesse instante (`FounderService.can_assign_founder()`, sem histórico de tenant, já que ele ainda não existe). A partir daí, **em toda a plataforma e em qualquer estado** (trial, subscrição ativa, promocional, o que for), mostra-se sempre só esse plano — nunca uma comparação entre Founder e TimelyOne. O mensal/anual continua sempre uma escolha ativa e disponível (via checkout inicial, ou depois via "Gerir subscrição"/portal do Stripe).

A fonte de verdade deixa de ser o estado da subscrição Stripe (`subscription_status`) e passa a ser sempre `tenant.is_founder`/`tenant.plan_tier` — campos já atribuídos no registo e persistentes independentemente de como o billing é gerido depois.

## Parte 1 — Backend

### 1.1 `SubscriptionService.get_available_plans` (`payments/services.py:264-363`)

Remove o parâmetro `subscription_status` (introduzido na `be-plans-03`, agora órfão) e a lógica `only_current` associada. No lugar, depois de montar a lista completa (Founder + Basic, com `is_available`/`is_current`/`can_upgrade` calculados como hoje), filtra sempre para a entrada cujo `plan_code` corresponde ao plano atribuído do tenant:

```python
if tenant is not None:
    assigned_plan = "founder" if tenant.is_founder else tenant.plan_tier
    filtered = [p for p in plans if p["plan_code"] == assigned_plan]
    if filtered:
        plans = filtered
```

O `if filtered:` (só substitui se encontrar) é uma salvaguarda para tenants legados com `plan_tier="pro"` (bloqueado, não aparece na lista construída) — nesse caso raro, mantém o comportamento antigo (lista completa) em vez de devolver uma lista vazia. Fora de escopo resolver isso agora — plano Pro já está descontinuado para novas subscrições.

Os dois call sites (`BillingService.get_billing_overview` em `payments/services.py:831`, `AvailablePlansView.get` em `payments/views.py:1192`) deixam de passar `subscription_status` — simplesmente `tenant=` chega.

### 1.2 `UserRegistrationSerializer.create` (`users/serializers.py:262-322`)

Hoje confia no campo `plan` enviado pelo cliente:
```python
requested_plan = data.get("plan", "basic")
if requested_plan == "founder":
    if not FounderService.can_assign_founder():
        raise ValidationError(...)
    is_founder = True
elif requested_plan == "basic" and FounderService.is_basic_blocked():
    raise ValidationError(...)
```

Passa a decidir sozinho, ignorando `data.get("plan")` para esta decisão:
```python
is_founder = FounderService.can_assign_founder()
```

O campo `plan` continua a existir no serializer (não remover, para não quebrar contratos de API existentes/testes que o enviem), mas deixa de influenciar `is_founder` — o servidor é sempre a autoridade.

**Nota importante:** confirmámos que `Register.jsx` (FEW) já nem envia `plan` hoje — este fix resolve uma inconsistência que já existia (o backend validava um campo que o frontend nunca mandava, na prática sempre caindo em `"basic"` por default, o que já estava a rejeitar o registo sempre que havia vagas Founder disponíveis — um bug ativo em produção agora mesmo, corrigido por este fix).

### 1.3 `CreateCheckoutSession.post` (`payments/views.py`, view de checkout inicial)

Mesmo princípio — deixa de confiar no `plan` enviado pelo cliente para decidir Founder vs Basic. Usa sempre `tenant.is_founder`/`tenant.plan_tier` (já atribuído no registo) para determinar o plano do checkout, ignorando/substituindo o `plan` do payload. O `interval` (mensal/anual) continua a vir do cliente normalmente, sem alteração.

## Parte 2 — Frontend Web

### `RegisterCheckout.jsx` e `PlanOnboarding.jsx`

Deixam de ser um `.map()` sobre `plans` com cards clicáveis (`onClick={() => setSelected(p.code)}`) — como `get_available_plans` agora devolve sempre 1 único plano, mostram diretamente esse plano (sem grelha de comparação), mantendo o toggle mensal/anual já existente e o botão de checkout.

`Plans.jsx` (ecrã de gestão pós-registo) já fica correto automaticamente, sem alterações — já consome `overview.available_plans` da mesma forma.

## Parte 3 — Mobile

Sem alterações de código — `CreditsPlanScreen.tsx` itera `availablePlans` sem lógica própria, herda automaticamente a lista já filtrada a 1 item.

## Testes a reescrever

Backend (`payments/tests/test_payments_stripe.py`):
- `test_get_available_plans_shows_all_when_trialing` — deixa de fazer sentido nesta forma; sai o `subscription_status="trialing"`, o teste passa a confirmar que devolve só 1 plano mesmo sem subscrição Stripe.
- `test_get_available_plans_shows_all_when_no_subscription` — mesma coisa.
- `test_get_available_plans_returns_correct_auto_renew_and_credits` — hoje assume que basic+founder aparecem juntos; passa a assumir só 1 (o atribuído ao tenant do teste).
- `test_get_available_plans_uses_public_plan_names` — mesma correção.
- `test_get_available_plans_shows_only_current_when_active`/`_when_past_due` — a intenção destes testes (mostrar só o plano atual quando pagante) passa a ser o comportamento *sempre*, não um caso especial — podem manter-se como estão ou fundir-se com os testes gerais.

`users/tests/test_founder_plan.py` (`TestRegistrationBasicBlockedByFounder`):
- Muda de sentido completamente: deixa de testar "o servidor aceita/rejeita o `plan` que o cliente pediu" para testar "o servidor decide sozinho, ignorando o que o cliente pedir" — os testes passam a enviar `plan="basic"` propositadamente com vagas Founder disponíveis, e a esperar `is_founder=True` de qualquer forma (a decisão do servidor prevalece).

Frontend: os testes já existentes de `Plans.test.jsx`, `PlanOnboarding.test.jsx`, `RegisterCheckout.test.jsx` (da `few-plans-03`) já mockam `overview.available_plans` diretamente com o array que quiserem — precisam de passar a mockar sempre 1 único item (não 2), e as asserções de "múltiplos cards clicáveis" em `PlanOnboarding.test.jsx`/`RegisterCheckout.test.jsx` (se existirem) precisam de atualização para o novo layout de card único.

## Fora de escopo

- Plano Pro (legado, já bloqueado para novos registos).
- Réplica de qualquer UI nova no MOB — não há ecrã de registo/checkout no MOB (`RegisterScreen.js` recusa registo, direciona para a web).
- Migração de dados para tenants `plan_tier="pro"` existentes.
