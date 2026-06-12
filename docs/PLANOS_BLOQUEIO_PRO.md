# BE-PLANS-01: Bloqueio do Plano Pro e Consolidação de Features no Basic/Founder

> **Issue:** #481 · **Branch:** `481-be-plans-01` · **Data:** 2026-06-12
>
> Coordenar depois com **FEW-PLANS-01** (frontend web) e **MOB-PLANS-01** (mobile).

## Decisão de produto

O plano **Pro foi bloqueado** — invisível e inacessível em qualquer fluxo público —
mas **preservado no código** para possível reativação futura. Os planos **Basic e
Founder absorveram todas as features** que eram exclusivas do Pro, tornando o Basic
o plano comercial principal.

Pontos importantes do escopo (esclarecidos em conjunto com o produto):

- A absorção é **apenas de features**. Preços e créditos de comunicação **não mudam**:

  | Plano   | Preço mensal | Créditos iniciais |
  |---------|--------------|-------------------|
  | Basic   | €29,00       | €5,00             |
  | Founder | €15,00       | €2,00             |
  | Pro     | (bloqueado)  | (bloqueado)       |

- O **Founder também recebe** as features ex-Pro. A frase "Founder permanece
  inalterado" da issue refere-se a preço, créditos e condições comerciais.
- Permissões de papel (Tenant/Owner, Manager, Staff) **não mudaram**.

## Features ex-Pro absorvidas por Basic e Founder

- Relatórios avançados (Business Analysis + Insights, Top Services, Revenue, Retention).
- White-label.
- Domínio personalizado (continua dependendo da flag `custom_domain_enabled`).
- Apps nativos Admin e Client (React Native).
- Push mobile.
- Notificações avançadas (SMS/WhatsApp) por plano — antes exigiam Pro ou créditos extras.
- Auto-renovação de créditos de comunicação (feature liberada; valores não mudam).
- Retenção pós-cancelamento de 90 dias (Basic tinha 30; Founder já tinha 90).
- Exports assíncronos de relatórios do tipo `advanced`.

## Como o bloqueio funciona

### Fonte única de verdade

`users/models.py` — classe `Tenant`:

```python
BLOCKED_PLANS = [PLAN_PRO]

@classmethod
def is_plan_blocked(cls, plan_code) -> bool: ...
```

O Pro **permanece** em `PLAN_CHOICES` (dados históricos e reativação futura), mas
nenhum fluxo público o lista ou atribui. Para reativar o Pro no futuro, basta
remover o código de `BLOCKED_PLANS` e revisar os pontos listados abaixo.

### Pontos de aplicação

| Camada | Arquivo | Comportamento |
|---|---|---|
| Listagem pública de planos | `payments/services.py` (`get_available_plans`) | Planos bloqueados são filtrados do `plan_order`; nunca chegam ao frontend |
| Checkout (serializer v2) | `payments/serializers.py` (`validate_plan`) | `plan="pro"` → HTTP 400 "Este plano não está disponível no momento." |
| Checkout (view legada) | `payments/views.py` (`CreateCheckoutSession`) | `allowed_plans = {"basic", "founder"}` → HTTP 400 |
| Webhooks Stripe | `payments/views.py` (3 pontos) e `payments/webhooks.py` (2 pontos) | Evento residual com plano bloqueado **não** altera `plan_tier`; loga `warning` com tenant e plano — sem erro silencioso |
| Billing overview | `payments/views.py` (`BillingOverviewView`) | Sync de plano em GET nunca aplica plano bloqueado |
| Conversão promocional | `users/models.py` (`apply_promotional_transition`) | Se `promotional_converts_to_plan` for bloqueado, converte para Basic |
| Console OPS | `ops/serializers.py` (`OpsTenantPlanUpdateSerializer`) | `plan_tier="pro"` rejeitado com erro de validação |
| Django Admin | `users/admin.py` | Ver seção abaixo |
| Créditos iniciais | `users/signals.py` (sem alteração) | Pro fora de `get_available_plans` → tenant criado como Pro não recebe crédito inicial |

### Tenants legados em Pro

Tenants que ainda estejam com `plan_tier="pro"` (em produção, 2 contas de teste)
**continuam funcionando** — os métodos de gating incluem o Pro nas listas de planos
permitidos. A migração é feita explicitamente pelo management command (abaixo).

## Mudanças de gating (`users/models.py` e `users/feature_flags.py`)

Métodos do `Tenant` atualizados para `plan_tier in [PLAN_BASIC, PLAN_PRO, PLAN_FOUNDER]`:

