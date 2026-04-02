# Salonix Backend

Backend for Salonix, a scheduling platform for salons, built with Django REST Framework.

This repository exposes the backend API consumed by the web frontend (React) and the mobile app (Expo/React Native).

---

## 🚀 Tech Stack

- Python 3.11+
- Django 5.x
- Django REST Framework
- drf-spectacular (OpenAPI 3)
- pytest
- SQLite / PostgreSQL (depending on environment)
- Stripe integration for subscriptions

---

## 📂 Project Structure

```
salonix-backend/
├── core/              # Appointments, services, schedules, series
├── users/             # Auth, tenants, staff, feature flags, SSE
├── payments/          # Stripe subscriptions, checkout, webhooks
├── reports/           # Reports, caching, exports
├── notifications/     # Notification devices, services, signals
├── ops/               # Ops admin APIs, metrics, permissions
├── salonix_backend/   # Django settings, middleware, admin, urls
├── docs/              # Backend docs and runbooks
├── scripts/           # Seeds and smoke scripts
├── tests/             # Cross-app tests
├── static/            # Admin assets and DRF spectacular assets
├── requirements.txt
├── api-schema.yaml
├── manage.py
└── README.md
```

---

## ⚙️ Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/<org>/salonix-backend.git
   cd salonix-backend
   ```
2. Create virtualenv:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Install deps:
   ```bash
   pip install -r requirements-dev.txt
   ```
4. Environment variables (`.env` or `settings.ini`):
   ```bash
   DJANGO_ENV=dev
   SECRET_KEY=...
   DEBUG=True
   DATABASE_URL=sqlite:///db.sqlite3
   STRIPE_SECRET_KEY=...
   STRIPE_WEBHOOK_SECRET=...
   USERS_AUTH_THROTTLE_LOGIN=10/min
   USERS_AUTH_THROTTLE_REGISTER=5/min
   USERS_TENANT_META_PUBLIC=60/min
   CAPTCHA_ENABLED=false
   CAPTCHA_PROVIDER=turnstile  # or hcaptcha
   CAPTCHA_SECRET=
   CAPTCHA_BYPASS_TOKEN=
   ```
5. Migrations:
   ```bash
   python manage.py migrate
   ```
6. Superuser:
   ```bash
   python manage.py createsuperuser
   ```

---

## 🧪 Tests

- Run full suite:
  ```bash
  pytest
  ```
- Run only reports tests:
  ```bash
  pytest reports/tests/
  ```

---

## 🔒 Self-service Hardening (BE-212)

- Protected endpoints: `POST /api/users/register/`, `POST /api/users/token/` (throttle + optional captcha) and `GET /api/users/tenant/meta/` (public throttle).
- Env vars: `USERS_AUTH_THROTTLE_LOGIN`, `USERS_AUTH_THROTTLE_REGISTER`, `USERS_TENANT_META_PUBLIC`, `CAPTCHA_*`.
- Dev/Test: throttling defaults are high; use `override_settings` to test 429; captcha bypass via `X-Captcha-Token`.

## 🔑 Password Recovery (BE-240)

- `POST /api/users/password/reset/` (neutral response `{"status":"ok"}`) and `POST /api/users/password/reset/confirm/` (uid + token + new_password).
- Throttle `users_password_reset`; captcha on request.
- Metric: `users_password_reset_events_total{event,result}`.

## 🔍 Smoke Tests

1. Terminal A: start backend (`make run` or `python manage.py runserver`).
2. Terminal B:
   ```bash
   make smoke  # wrapper for ./scripts/smoke_reports.sh
   ```

Seeded credentials:

- `pro_smoke@demo.local / Smoke@123`
- `client_smoke@demo.local / Smoke@123`
- Set `SMOKE_USER_PASSWORD=...` before `make seed` to override default.

What does the script do?

- Authenticates as `pro_smoke`.
- Calls `/api/reports/overview/`, `/top-services/`, `/revenue/` and exports CSV with backoff.
- Validates throttling and Prometheus metrics.

Note: run `make seed` to populate demo data before smoke.

---

## 💳 Stripe / Billing

- Configure monthly plan prices via `.env`:
  - `STRIPE_PRICE_BASIC_MONTHLY_ID`
  - `STRIPE_PRICE_STANDARD_MONTHLY_ID`
  - `STRIPE_PRICE_PRO_MONTHLY_ID`
  - `STRIPE_PRICE_ENTERPRISE_MONTHLY_ID`
- Optional: `STRIPE_TRIAL_DAYS` controls trial (default: 14 days).
- Return URLs (`STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`, `STRIPE_PORTAL_RETURN_URL`) should point to FE.
- Manual test: call `/api/payments/stripe/create-checkout-session/` with `plan="basic|standard|pro|enterprise"` and confirm Stripe redirects.

---

## 📖 API Documentation

- Raw schema: `/api/schema/`
- Swagger UI: `/api/docs/swagger/`
- ReDoc: `/api/docs/redoc/`

---

## 📡 Credits SSE

- Endpoint: `GET /api/users/realtime/credits/` (`Content-Type: text/event-stream`)
- Auth: `Authorization: Bearer <JWT>` (IsAuthenticated)
- Events: `heartbeat` (periodic ping) and `credit_update` (payload with `balance` and `ledger`).
- Observability: `USERS_SSE_EVENTS_TOTAL{event,result}`; logs include `X-Request-ID`.

Example (`curl`):

```bash
curl -N \
  -H "Accept: text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Request-ID: sse-docs-demo-001" \
  http://localhost:8000/api/users/realtime/credits/
