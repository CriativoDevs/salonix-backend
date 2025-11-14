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
- Create checkout: `POST /api/payments/checkout/` (body includes `plan_code`).
- Webhooks: `POST /api/payments/webhooks/stripe/` (events: `checkout.session.completed`, `customer.subscription.*`).
- Credits: `POST /api/credits/add/` creates PaymentIntent for top‑up; history in `GET /api/credits/history/`.

### Behaviour
- Checkout creates Stripe session with metadata (`plan_code`, `user_id`, `client_reference_id`) and optional trial days.
- Webhook updates `Subscription`, `UserFeatureFlags`, and `Tenant.plan_tier` accordingly.
- Logs capture exceptions without failing the HTTP response; Prometheus metrics reflect outcomes.

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
- Criar checkout: `POST /api/payments/checkout/` (corpo inclui `plan_code`).
- Webhooks: `POST /api/payments/webhooks/stripe/` (eventos: `checkout.session.completed`, `customer.subscription.*`).
- Créditos: `POST /api/credits/add/` cria PaymentIntent para recarga; histórico em `GET /api/credits/history/`.

### Comportamento
- Checkout cria sessão Stripe com metadata (`plan_code`, `user_id`, `client_reference_id`) e trial opcional.
- Webhook atualiza `Subscription`, `UserFeatureFlags` e `Tenant.plan_tier` conforme o plano.
- Logs registram exceções sem derrubar a resposta; métricas Prometheus refletem resultados.

### Testes
- Stripe CLI: `stripe listen --forward-to localhost:8000/api/payments/webhooks/stripe/`.
- Disparar eventos de teste: `stripe trigger checkout.session.completed`.
- Configure os preços no `.env` com IDs de teste/live.