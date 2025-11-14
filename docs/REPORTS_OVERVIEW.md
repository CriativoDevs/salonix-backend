# 🇬🇧 Reports Overview — Salonix Backend (EN)

## Overview
Reports provide operational and business insights: overview, top services, revenue, and exports. Designed with cache, throttling, and CSV export.

## Implementation
- App: `salonix-backend/reports/` — models, views, throttling, observability.
- Cache invalidation via signals, scoped throttling for protection.
- CSV export available for main reports.

## Typical Endpoints
- `GET /api/reports/overview/`
- `GET /api/reports/top-services/`
- `GET /api/reports/revenue/`
- `GET /api/reports/.../export.csv`

## Links
- Architecture: `ARQUITETURA_SISTEMA.md`.
- Ops Runbook: `OPS_RUNBOOK.md`.

---

# 🇧🇷 Visão Geral de Relatórios — Salonix Backend (PT)

## Visão Geral
Relatórios entregam visão operacional e de negócio: overview, serviços mais vendidos, receita e exportações. Projetados com cache, throttling e export CSV.

## Implementação
- App: `salonix-backend/reports/` — models, views, throttling, observability.
- Invalidação de cache por signals, throttling por escopo.
- Exportação CSV nos principais relatórios.

## Endpoints Típicos
- `GET /api/reports/overview/`
- `GET /api/reports/top-services/`
- `GET /api/reports/revenue/`
- `GET /api/reports/.../export.csv`

## Links
- Arquitetura: `ARQUITETURA_SISTEMA.md`.
- Runbook de Ops: `OPS_RUNBOOK.md`.