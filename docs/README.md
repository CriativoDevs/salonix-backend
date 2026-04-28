# 📚 Salonix Backend Documentation

This directory centralizes backend documentation for both technical and non‑technical audiences. English comes first; Portuguese follows below.

## 📋 Documentation Index (EN)

- Strategy: `ESTRATEGIA_DESENVOLVIMENTO.md`, `MVP_STATUS_ATUAL.md`, `BE_BUSINESS_BRIEF.md`.
- Architecture & Implementation: `ARQUITETURA_SISTEMA.md`, `IMPLEMENTACOES_BACKEND.md`.
- API & Schema: `API_OPENAPI.md`.
- Tenancy: `TENANT_LIFECYCLE.md`, `TENANT_REGISTRATION_FLOW.md`.
- Validation & Errors: `VALIDATION_SYSTEM.md`, `../ERROR_HANDLING.md`.
- Security: `CAPTCHA_SYSTEM.md`, `SENSITIVE_ENDPOINTS_INVENTORY.md`.
- Observability & Notifications: `OBSERVABILITY.md`, `NOTIFICATIONS_OVERVIEW.md`.
- Reports: `REPORTS_OVERVIEW.md`.
- Tutorials & Operations: `TUTORIAL_DJANGO_ADMIN.md`, `OPS_RUNBOOK.md`.
- Payments (Stripe): `PAGAMENTOS_STRIPE.md`.
- Seeds: `../SEED_DATA_CREDITS.md`.
- Testing: `TESTING_GUIDE.md`.

## 🚀 Quick Start (Non‑Technical)

- Admin URL: `http://0.0.0.0:8000/admin/`.
- Log in with the admin credentials provided by your team.
- Create a tenant, invite staff, and configure branding using `TUTORIAL_DJANGO_ADMIN.md`.

## 🛠️ Quick Start (Developers)

- Run dev server: `python manage.py runserver 0.0.0.0:8000`.
- Run tests: `python -m pytest`.
- Bootstrap admin: `python manage.py setup_admin`.
- API docs (Swagger): `http://0.0.0.0:8000/api/schema/swagger-ui/`.

## 🔍 Find Topics Fast

- Multi‑tenancy: `IMPLEMENTACOES_BACKEND.md#1-infraestrutura-base` and `ARQUITETURA_SISTEMA.md#multi-tenancy-first`.
- Staff management: `IMPLEMENTACOES_BACKEND.md#gestão-de-staff-por-tenant-be-282` and `TUTORIAL_DJANGO_ADMIN.md#gestão-de-staff-convites-e-profissionais`.
- White‑label: `IMPLEMENTACOES_BACKEND.md#2-white-label-e-branding` and `TUTORIAL_DJANGO_ADMIN.md#configurando-white-label`.
- Reports: `IMPLEMENTACOES_BACKEND.md#4-sistema-de-relatórios` and `ARQUITETURA_SISTEMA.md#sistema-de-cache`.
- Notifications & Observability: `IMPLEMENTACOES_BACKEND.md#5-sistema-de-notificações` and `ARQUITETURA_SISTEMA.md#monitoramento-e-observabilidade`.
- Tests: `TESTING_GUIDE.md`, `IMPLEMENTACOES_BACKEND.md#sistema-de-testes`, `ARQUITETURA_SISTEMA.md#estratégia-de-testes`.

## 📊 Project Status (MVP)

- Delivered: self‑service auth/registration per tenant, cached reports, hardening (scoped throttling, captcha switch, structured logs), password recovery with metrics.
- Next steps: captcha validation (BE‑212), transactional emails (BE‑240), Stripe live, prod‑like infra (Postgres/Redis/HTTPS/CORS/Secrets/Observability), updated OpenAPI and end‑to‑end smokes.

## 🔗 Useful Links

- Admin: `http://0.0.0.0:8000/admin/`.
- API root: `http://0.0.0.0:8000/api/`.
- Swagger UI: `http://0.0.0.0:8000/api/schema/swagger-ui/`.
- Key files: `salonix_backend/settings.py`, `salonix_backend/urls.py`, `users/models.py`, `core/models.py`, `salonix_backend/admin.py`.

## 📝 Contributing

- Read `ARQUITETURA_SISTEMA.md`.
- Ensure tests pass and update relevant docs.
- Open PRs with clear descriptions.

---

## 🇧🇷 Documentação (PT)

