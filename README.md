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

## 🔍 Smoke tests

- Para validar endpoints críticos de relatórios, use:
    ```bash
    ./scripts/smoke_reports.sh
    ```

- Credenciais seedadas:
    - `pro_smoke@demo.local / Smoke@123`
    - `client_smoke@demo.local / Smoke@123`
    - Defina `SMOKE_USER_PASSWORD=...` antes de `make seed` para alterar a senha padrão usada pelos smokes.

---

### Esse script:

- autentica como usuário de smoke (pro_smoke);
- chama /api/reports/overview/, /top-services/, /revenue/;
- valida que retornam 200 OK.


## ⚠️ Certifique-se de ter rodado o comando de seed para popular dados de teste.

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
