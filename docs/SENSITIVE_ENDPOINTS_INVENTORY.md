# Sensitive Endpoints Inventory

This document is the initial inventory for issue BE-SEC-04 and identifies the backend routes that require stricter OWASP API Top 10 and ASVS review.

Status
- Date: 2026-04-28
- Scope: backend HTTP endpoints
- Source of truth used for this inventory: `salonix_backend/urls.py`, `core/urls.py`, `users/urls.py`, `payments/urls.py`, `ops/urls.py`, `notifications/urls.py`
- Goal of this phase: identify sensitive surfaces before authorization, abuse-control, and header reviews

## Review Criteria

An endpoint is treated as sensitive when at least one of the following applies:
- handles authentication, password reset, tokens, session bootstrap, or access links
- returns or mutates personal data, staff data, customer data, or tenant metadata
- exposes billing, credits, payment history, subscriptions, or Stripe configuration
- changes tenant configuration, notification settings, or module flags
- is privileged for OPS/admin workflows or exposes audit/support data
- supports bulk import, bulk export, or other high-volume data extraction paths

## Inventory By Domain

### 1. Authentication and Account Recovery

Primary prefixes
- `/api/users/`
- `/api/ops/auth/`
- `/api/clients/` and `/api/public/clients/`

Routes to review
- `/api/users/register/`
- `/api/users/token/`
- `/api/users/token/refresh/`
- `/api/users/password/reset/`
- `/api/users/password/reset/confirm/`
- `/api/ops/auth/login/`
- `/api/ops/auth/refresh/`
- `/api/ops/auth/me/`
- `/api/clients/access-link/`
- `/api/clients/access-accept/`
- `/api/clients/login/`
- `/api/clients/token/refresh/`
- `/api/clients/set-password/`
- `/api/public/clients/access-link/`

Why sensitive
- token issuance and refresh
- password recovery and account takeover risk
- client and OPS access bootstrap flows
- brute force, credential stuffing, and enumeration exposure

Observed guardrails in code
- `users/views.py` applies dedicated throttles to register, login, tenant meta public access, and password reset flows
- `ops/views.py` applies dedicated throttles to OPS login and refresh

### 2. Personal Data, Staff, and Customer Data

Primary prefixes
- `/api/users/`
- `/api/`

Routes to review
- `/api/users/me/profile/`
- `/api/users/me/tenant/`
- `/api/users/staff/`
- `/api/users/staff/resend/`
- `/api/users/staff/access-link/`
- `/api/users/staff/contact/`
- `/api/users/staff/accept/`
- `/api/users/tenant/profile/`
- `/api/users/tenant/meta/`
- `/api/salon/customers/`
- `/api/clients/me/profile/`
- `/api/clients/me/appointments/upcoming/`
- `/api/clients/me/appointments/history/`
- `/api/clients/me/appointments/`
- `/api/clients/me/appointments/<id>/cancel/`
- `/api/me/appointments/`
- `/api/appointments/<id>/`
- `/api/appointments/<id>/cancel/`
- `/api/appointments/series/`
- `/api/appointments/series/<id>/`
- `/api/appointments/series/<series_id>/occurrence/<occurrence_id>/cancel/`

Why sensitive
- personal data and staff contact data
- tenant-linked customer records and appointment history
- object-level authorization risk across tenant boundaries
- staff invitation and access-link flows can leak account bootstrap data

Observed guardrails in code
- many authenticated user views in `users/views.py` require `IsAuthenticated`
- several mobile-facing authenticated views also require `RequiresMobileAccess`

### 3. Billing, Credits, and Stripe

Primary prefixes
- `/api/payments/stripe/`
- `/api/users/credits/`

Routes to review
- `/api/payments/stripe/create-checkout-session/`
- `/api/payments/stripe/billing-portal/`
- `/api/payments/stripe/webhook/`
- `/api/payments/stripe/webhooks/stripe/`
- `/api/payments/stripe/credits/packages/`
- `/api/payments/stripe/credits/purchase/`
- `/api/payments/stripe/credits/checkout/`
- `/api/payments/stripe/plans/`
- `/api/payments/stripe/subscription/current/`
- `/api/payments/stripe/subscription/action/`
- `/api/payments/stripe/history/`
- `/api/payments/stripe/overview/`
- `/api/payments/stripe/settings/`
- `/api/payments/stripe/v2/checkout/`
- `/api/payments/stripe/v2/portal/`
- `/api/users/credits/balance/`
- `/api/users/credits/history/`
- `/api/users/credits/consume/`
- `/api/users/credits/purchase/`
- `/api/users/realtime/credits/`