Esta pasta centraliza toda a documentação do backend para públicos técnicos e não técnicos. Inglês acima; português abaixo.

### 📋 Índice

- Estratégia: `ESTRATEGIA_DESENVOLVIMENTO.md`, `MVP_STATUS_ATUAL.md`, `BE_BUSINESS_BRIEF.md`.
- Arquitetura & Implementação: `ARQUITETURA_SISTEMA.md`, `IMPLEMENTACOES_BACKEND.md`.
- API & Schema: `API_OPENAPI.md`.
- Multi‑tenancy: `TENANT_LIFECYCLE.md`, `TENANT_REGISTRATION_FLOW.md`.
- Validação & Erros: `VALIDATION_SYSTEM.md`, `../ERROR_HANDLING.md`.
- Observabilidade & Notificações: `OBSERVABILITY.md`, `NOTIFICATIONS_OVERVIEW.md`.
- Segurança: `CAPTCHA_SYSTEM.md`, `SENSITIVE_ENDPOINTS_INVENTORY.md`.
- Relatórios: `REPORTS_OVERVIEW.md`.
- Tutoriais & Operações: `TUTORIAL_DJANGO_ADMIN.md`, `OPS_RUNBOOK.md`.
- Pagamentos (Stripe): `PAGAMENTOS_STRIPE.md`.
- Seeds: `../SEED_DATA_CREDITS.md`.
- Testes: `TESTING_GUIDE.md`.

### 🚀 Início Rápido (Não Técnicos)

- Admin: `http://0.0.0.0:8000/admin/`.
- Entre com as credenciais de admin fornecidas pela equipe.
- Crie o tenant, convide a equipe e ajuste o branding em `TUTORIAL_DJANGO_ADMIN.md`.

### 🛠️ Início Rápido (Desenvolvedores)

- Servidor: `python manage.py runserver 0.0.0.0:8000`.
- Testes: `python -m pytest`.
- Admin seed: `python manage.py setup_admin`.
- API docs: `http://0.0.0.0:8000/api/schema/swagger-ui/`.

### 🔍 Encontre por Tema

- Multi‑tenancy: `IMPLEMENTACOES_BACKEND.md#1-infraestrutura-base` e `ARQUITETURA_SISTEMA.md#multi-tenancy-first`.
- Gestão de staff: `IMPLEMENTACOES_BACKEND.md#gestão-de-staff-por-tenant-be-282` e `TUTORIAL_DJANGO_ADMIN.md#gestão-de-staff-convites-e-profissionais`.
- White‑label: `IMPLEMENTACOES_BACKEND.md#2-white-label-e-branding` e `TUTORIAL_DJANGO_ADMIN.md#configurando-white-label`.
- Relatórios: `IMPLEMENTACOES_BACKEND.md#4-sistema-de-relatórios` e `ARQUITETURA_SISTEMA.md#sistema-de-cache`.
- Notificações & Observabilidade: `IMPLEMENTACOES_BACKEND.md#5-sistema-de-notificações` e `ARQUITETURA_SISTEMA.md#monitoramento-e-observabilidade`.
- Testes: `TESTING_GUIDE.md`, `IMPLEMENTACOES_BACKEND.md#sistema-de-testes`, `ARQUITETURA_SISTEMA.md#estratégia-de-testes`.

### 📊 Status do Projeto (MVP)

- Entregues: autenticação/registro por tenant, relatórios com cache, hardening (throttling por escopo, captcha switch, logs estruturados), recuperação de senha com métricas.
- Próximos: validação de captcha (BE‑212), e‑mails transacionais (BE‑240), Stripe live, infra prod‑like, OpenAPI atualizado e smokes e2e.

### 🔗 Links Úteis

- Admin: `http://0.0.0.0:8000/admin/`.
- API: `http://0.0.0.0:8000/api/`.
- Swagger UI: `http://0.0.0.0:8000/api/schema/swagger-ui/`.
- Arquivos chave: `salonix_backend/settings.py`, `salonix_backend/urls.py`, `users/models.py`, `core/models.py`, `salonix_backend/admin.py`.

### 📝 Contribuição

- Leia `ARQUITETURA_SISTEMA.md`.
- Garanta testes passando e atualize docs.
- Abra PRs com descrição clara.

---

Documentação mantida pela equipe Salonix — Última atualização: 11 Setembro 2025
