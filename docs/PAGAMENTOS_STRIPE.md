# 💳 Pagamentos Stripe — Salonix (EN/PT)

## 🇬🇧 English

### Overview

Salonix integrates with Stripe for subscriptions (plans) and one‑off credit purchases. This document covers environment variables, endpoints, webhook flow, and testing.

### Environment Variables (`.env`)

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_BASIC_MONTHLY_ID`
- `STRIPE_PRICE_STANDARD_MONTHLY_ID`
- `STRIPE_PRICE_PRO_MONTHLY_ID`
- `STRIPE_PRICE_ENTERPRISE_MONTHLY_ID`
- `STRIPE_TRIAL_DAYS` (default: 14)

### Endpoints

- Create plan checkout: `POST /api/payments/checkout/` (body includes `plan_code`).
- Webhooks: `POST /api/payments/webhooks/stripe/` (events: `checkout.session.completed`, `customer.subscription.*`).
- Credits (Stripe Checkout): `POST /api/payments/stripe/credits/checkout/` (mode=payment) e pacotes em `GET /api/payments/stripe/credits/packages/`.
- Credits (balance/ledger): `GET /api/auth/credits/balance/`, `GET /api/auth/credits/history/`, `POST /api/auth/credits/consume/`.
- Realtime (SSE): `GET /api/auth/realtime/credits/` (`text/event-stream`).

### Behaviour

- Plan checkout creates Stripe session with metadata (`plan_code`, `user_id`, `client_reference_id`) and optional trial days.
- Credit checkout creates session (`mode=payment`) com metadata (`type=credit_purchase`, `tenant_id`, `user_id`, `price_id`, `credits_amount`).
- Webhook processa `checkout.session.completed`: atualiza assinatura quando `subscription` presente; aplica créditos quando `metadata.type=credit_purchase` e `payment_status=paid`.
- Logs capturam exceções e métricas refletem resultados.

### Testing

- Use Stripe CLI: `stripe listen --forward-to localhost:8000/api/payments/webhooks/stripe/`.
- Trigger test events: `stripe trigger checkout.session.completed`.
- Configure prices in `.env` with live/test IDs.

---

## 🇧🇷 Português

### Visão Geral

O Salonix integra com Stripe para assinaturas (planos) e compra avulsa de créditos. Este documento cobre variáveis de ambiente, endpoints, fluxo de webhook e testes.

### Variáveis de Ambiente (`.env`)

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_BASIC_MONTHLY_ID`
- `STRIPE_PRICE_STANDARD_MONTHLY_ID`
- `STRIPE_PRICE_PRO_MONTHLY_ID`
- `STRIPE_PRICE_ENTERPRISE_MONTHLY_ID`
- `STRIPE_TRIAL_DAYS` (padrão: 14)

### Endpoints

- Checkout de plano: `POST /api/payments/checkout/` (corpo inclui `plan_code`).
- Webhooks: `POST /api/payments/webhooks/stripe/` (eventos: `checkout.session.completed`, `customer.subscription.*`).
- Créditos (Stripe Checkout): `POST /api/payments/stripe/credits/checkout/` (mode=payment) e pacotes em `GET /api/payments/stripe/credits/packages/`.
- Créditos (saldo/ledger): `GET /api/auth/credits/balance/`, `GET /api/auth/credits/history/`, `POST /api/auth/credits/consume/`.
- Realtime (SSE): `GET /api/auth/realtime/credits/` (`text/event-stream`).

### Comportamento

- Checkout de plano cria sessão Stripe com metadata (`plan_code`, `user_id`, `client_reference_id`) e trial opcional.
- Checkout de créditos cria sessão (`mode=payment`) com metadata (`type=credit_purchase`, `tenant_id`, `user_id`, `price_id`, `credits_amount`).
- Webhook processa `checkout.session.completed`: atualiza assinatura quando `subscription` presente; aplica créditos quando `metadata.type=credit_purchase` e `payment_status=paid`.
- Logs registram exceções e métricas refletem resultados.

### Testes

- Stripe CLI: `stripe listen --forward-to localhost:8000/api/payments/webhooks/stripe/`.
- Disparar eventos de teste: `stripe trigger checkout.session.completed`.
- Configure os preços no `.env` com IDs de teste/live.

### Limites e Custos (créditos)

- Conforme `BUSINESS_OVERVIEW.md`: créditos avulsos disponíveis desde o Basic; custo de SMS ≈ €0,045 (PT); WhatsApp conforme categoria.
- Excedentes: custo + 20% (mínimo €3/mês). Créditos avulsos expiram em 60 dias.
- Políticas e seeds: ver `SEED_DATA_CREDITS.md`.

### Autorização de Compra de Créditos

- Somente `OWNER` ativo do tenant pode comprar créditos avulsos.
- `request.tenant` deve corresponder a `user.tenant` e `tenant.comm_extra_allowed` precisa estar habilitado.
- Em violações, a API retorna `403`.

### SSE de Créditos

- Endpoint `GET /api/auth/realtime/credits/` retorna stream `text/event-stream` com eventos de atualização de saldo/ledger isolados por tenant autenticado.
- Exemplo de evento:
  - `event: credit_update` seguido de `data: {"balance": "19.90", "type": "purchase"}` e uma linha em branco.
  - Heartbeat periódico para manter conexão.
