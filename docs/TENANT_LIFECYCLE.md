# Tenant Lifecycle (EN)

This document defines the lifecycle of a tenant (salon/organization) in Salonix Backend, describing states, transitions, and the main side effects such as staff ownership, feature flags, credits, domains, and emails.

## States

- Registered: Tenant exists, `is_active=true` by default.
- Active: Normal operation; features governed by `plan_tier` and flags on `Tenant`.
- Suspended: Ops/Admin set `is_active=false`; access and automations are blocked.
- Deleted: Hard delete via admin or GDPR; data removed. Archival is not implemented.

## Core Transitions

- Registration:
  - Creates `Tenant`, `CustomUser` (owner), and `TenantStaffMember(role=owner)`.
  - Endpoint: `POST /api/users/register/` (see `TENANT_REGISTRATION_FLOW.md`).
- Activation/Suspension:
  - Toggle `Tenant.is_active` via admin actions.
  - Staff members and professionals may be deactivated with `TenantStaffMember.status`.
- Configuration:
  - Branding: `logo`/`logo_url`, `favicon_url`, `app_name`.
  - Locale: `timezone`, `currency`.
  - Plans & flags: `plan_tier`, `addons_enabled`, modules (PWA, reports, RN apps), notification channels.
- Invitations:
  - Staff: `TenantStaffMember` with `status=invited`→`active` using invite token.
  - Client PWA invites: governed by `auto_invite_enabled` (sent on client creation events).
- Credits & Billing:
  - Communication credits in `Tenant.comm_credit_eur`; history tracked in `users.models.CommLedger`.
  - Extra credits and auto‑renew via `comm_extra_allowed` and `comm_auto_renew`.
- Domains & White‑label:
  - `custom_domain_enabled` and `custom_domain` for branded access (Pro+).

## Emails & Notifications

- Owner welcome/invite emails depend on email backend configuration.
- Staff invitations use `TenantStaffMember` invite workflow.
- PWA client invites handled by notifications service (placeholder implementation).
- See settings in `salonix_backend/settings.py` and docs in `NOTIFICATIONS_OVERVIEW.md`.

## Related Docs

- `TENANT_REGISTRATION_FLOW.md` — endpoint and email flow.
- `ARQUITETURA_SISTEMA.md` — multi‑tenancy, relationships, endpoints.
- `IMPLEMENTACOES_BACKEND.md` — feature flags, staff management.
- `OBSERVABILITY.md`, `ERROR_HANDLING.md` — health, logs, errors.

---

# Ciclo de Vida do Tenant (PT)

Este documento define o ciclo de vida de um tenant (salão/organização) no Backend do Salonix, cobrindo estados, transições e efeitos como propriedade de staff, flags, créditos, domínios e e‑mails.

## Estados

- Registrado: Tenant existe, `is_active=true` por padrão.
- Ativo: Operação normal; recursos conforme `plan_tier` e flags em `Tenant`.
- Suspenso: Ops/Admin definem `is_active=false`; acesso e automações bloqueados.
- Deletado: Exclusão definitiva via admin ou GDPR; dados removidos. Arquivamento não implementado.

## Transições Principais

- Registro:
  - Cria `Tenant`, `CustomUser` (owner) e `TenantStaffMember(role=owner)`.
  - Endpoint: `POST /api/users/register/` (ver `TENANT_REGISTRATION_FLOW.md`).
- Ativação/Suspensão:
  - Alternar `Tenant.is_active` via ações de admin.
  - Membros de equipe e profissionais podem ser desativados com `TenantStaffMember.status`.
- Configuração:
  - Branding: `logo`/`logo_url`, `favicon_url`, `app_name`.
  - Localização: `timezone`, `currency`.
  - Planos & flags: `plan_tier`, `addons_enabled`, módulos (PWA, relatórios, apps RN), canais de notificação.
- Convites:
  - Staff: `TenantStaffMember` com `status=invited`→`active` via token de convite.
  - Convites PWA de cliente: controlados por `auto_invite_enabled` (enviados em eventos de criação de cliente).
- Créditos & Cobrança:
  - Créditos de comunicação em `Tenant.comm_credit_eur`; histórico em `users.models.CommLedger`.
  - Créditos avulsos e renovação automática via `comm_extra_allowed` e `comm_auto_renew`.
- Domínios & White‑label:
  - `custom_domain_enabled` e `custom_domain` para acesso com domínio próprio (Pro+).

## E‑mails & Notificações

- E‑mail de boas‑vindas/convite do owner depende da configuração do backend de e‑mail.
- Convites de staff usam o fluxo com token em `TenantStaffMember`.
- Convites PWA do cliente são tratados pelo serviço de notificações (implementação placeholder).
- Ver configurações em `salonix_backend/settings.py` e docs em `NOTIFICATIONS_OVERVIEW.md`.

## Documentos Relacionados

- `TENANT_REGISTRATION_FLOW.md` — endpoint e fluxo de e‑mail.
- `ARQUITETURA_SISTEMA.md` — multi‑tenancy, relações, endpoints.
- `IMPLEMENTACOES_BACKEND.md` — feature flags, gestão de staff.
- `OBSERVABILITY.md`, `ERROR_HANDLING.md` — saúde, logs, erros.