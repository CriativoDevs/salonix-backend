# Salonix Backend

Backend do **Salonix**, sistema de agendamento para salões, desenvolvido em **Django REST Framework**.

Este repositório cobre a API que suporta o frontend web (React) e o mobile (Expo/React Native).

---

## 🚀 Tecnologias principais

- [Python 3.11+](https://www.python.org/)
- [Django 5.x](https://www.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [drf-spectacular](https://drf-spectacular.readthedocs.io/) (OpenAPI 3)
- [pytest](https://docs.pytest.org/)
- [SQLite / PostgreSQL](https://www.postgresql.org/) (dependendo do ambiente)
- Integração com Stripe para assinaturas

---

## 📂 Estrutura do projeto
```
salonix-backend/
│
├── core/              # Agendamentos, serviços, salões
├── payments/          # Assinaturas (Stripe)
├── reports/           # Relatórios e exportações
├── users/             # Autenticação, usuários, feature flags
│
├── salonix_backend/   # Configurações Django
├── scripts/           # Ferramentas auxiliares (smoke tests, seeds)
├── pytest.ini         # Configuração de testes
└── README.md
```

---

## ⚙️ Configuração

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
   pip install -r requirements.txt
   ```

4.	Configure variáveis de ambiente (.env ou settings.ini):
    ```bash
    DJANGO_ENV=dev
    SECRET_KEY=...
    DEBUG=True
    DATABASE_URL=sqlite:///db.sqlite3
    STRIPE_SECRET_KEY=...
    STRIPE_WEBHOOK_SECRET=...
    # Throttling (produção; em dev/test já vem alto por padrão)
    USERS_AUTH_THROTTLE_LOGIN=10/min
    USERS_AUTH_THROTTLE_REGISTER=5/min
    USERS_TENANT_META_PUBLIC=60/min
    # Captcha (self-service)
    CAPTCHA_ENABLED=false
    CAPTCHA_PROVIDER=turnstile  # ou hcaptcha
    CAPTCHA_SECRET=
    CAPTCHA_BYPASS_TOKEN=       # ex.: dev-bypass (enviar em X-Captcha-Token)
    ```

5. Rode migrações:
   ```bash
   python manage.py migrate
   ```

6. Crie um superusuário:
    ```bash
    python manage.py createsuperuser
    ```

---
## 🧪 Testes

- Rodar toda a suíte de testes:
    ```bash
    pytest
    ```
- Rodar apenas os testes de relatórios:
    ```bash
    pytest reports/tests/
    ```
---
## 🔑 Recuperação de Senha (BE-240)

- Endpoints:
  - POST `/api/users/password/reset/` – solicita reset; resposta neutra `{"status":"ok"}`.
  - POST `/api/users/password/reset/confirm/` – confirma com `uid` + `token` + `new_password`.
- Segurança:
  - Throttle `users_password_reset` (configurável por env; alto em dev/test).
  - Captcha aplicado na solicitação (usa `CAPTCHA_*`).
- E-mail:
  - Envia link de reset usando `reset_url` informado pelo cliente: `{reset_url}?uid={uid}&token={token}`.
- Métricas:
  - `users_password_reset_events_total{event=request|confirm, result=success|failure}`.

## 🔒 Hardening Self-service (BE-212)

- Endpoints protegidos:
  - POST `/api/users/register/` e `/api/users/token/` com throttling por IP/usuário e captcha opcional.
  - GET `/api/users/tenant/meta/` com throttling público.
- Envs relevantes:
  - `USERS_AUTH_THROTTLE_LOGIN`, `USERS_AUTH_THROTTLE_REGISTER`, `USERS_TENANT_META_PUBLIC`.
  - `CAPTCHA_ENABLED`, `CAPTCHA_PROVIDER=turnstile|hcaptcha`, `CAPTCHA_SECRET`, `CAPTCHA_BYPASS_TOKEN`.
- Dev/Test:
  - Defaults de throttling são altos para não interferir; use `override_settings` para testar 429.
  - Para testar captcha sem rede, defina `CAPTCHA_BYPASS_TOKEN` e envie `X-Captcha-Token`.

---

## 🔍 Smoke tests

1. Em um terminal, suba o backend (`make run` ou `python manage.py runserver`).
2. Em outro terminal execute:
    ```bash
    make smoke        # wrapper que chama ./scripts/smoke_reports.sh
    ```

- Credenciais seedadas:
    - `pro_smoke@demo.local / Smoke@123`
    - `client_smoke@demo.local / Smoke@123`
    - Defina `SMOKE_USER_PASSWORD=...` antes de `make seed` para alterar a senha padrão usada pelos smokes.

### O script faz o quê?

- autentica como usuário de smoke (`pro_smoke`);
- chama `/api/reports/overview/`, `/top-services/`, `/revenue/` e exports CSV com backoff;
- valida throttling e métricas Prometheus.

> ⚠️ Certifique-se de ter rodado `make seed` para popular dados de teste antes de executar o smoke.

---

## 💳 Stripe / Billing

- Configure os preços mensais dos planos via `.env`:
    - `STRIPE_PRICE_BASIC_MONTHLY_ID`
    - `STRIPE_PRICE_STANDARD_MONTHLY_ID`
    - `STRIPE_PRICE_PRO_MONTHLY_ID`
    - `STRIPE_PRICE_ENTERPRISE_MONTHLY_ID`
- (Opcional) `STRIPE_TRIAL_DAYS` controla o período trial aplicado no checkout (default: 14 dias).
- URLs de retorno (`STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`, `STRIPE_PORTAL_RETURN_URL`) podem apontar para o FE.
- Para testar billing manualmente, chame `/api/payments/stripe/create-checkout-session/` com `plan="basic|standard|pro|enterprise"` e confirme os redirecionamentos do Stripe.

⸻

## 📖 Documentação da API

A API segue OpenAPI 3, gerado pelo drf-spectacular.
- Esquema cru: /api/schema/
- Swagger UI: /api/docs/swagger/
- ReDoc: /api/docs/redoc/

⸻

## 🗂️ Feature flags

O acesso a relatórios e recursos avançados é controlado via UserFeatureFlags.
Campos principais:
- is_pro: usuário em plano pago
- reports_enabled: habilitação de relatórios

---

## 🧑‍💻 Contribuição

Fluxo padrão:
1.	Crie uma branch a partir da issue do GitHub:
    ```bash
    git checkout -b BE-XX-nome-da-tarefa
    ```
2.	Implemente e garanta que tests + smoke passem.
3.	Abra um Pull Request vinculando à issue.
4.	Após review/merge, feche a issue correspondente.

---

## 📦 Deployment

Ambientes:
- dev: local, SQLite
- uat: staging em PythonAnywhere (SQLite)
- prod: PostgreSQL (hospedagem TBD)

---

## 🏷️ MVP Focus

O projeto está em fase de MVP, priorizando:
- Autenticação JWT
- Agendamentos (CRUD + fluxo)
- Relatórios básicos (overview, top services, revenue)
- Exportações CSV
- Integração Stripe (assinaturas)

Melhorias maiores (ex.: cache avançado, observabilidade full, IA, etc.) serão consideradas após entrega do MVP.

---

# README.md (patch mínimo para Smoke)

Sugestão de ajuste na sua seção “🔍 Smoke tests” para usar o Make:

 ## 🔍 Smoke tests
```diff

-- Para validar endpoints críticos de relatórios, use:
-    ```bash
-    ./scripts/smoke_reports.sh
-    ```
+- Para validar endpoints críticos de relatórios:
+    ```bash
+    make smoke
+    ```
+
+Ou diretamente pelo script:
+```bash
+./scripts/smoke_reports.sh
```

---

## 🌱 Seed (dados de demonstração)

Cria usuários, profissionais, serviços, slots e alguns agendamentos (idempotente):

```bash
make seed        # roda o management command seed_demo
# ou
./scripts/seed.sh
```

### 🚀 Seed em massa (para testes de performance)

Para gerar grandes volumes de dados de teste:

```bash
make seed-mass   # gera dados padrão (1000 agendamentos)
```

Ou com parâmetros customizados:

```bash
make seed-mass APPOINTMENTS=10000 CUSTOMERS=2000 PROFESSIONALS=50 SERVICES=100
```

**Parâmetros disponíveis:**
- `APPOINTMENTS`: número de agendamentos (padrão: 1000)
- `CUSTOMERS`: número de clientes (padrão: 200)
- `PROFESSIONALS`: número de profissionais (padrão: 10)
- `SERVICES`: número de serviços (padrão: 20)
- `DAYS_BACK`: dias no passado para gerar dados (padrão: 365)
- `BATCH_SIZE`: tamanho do lote para inserções (padrão: 1000)

**Exemplo de uso para teste de performance:**
```bash
# Gerar 50k agendamentos para teste de stress
make seed-mass APPOINTMENTS=50000 CUSTOMERS=10000 PROFESSIONALS=100 SERVICES=200

# Testar exportação CSV com dados grandes
curl 'http://localhost:8000/api/appointments/export_csv/' -H 'Authorization: Bearer <token>'
```

> ⚠️ **Atenção**: O comando seed-mass pode demorar vários minutos para grandes volumes. Use com moderação em desenvolvimento.

---

### 🔥 Smoke de cache dos relatórios

Este script cria **1 appointment** como `client_smoke` e verifica se o endpoint
`/api/reports/top-services/` muda **antes vs. depois**, provando que os
*sinais* invalidam o cache dos relatórios corretamente.

Pré-requisitos:
- `make run` ativo em `http://localhost:8000`
- `make seed` já executado (para dados de demonstração)
- `curl` e `jq` instalados

Rodar:
```bash
make smoke-cache
```
