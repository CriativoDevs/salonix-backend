# Plans: nomenclatura pública + exibição de plano único — Design

**Repos afetados:**
- `salonix-backend` (branch `be-plans-03-single-plan-display`) — lógica principal
- `salonix-frontend-web` (branch `few-plans-03-single-plan-display`) — correção de nomenclatura, sem mudança de lógica
- `salonix-mobile` (branch a criar) — sem mudança de código, só verificação/teste

## Contexto

Durante a revisão do ecrã "Créditos e Plano" do app nativo (screenshot iOS), o Pablo identificou dois problemas:

1. **Nomenclatura interna vazando para o utilizador final.** "basic" é o nome interno do plano; o nome público deve ser "TimelyOne". O plano "founder" deve aparecer publicamente como "TimelyOne Founder".
2. **Duas opções lado a lado quando já há uma escolha feita.** Quando o tenant já tem uma subscrição paga ativa (Founder ou TimelyOne), o ecrã de gestão (Créditos e Plano no MOB, e `/plans` no PWA quando autenticado com plano ativo) mostra as duas opções como se fosse uma escolha em aberto — mas trocar de Founder para TimelyOne não faz sentido enquanto ativo (TimelyOne é mais caro), e trocar de TimelyOne para Founder já é bloqueado pela regra da BE-MARKETING-03 (quem sai do Founder nunca mais volta). A única escolha que devia restar nesse estado é o ciclo de faturação (mensal/anual) — e essa já é resolvida pelo botão "Gerir subscrição" (portal do Stripe), sem precisar de UI nova.

Confirmado com o Pablo: **durante o trial** (sem subscrição paga ainda), o ecrã continua a mostrar as duas opções normalmente, para permitir a escolha inicial. A restrição só se aplica quando já existe uma subscrição com status `active` ou `past_due` (ou seja, já é pagante — `trialing` não conta).

## Investigação relevante

- `payments/services.py:234-262` (`SubscriptionService.AVAILABLE_PLANS`) — dicionário com `"basic"` e `"pro"`, cada um com campo `"name"`.
- `payments/services.py:264-341` (`get_available_plans`) — monta a lista final; a entrada do Founder é adicionada inline dentro do método (não está no dicionário `AVAILABLE_PLANS`), com `"name": "Founder"` hardcoded.
- `payments/services.py:447-...` (`get_current_subscription`) — só considera subscrições com `status__in=["active", "trialing", "past_due"]`; o dict retornado inclui `"status"`, distinguindo `trialing` (ainda em trial) de `active`/`past_due` (já pagante).
- `payments/services.py:810-870` (`get_billing_overview`) — chama `get_available_plans(current_subscription["plan_code"] if current_subscription else None, tenant=...)`, sem hoje considerar o `status` da subscrição.
- `payments/views.py:1171` (`AvailablePlansView`) — endpoint separado que também chama `get_available_plans`, mas **não é consumido por nenhum FE/MOB atual** (confirmado por busca em ambos os repos) — só existe como endpoint standalone, provavelmente legado.
- `salonix-frontend-web/.../src/pages/Plans.jsx` (pós FEW-MARKETING-04) — usa `mergePlanAvailability(PLAN_OPTIONS, overview.available_plans)`; o nome exibido vem de `t('plans.options.${code}.name', p.name)` — **a chave i18n já existe e tem prioridade sobre o `name` do backend**. `pt.json`/`en.json` já têm `plans.options.basic.name = "TimelyOne"` (correto), mas `plans.options.founder.name = "Founder"` (precisa de correção).
- `salonix-mobile/.../src/screens/CreditsPlanScreen.tsx:196-215` — itera `availablePlans.map(...)` e renderiza `{plan.name}` **diretamente**, sem indireção i18n. Não tem seletor mensal/anual — só `price_monthly` e um botão "Mudar para este plano" por plano, mais um botão "Gerir subscrição" (abre o portal do Stripe) já existente.

## Parte 1 — Backend (`salonix-backend`)

### Nomenclatura

Em `payments/services.py`:
- `AVAILABLE_PLANS["basic"]["name"]`: `"Basic"` → `"TimelyOne"`.
- Dentro de `get_available_plans`, a entrada inline do Founder: `"name": "Founder"` → `"name": "TimelyOne Founder"`.

`AVAILABLE_PLANS["pro"]["name"]` fica inalterado (Pro está bloqueado globalmente, fora de escopo).

### Filtro de plano único quando já pagante

`get_available_plans` passa a aceitar um novo parâmetro `subscription_status: Optional[str] = None`. Regra adicionada no fim do método, antes do `return plans`:

