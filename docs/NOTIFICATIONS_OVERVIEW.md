# 🇬🇧 Notifications Overview — Salonix Backend (EN)

## Overview
Salonix provides a notifications subsystem with event hooks, logging, and metrics. Real delivery drivers (Twilio SMS, WhatsApp via Meta) are pending for MVP completion.

## Channels
- Email (internal utility), SMS (Twilio, pending), WhatsApp (Meta, pending), Push (web/mobile, planned).

## Credits & Realtime
- Credit accounting lives under `notifications/` and `users/` modules.
- Realtime credits via SSE: `GET /api/users/realtime/credits/`.

## Implementation
- Core app: `salonix-backend/notifications/` — models, services, serializers, views.
- Metrics: emitted via `notifications/observability.py` (planned) and Ops.

## Pending Tasks
- BE-128: Twilio SMS integration (production delivery).
- BE-129: WhatsApp via Meta.
- BE-131+: Plan limits, dashboards, templates, webhooks.

## Links
- Architecture: `ARQUITETURA_SISTEMA.md`.
- Ops Runbook: `OPS_RUNBOOK.md`.
- Seed credits: `../SEED_DATA_CREDITS.md`.

---

# 🇧🇷 Visão Geral de Notificações — Salonix Backend (PT)

## Visão Geral
O subsistema de notificações possui hooks de eventos, logging e métricas. Drivers de entrega real (Twilio SMS, WhatsApp Meta) estão pendentes para concluir o MVP.

## Canais
- E-mail (utilitário interno), SMS (Twilio, pendente), WhatsApp (Meta, pendente), Push (web/mobile, planejado).

## Créditos & Realtime
- Contabilização de créditos em `notifications/` e `users/`.
- Créditos em tempo real via SSE: `GET /api/users/realtime/credits/`.

## Implementação
- App: `salonix-backend/notifications/` — models, services, serializers, views.
- Métricas: emitidas via `notifications/observability.py` (planejado) e Ops.

## Tarefas Pendentes
- BE-128: Integração SMS Twilio (entrega real).
- BE-129: WhatsApp via Meta.
- BE-131+: Limites por plano, dashboards, templates, webhooks.

## Links
- Arquitetura: `ARQUITETURA_SISTEMA.md`.
- Runbook de Ops: `OPS_RUNBOOK.md`.
- Seed de créditos: `../SEED_DATA_CREDITS.md`.