- `can_use_advanced_reports()` — antes só Pro.
- `can_use_white_label()` — antes só Pro.
- `can_use_custom_domain()` — antes Pro + flag; agora qualquer plano ativo + flag.
- `can_use_native_admin()` / `can_use_native_client()` — antes Pro ou flag explícita.
- `can_use_advanced_notifications()` — antes Pro (ou canal + créditos extras).
- `can_use_pwa_client()` — agora inclui `PLAN_FOUNDER` na lista (correção de lacuna).
- `get_retention_days()` — Basic: 30 → **90 dias**.

Em `users/feature_flags.py`, a `plan_hierarchy` usada por `requires_plan()` /
`RequiresPlan` foi nivelada (todos os planos ativos no nível 2). De passagem,
**corrigido um bug**: `founder` não existia na hierarquia e caía para nível 0 —
um tenant Founder falharia qualquer `requires_plan('pro')`.

Em `users/views.py`, o toggle de `push_mobile_enabled` deixou de exigir Pro
(passa a aceitar qualquer plano ativo).

Em `ops/views.py` (`update_plan`), a lógica de conflitos "planos não-Pro não
suportam SMS/WhatsApp/addons" foi removida — todos os planos ativos suportam;
mudanças de plano não desativam mais esses recursos.

`get_feature_flags_dict()` não precisou de alteração: ele delega aos métodos
`can_use_*`, então o payload exposto ao frontend reflete automaticamente as
novas capacidades.

## Migração dos tenants (management command)

```bash
python manage.py migrate_tenants_to_basic --dry-run   # lista sem alterar
python manage.py migrate_tenants_to_basic             # executa
```

Arquivo: `users/management/commands/migrate_tenants_to_basic.py`

- Seleciona tenants com `plan_tier` em `BLOCKED_PLANS` (Founder não é tocado).
- **Idempotente**: re-execuções não alteram tenants já migrados ("Nada a migrar").
- Transação atômica com `select_for_update`; log estruturado por tenant
  (`tenant_id`, plano antigo → novo) + saída legível no stdout.

Após o deploy desta tarefa, rodar o command em produção para migrar as 2 contas
de teste.

## Django Admin (`users/admin.py`)

- Ação em massa **"Upgrade para plano Pro" removida**.
- `plan_tier` e `promotional_converts_to_plan`: choices filtrados via
  `formfield_for_choice_field` — Pro não aparece ao criar/editar tenant
  (registros históricos mantêm o valor salvo).
- Filtro lateral de plano substituído por `PlanTierListFilter` (custom), que
  oculta planos bloqueados das opções.

## Testes

Suite completa: **906 passed, 5 skipped** (`python -m pytest`).

### Novos (`users/tests/test_plan_blocking.py`, 17 testes)

- Pro bloqueado / Basic e Founder não bloqueados.
- Pro ausente de `get_available_plans()`.
- Checkout com `plan="pro"` rejeitado (view legada e v2).
- Conversão promocional nunca resulta em plano bloqueado.
- Basic e Founder com todas as features ex-Pro; retenção 90 dias.
- Domínio custom continua exigindo flag.
- Owner Basic consegue ativar auto-renovação de créditos.
- Preço/créditos do Basic inalterados (€29/€5).
- OPS rejeita Pro e aceita Basic.
- Command: migra Pro→Basic, não toca Founder, idempotente, `--dry-run` não altera.

### Atualizados (~25 testes em 13 arquivos)

Testes que assumiam o gating antigo foram invertidos (Basic agora tem acesso) ou
adaptados. Destaques:

- **Cobertura do caminho de negação preservada**: como nenhum plano ativo é mais
  negado nos apps mobile, os testes do payload 403 (`PLAN_UPGRADE_REQUIRED`) em
  `users/tests/test_permissions.py` e `test_mobile_app_access.py` passaram a
  mockar `Tenant.can_use_native_admin/client` — a máquina de negação continua
  testada sem depender de um plano negado real.
- `test_pro_plan_initial_credits`: tenant criado como Pro **não recebe** crédito
  inicial (consequência do signal usar `get_available_plans`); documentado no teste.
- Cancelamento: fixtures ajustadas para a retenção de 90 dias do Basic.
- OPS: troca de plano não gera mais conflito 409; upgrade de teste usa Founder.

### Nota sobre o conftest global

O tenant default dos testes (`conftest.py`, `setup_default_tenant`) usa
`plan_tier="pro"` — mantido de propósito: valida que tenants legados em Pro
continuam operando normalmente até a migração.

## Reativação futura do Pro (checklist)

1. Remover `PLAN_PRO` de `Tenant.BLOCKED_PLANS`.
2. Reavaliar `AVAILABLE_PLANS["pro"]` (preço/features/créditos) em `payments/services.py`.
3. Decidir se as features voltam a ser exclusivas (reverter listas nos `can_use_*`).
4. Restaurar choices/filtros no Django Admin se desejado.
5. Revisar testes de `test_plan_blocking.py` (vão falhar apontando os pontos).