```python
only_current = current_plan is not None and subscription_status in ("active", "past_due")
if only_current:
    plans = [p for p in plans if p["is_current"]]
```

Os dois call sites que hoje chamam `get_available_plans` passam a fornecer também o status:
- `get_billing_overview` (`payments/services.py:810-816`) — já tem `current_subscription` disponível; passa `current_subscription.get("status") if current_subscription else None`.
- `AvailablePlansView.get` (`payments/views.py:1171`) — mesma mudança, por consistência, ainda que este endpoint não seja consumido hoje por nenhum cliente.

**Por que aqui e não em `get_billing_overview`:** manter a regra dentro de `get_available_plans` garante que qualquer consumidor futuro do método (incluindo `AvailablePlansView`) se beneficia automaticamente, em vez de duplicar a lógica em cada call site — mesmo padrão já usado para `FounderService.is_basic_blocked`.

### Comportamento resultante

| Situação do tenant | Lista devolvida |
|---|---|
| Sem subscrição (trial ou nunca assinou) | Todos os planos elegíveis (comportamento atual, inalterado) |
| Subscrição `trialing` | Todos os planos elegíveis (comportamento atual, inalterado) |
| Subscrição `active`/`past_due` no TimelyOne | Só a entrada `basic` (`is_current: true`) |
| Subscrição `active`/`past_due` no Founder | Só a entrada `founder` (`is_current: true`) |

## Parte 2 — Frontend Web (`salonix-frontend-web`)

Única mudança: adicionar a chave i18n em falta.

`src/i18n/locales/pt.json` e `en.json`, dentro de `plans.options.founder`:
```json
"name": "TimelyOne Founder"
```

(substituindo o valor atual `"Founder"`). Nenhuma mudança em `Plans.jsx`, `PlanOnboarding.jsx` ou `RegisterCheckout.jsx` — a filtragem para 1 plano já vem pronta do backend via `overview.available_plans`, e o layout `grid sm:grid-cols-2` já suporta 1 ou 2 itens sem alteração (grid simplesmente não preenche a segunda coluna quando há só 1 filho).

## Parte 3 — Mobile (`salonix-mobile`)

Nenhuma mudança de código — `CreditsPlanScreen.tsx` já renderiza `plan.name` e itera `availablePlans` sem lógica própria, então herda automaticamente a nomenclatura e a filtragem do backend. Apenas se adiciona cobertura de teste (ver seção de testes) para pinar esse comportamento e evitar regressão futura.

## Testes

### Backend (`payments/tests/test_payments_stripe.py`)

- `get_available_plans` com `subscription_status="active"` e `current_plan="basic"` → devolve só a entrada `basic`.
- `get_available_plans` com `subscription_status="active"` e `current_plan="founder"` → devolve só a entrada `founder`.
- `get_available_plans` com `subscription_status="trialing"` → devolve a lista completa (comportamento inalterado).
- `get_available_plans` com `subscription_status=None` (sem subscrição) → devolve a lista completa (comportamento inalterado).
- `get_available_plans` com `subscription_status="past_due"` → mesmo comportamento que `"active"` (só o plano atual).
- Verificar que os nomes retornados são `"TimelyOne"` e `"TimelyOne Founder"`.
- `get_billing_overview`: tenant com subscrição `active` no plano `basic` → `overview["available_plans"]` tem só 1 item.

### Frontend Web

Nenhum teste novo necessário além de confirmar visualmente/manualmente que a chave i18n aparece corretamente — não há lógica nova para testar (o comportamento de filtragem já é coberto pelos testes existentes de `Plans.jsx`/`PlanOnboarding.jsx`/`RegisterCheckout.jsx` da FEW-MARKETING-04, que já teste o `is_available`/render condicional a partir de `available_plans`).

### Mobile

Adicionar um teste a `CreditsPlanScreen.test.tsx`: mock de `fetchBillingOverview` retornando `available_plans` com 1 único item (`is_current: true`) → o ecrã renderiza só esse card, com o nome vindo diretamente do mock (ex.: `"TimelyOne Founder"`), sem necessidade de mudança no componente.

## Fora de escopo

- Seletor mensal/anual novo no MOB — decisão consciente de usar o "Gerir subscrição" (portal do Stripe) existente, conforme confirmado com o Pablo.
- Auditoria de gates de plano/feature no MOB — tarefa seguinte, já combinada, mas não faz parte desta.
- Qualquer mudança em `AvailablePlansView` além de passar o novo parâmetro — o endpoint continua sem consumidores conhecidos.
