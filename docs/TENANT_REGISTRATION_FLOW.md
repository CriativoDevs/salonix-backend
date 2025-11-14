# Tenant Registration Flow (EN)

This document describes the self‑service tenant registration endpoint, side effects (owner/staff creation), and email sending requirements.

## Endpoint

- URL: `POST /api/users/register/`
- Purpose: Create a new `Tenant`, an owner `CustomUser`, and a `TenantStaffMember(role=owner)`.
- Typical Payload (example):
  ```json
  {
    "salon_name": "Your Salon",
    "owner_email": "owner@example.com",
    "owner_password": "S3cureP@ss",
    "timezone": "Europe/Lisbon",
    "currency": "EUR"
  }
  ```
- Response: 201 with created resources (user minimal data), or 400 with validation errors.

## Side Effects

- Tenant created with defaults (`plan_tier=basic`, flags off except `pwa_admin_enabled`).
- Owner user created and linked via `CustomUser.tenant`.
- Staff ownership: `TenantStaffMember(role=owner, status=active)` created.

## Emails

- Welcome/confirmation emails depend on `EMAIL_BACKEND` configuration.
- Staff invites are separate flows using `TenantStaffMember` invite token.
- Client PWA invites are triggered by customer creation events when `Tenant.auto_invite_enabled=true`.

## Email Backend & ENV

Set the following in environment for production sending:

- `EMAIL_BACKEND` (e.g., `django.core.mail.backends.smtp.EmailBackend`)
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS` or `EMAIL_USE_SSL`
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
- `DEFAULT_FROM_EMAIL`

For development:

- Use `django.core.mail.backends.console.EmailBackend` or `locmem.EmailBackend`.
- See `salonix_backend/settings.py` for how env vars are read.

## Implementation References

- Models: `users/models.py` (`Tenant`, `CustomUser`, `TenantStaffMember`).
- Email utils: `core/email_utils.py` (examples like appointment confirmations).
- Notifications: `notifications/services.py` (PWA invite placeholder).
- Password reset: flows in `users/views.py`.

## Observability & Errors

- Logs/metrics: `OBSERVABILITY.md`.
- Error codes and DRF integration: `ERROR_HANDLING.md`.

---

# Fluxo de Cadastro do Tenant (PT)

Este documento descreve o endpoint de registro self‑service de tenant, efeitos colaterais (criação de owner/staff) e requisitos de envio de e‑mails.

## Endpoint

- URL: `POST /api/users/register/`
- Objetivo: Criar um `Tenant`, um `CustomUser` owner e `TenantStaffMember(role=owner)`.
- Payload típico (exemplo):
  ```json
  {
    "salon_name": "Seu Salão",
    "owner_email": "owner@example.com",
    "owner_password": "S3cureP@ss",
    "timezone": "Europe/Lisbon",
    "currency": "EUR"
  }
  ```
- Resposta: 201 com recursos criados (dados mínimos de usuário), ou 400 com erros de validação.

## Efeitos Colaterais

- Tenant criado com padrões (`plan_tier=basic`, flags off exceto `pwa_admin_enabled`).
- Owner criado e vinculado via `CustomUser.tenant`.
- Propriedade: `TenantStaffMember(role=owner, status=active)` criado.

## E‑mails

- E‑mails de boas‑vindas/confirmação dependem da configuração de `EMAIL_BACKEND`.
- Convites de staff são fluxos separados usando token de convite em `TenantStaffMember`.
- Convites PWA de cliente são disparados em eventos de criação de cliente quando `Tenant.auto_invite_enabled=true`.

## Backend de E‑mail & ENV

Defina no ambiente para envio em produção:

- `EMAIL_BACKEND` (ex.: `django.core.mail.backends.smtp.EmailBackend`)
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS` ou `EMAIL_USE_SSL`
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
- `DEFAULT_FROM_EMAIL`

Para desenvolvimento:

- Use `django.core.mail.backends.console.EmailBackend` ou `locmem.EmailBackend`.
- Veja `salonix_backend/settings.py` para leitura das variáveis.

## Referências de Implementação

- Modelos: `users/models.py` (`Tenant`, `CustomUser`, `TenantStaffMember`).
- Utilitários de e‑mail: `core/email_utils.py` (ex.: confirmações de agendamento).
- Notificações: `notifications/services.py` (placeholder de convite PWA).
- Reset de senha: fluxos em `users/views.py`.

## Observabilidade & Erros

- Logs/métricas: `OBSERVABILITY.md`.
- Códigos de erro e integração com DRF: `ERROR_HANDLING.md`.