```

Example (`EventSource`):

```js
const es = new EventSource("/api/users/realtime/credits/");
es.addEventListener("credit_update", (e) => {
  const payload = JSON.parse(e.data);
  // update UI with payload.balance and payload.ledger
});
es.addEventListener("heartbeat", () => {
  // optional: show active connection
});
```

Notes:

- SSE headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`.
- On error, `USERS_SSE_EVENTS_TOTAL{event="error", result}` captures outcomes.

---

## 🗂️ Feature Flags

- Access to advanced features is controlled via `UserFeatureFlags`.
- Key fields: `is_pro`, `reports_enabled`.

---

## 🧑‍💻 Contributing

1. Create a branch from the GitHub issue:
   ```bash
   git checkout -b BE-XX-task-name
   ```
2. Implement and ensure tests + smoke pass.
3. Open a Pull Request linking the issue.
4. After review/merge, close the related issue.

---

## 📦 Deployment

- dev: local, SQLite
- uat: staging (PythonAnywhere, SQLite)
- prod: PostgreSQL (hosting TBD)

---

## 🏷️ MVP Focus

- JWT auth
- Appointments (CRUD + flow)
- Basic reports (overview, top services, revenue)
- CSV exports
- Stripe integration (subscriptions)

Major improvements (advanced cache, full observability, AI, etc.) are planned post-MVP.

---

## 🌱 Seed (demo data)

Creates users, professionals, services, slots and some appointments (idempotent):

```bash
make seed
# or
./scripts/seed.sh
```

**Tenants created:**

- `default` (Standard Plan)
- `basic-demo` (Basic Plan)
- `pro-demo` (Pro Plan, Custom Domain)
- `empty-credits` (Standard Plan, 0 credits)

**Credentials:**

- Admin: `admin@demo.local` / `admin`
- Pro User: `pro_smoke@demo.local` / `Smoke@123`
- Client: `client_smoke@demo.local` / `Smoke@123`

### 🚀 Mass seed (performance tests)

For large test data volumes:

---

## 🇧🇷 README em Português

### 🚀 Tecnologias principais

- Python 3.11+
- Django 5.x
- Django REST Framework
- drf-spectacular (OpenAPI 3)
- pytest
- SQLite / PostgreSQL (dependendo do ambiente)
- Integração com Stripe para assinaturas

### 📂 Estrutura do projeto

```
salonix-backend/
├── core/              # Agendamentos, serviços, horários, séries
├── users/             # Autenticação, tenants, staff, feature flags, SSE
├── payments/          # Assinaturas Stripe, checkout, webhooks
├── reports/           # Relatórios, cache, exportações
├── notifications/     # Notificações, devices, serviços, signals
├── ops/               # APIs Ops, métricas, permissões
├── salonix_backend/   # Configurações Django, middleware, admin, urls
├── docs/              # Documentação backend e runbooks
├── scripts/           # Seeds e scripts de smoke
├── tests/             # Testes cross-app
├── static/            # Assets do admin e DRF
├── requirements.txt
├── api-schema.yaml
├── manage.py
└── README.md
```

### ⚙️ Configuração

1. Clone o repositório:
   ```bash
   git clone https://github.com/<org>/salonix-backend.git
   cd salonix-backend
   ```
2. Crie o virtualenv:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Instale dependências:
   ```bash
   pip install -r requirements-dev.txt
   ```
