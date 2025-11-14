# Testing Guide (EN)

This guide explains how to run and write tests for Salonix Backend, covering unit, integration, and API tests with multi‑tenant considerations.

## Run Tests

- All tests: `python -m pytest`
- Django test runner: `python manage.py test` (alternative)
- Coverage (optional): `pytest --cov=.`

## Environment

- Use `.env.test` with safe defaults.
- Email backend for tests: `django.core.mail.backends.locmem.EmailBackend`.
- DB: sqlite or Postgres; ensure migrations applied in CI.

## Patterns

- Factories/fixtures for `Tenant`, `CustomUser`, `TenantStaffMember`.
- API tests with DRF `APIClient` and tenant scoping.
- Cache‑aware tests for reports and throttling.
- Error handling: assert standardized error codes from `ERROR_HANDLING.md`.

## Examples

- Tenant lifecycle:
  - Create tenant via registration endpoint.
  - Assert owner staff member exists and `is_active` toggles.
  - Validate feature flags dict from `Tenant.get_feature_flags_dict()`.
- Emails:
  - Use locmem backend; assert outbox length and contents.
  - Staff invite: generate token, hit accept endpoint, assert status changes.
- Reports:
  - Seed sample data; hit CSV export; assert content type and row counts.

## CI Recommendations

- Run specific apps first (users/core), then full suite.
- Fail fast on migration or schema drift.
- Emit minimal metrics/logs; avoid external network.

## Related Docs

- `ARQUITETURA_SISTEMA.md` — test strategy notes.
- `IMPLEMENTACOES_BACKEND.md` — modules with tests.
- `ERROR_HANDLING.md` — error shape and codes.
- `OBSERVABILITY.md` — logs in tests.

---

# Guia de Testes (PT)

Este guia explica como executar e escrever testes no Backend do Salonix, cobrindo unitários, integração e APIs com foco em multi‑tenant.

## Executar Testes

- Todos: `python -m pytest`
- Runner Django: `python manage.py test` (alternativo)
- Cobertura (opcional): `pytest --cov=.`

## Ambiente

- Use `.env.test` com defaults seguros.
- Backend de e‑mail para testes: `django.core.mail.backends.locmem.EmailBackend`.
- BD: sqlite ou Postgres; garanta migrações aplicadas no CI.

## Padrões

- Factories/fixtures para `Tenant`, `CustomUser`, `TenantStaffMember`.
- Testes de API com DRF `APIClient` e escopo de tenant.
- Testes sensíveis a cache para relatórios e throttling.
- Tratamento de erros: valide códigos padronizados de `ERROR_HANDLING.md`.

## Exemplos

- Ciclo de vida do tenant:
  - Crie tenant via endpoint de registro.
  - Verifique owner e `is_active` alternando.
  - Valide o dicionário de flags via `Tenant.get_feature_flags_dict()`.
- E‑mails:
  - Use locmem; valide tamanho do outbox e conteúdo.
  - Convite de staff: gere token, aceite convite, verifique mudança de status.
- Relatórios:
  - Seed de dados; exporte CSV; valide content type e contagem de linhas.

## Recomendações de CI

- Rode apps específicas primeiro (users/core), depois a suíte completa.
- Falhe rápido em migração ou drift de schema.
- Emita métricas/logs mínimos; evite rede externa.

## Documentos Relacionados

- `ARQUITETURA_SISTEMA.md` — notas de estratégia de testes.
- `IMPLEMENTACOES_BACKEND.md` — módulos com testes.
- `ERROR_HANDLING.md` — formato e códigos de erro.
- `OBSERVABILITY.md` — logs em testes.