Why sensitive
- billing state, subscription lifecycle, payment records, and credit balances
- outbound payment actions and customer portal bootstrap
- webhook ingestion from external provider
- risk of tenant data disclosure and billing abuse

Observed guardrails in code
- most payment views use `IsAuthenticated`
- Stripe webhook endpoints are intentionally `AllowAny` and must rely on signature validation and replay protection

### 4. Tenant Configuration and Lifecycle

Primary prefixes
- `/api/users/tenant/`
- `/api/tenants/`
- `/api/notifications/`
- `/api/ops/global-settings/`

Routes to review
- `/api/users/tenant/meta/`
- `/api/users/tenant/profile/`
- `/api/users/tenant/notifications/`
- `/api/users/tenant/modules/`
- `/api/tenants/cancel-account/`
- `/api/tenants/reactivate/`
- `/api/notifications/consent/`
- `/api/notifications/consent/create/`
- `/api/notifications/consent/withdraw/`
- `/api/ops/global-settings/`

Why sensitive
- changes tenant-visible behavior, branding, modules, lifecycle, or communication preferences
- affects compliance, entitlements, and data-retention expectations
- requires strong tenant scoping and privileged-write controls

### 5. OPS and Privileged Administrative Surfaces

Primary prefix
- `/api/ops/`

Routes to review
- `/api/ops/tenants/`
- `/api/ops/users/`
- `/api/ops/support/`
- `/api/ops/lockouts/`
- `/api/ops/audit-logs/`
- `/api/ops/global-settings/`
- `/api/ops/notification-templates/`
- `/api/ops/alerts/`
- `/api/ops/metrics/overview/`

Why sensitive
- global or cross-tenant operational visibility
- privileged mutations on tenants and users
- support tooling and audit trails often expose sensitive fields even on read-only actions

Observed guardrails in code
- `ops/views.py` uses `IsOpsSupportOrAdmin` and `IsOpsAdmin` on privileged routes
- these endpoints still require explicit object scoping review and output minimization review

### 6. Import, Export, Feedback, and High-Volume Data Movement

Primary prefixes
- `/api/import/`
- `/api/export/`
- `/api/feedbacks/`

Routes to review
- `/api/import/customers/`
- `/api/import/services/`
- `/api/import/staff/`
- `/api/import/appointments/`
- `/api/import/templates/<entity>.csv`
- `/api/export/customers.csv`
- `/api/export/services.csv`
- `/api/export/staff.csv`
- `/api/feedbacks/`
- `/api/feedbacks/<id>/`
- `/api/feedbacks/export/`
- `/api/feedbacks/purge/<customer_id>/`
- `/api/feedbacks/retention/enforce/`

Why sensitive
- bulk ingestion and extraction of tenant-linked records
- CSV attack surface, oversized payloads, and mass disclosure risk
- retention and purge actions can remove regulated data

### 7. Notification Logs, Devices, and Communication Data

Primary prefix
- `/api/notifications/`

Routes to review
- `/api/notifications/`
- `/api/notifications/<id>/read/`
- `/api/notifications/mark-all-read/`
- `/api/notifications/stats/`
- `/api/notifications/register_device/`
- `/api/notifications/test/`
- `/api/notifications/test-push/`
- `/api/notifications/logs/`

Why sensitive
- device registration data
- notification logs and communication metadata
- test endpoints can become abuse pivots if not tightly restricted

## Public But Security-Relevant Routes

These routes are public or semi-public and must be included in abuse and information-disclosure review even when they are not full sensitive-data endpoints.

- `/api/public/unsubscribe`
- `/api/users/captcha/new/`
- `/api/users/founder-availability/`
- `/api/public/services/`
- `/api/public/professionals/`
- `/api/public/slots/`
- `/api/public/tenants/<slug>/`
- `/api/public/appointments/<id>/ics/`

## Initial Review Priorities

Priority 1
- authentication, reset, refresh, and access-link flows
- OPS routes with cross-tenant reach
- billing and subscription actions

Priority 2
- tenant configuration and customer/staff object access
- imports, exports, and feedback retention operations

Priority 3
- notification logs, device registration, and public metadata routes

## Follow-Up Items For BE-SEC-04

This inventory should drive the next checklist items:
- object and tenant authorization review per endpoint group
- throttle and abuse-control review for public and mutation-heavy routes
- CORS, CSRF, and security header review for browser-exposed flows
- security checklist template for new endpoints and PR review