4. Variáveis de ambiente (`.env` ou `settings.ini`):
   ```bash
   DJANGO_ENV=dev
   SECRET_KEY=...
   DEBUG=True
   DATABASE_URL=sqlite:///db.sqlite3
   STRIPE_SECRET_KEY=...
   STRIPE_WEBHOOK_SECRET=...
   USERS_AUTH_THROTTLE_LOGIN=10/min
   USERS_AUTH_THROTTLE_REGISTER=5/min
   USERS_TENANT_META_PUBLIC=60/min
   CAPTCHA_ENABLED=false
   CAPTCHA_PROVIDER=turnstile  # ou hcaptcha
   CAPTCHA_SECRET=
   CAPTCHA_BYPASS_TOKEN=
   ```
5. Migrações:
   ```bash
   python manage.py migrate
   ```
6. Superusuário:
   ```bash
   python manage.py createsuperuser
   ```

### 🧪 Testes

- Rodar a suíte completa:
  ```bash
  pytest
  ```
- Rodar apenas relatórios:
  ```bash
  pytest reports/tests/
  ```

### 🔒 Hardening Self-service (BE-212)

- Endpoints protegidos: `POST /api/users/register/`, `POST /api/users/token/` (throttle + captcha opcional) e `GET /api/users/tenant/meta/` (throttle público).
- Envs: `USERS_AUTH_THROTTLE_LOGIN`, `USERS_AUTH_THROTTLE_REGISTER`, `USERS_TENANT_META_PUBLIC`, `CAPTCHA_*`.
- Dev/Test: throttling alto por padrão; use `override_settings` para testar 429; bypass captcha via `X-Captcha-Token`.

### 🔑 Recuperação de Senha (BE-240)

- `POST /api/users/password/reset/` (resposta neutra `{"status":"ok"}`) e `POST /api/users/password/reset/confirm/` (uid + token + new_password).
- Throttle `users_password_reset`; captcha no request.
- Métrica: `users_password_reset_events_total{event,result}`.

### 🔍 Smoke tests

1. Suba o backend (`make run` ou `python manage.py runserver`).
2. Execute:
   ```bash
   make smoke
   ```

Credenciais seed:

- `pro_smoke@demo.local / Smoke@123`
- `client_smoke@demo.local / Smoke@123`
- `SMOKE_USER_PASSWORD=...` antes de `make seed` altera a senha padrão.

O script:

- Autentica como `pro_smoke`.
- Chama relatórios (`overview`, `top-services`, `revenue`) e exporta CSV.
- Valida throttling e métricas Prometheus.

### 💳 Stripe / Billing

- `.env`: `STRIPE_PRICE_*_MONTHLY_ID` e `STRIPE_TRIAL_DAYS` (opcional).
- URLs de retorno: `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`, `STRIPE_PORTAL_RETURN_URL`.
- Teste manual: `POST /api/payments/stripe/create-checkout-session/` com `plan`.

### 📖 Documentação da API

- `/api/schema/`, `/api/docs/swagger/`, `/api/docs/redoc/`.

### 📡 SSE de Créditos

- `GET /api/users/realtime/credits/` (`text/event-stream`), `Authorization: Bearer <JWT>`.
- Eventos: `heartbeat` e `credit_update` com `balance` e `ledger`.
- Observabilidade: `USERS_SSE_EVENTS_TOTAL{event,result}` e logs com `X-Request-ID`.

Exemplo `curl`:

```bash
curl -N \
  -H "Accept: text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Request-ID: sse-docs-demo-001" \
  http://localhost:8000/api/users/realtime/credits/
```

### 🗂️ Feature flags

- `UserFeatureFlags`: `is_pro`, `reports_enabled`.

### 🧑‍💻 Contribuição

1. Crie branch da issue:
   ```bash
   git checkout -b BE-XX-nome-da-tarefa
   ```
2. Garanta tests + smoke.
3. Abra PR vinculando à issue.
4. Após review/merge, feche a issue.

### 📦 Deployment

- dev: local (SQLite)
- uat: staging (PythonAnywhere, SQLite)
- prod: PostgreSQL (TBD)

### 🏷️ MVP Focus

- JWT, Agendamentos, Relatórios básicos, CSV, Stripe.

### 🌱 Seed (dados de demonstração)

```bash
make seed
# ou
./scripts/seed.sh
```

**Tenants criados:**

- `default` (Plano Standard)
- `basic-demo` (Plano Basic)
- `pro-demo` (Plano Pro, Domínio Personalizado)
- `empty-credits` (Plano Standard, 0 créditos)

**Credenciais:**

- Admin: `admin@demo.local` / `admin`
- Pro User: `pro_smoke@demo.local` / `Smoke@123`
- Client: `client_smoke@demo.local` / `Smoke@123`
