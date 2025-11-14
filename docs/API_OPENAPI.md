# 🇬🇧 API & OpenAPI — Salonix Backend (EN)

## Overview
Salonix exposes REST APIs documented via Swagger UI and OpenAPI schema. This page explains where to find and regenerate the schema.

## Key URLs
- Swagger UI: `http://0.0.0.0:8000/api/schema/swagger-ui/`
- API root: `http://0.0.0.0:8000/api/`

## Schema Files
- OpenAPI YAML: `salonix-backend/api-schema.yaml`

## Developer Tasks
- Generate/refresh schema: `make openapi` (if available) or DRF Spectacular export commands.
- Keep endpoints and serializers in sync; update docs on changes.

## Links
- Architecture: `ARQUITETURA_SISTEMA.md`.
- Reports: `REPORTS_OVERVIEW.md`.
- Payments (Stripe): `PAGAMENTOS_STRIPE.md`.

---

# 🇧🇷 API & OpenAPI — Salonix Backend (PT)

## Visão Geral
O backend expõe APIs REST documentadas via Swagger UI e schema OpenAPI. Esta página mostra onde encontrar e como regenerar o schema.

## URLs Principais
- Swagger UI: `http://0.0.0.0:8000/api/schema/swagger-ui/`
- Raiz da API: `http://0.0.0.0:8000/api/`

## Arquivos de Schema
- OpenAPI YAML: `salonix-backend/api-schema.yaml`

## Tarefas de Dev
- Gerar/atualizar schema: `make openapi` (se disponível) ou comandos do DRF Spectacular.
- Manter endpoints e serializers alinhados; atualizar docs ao mudar.

## Links
- Arquitetura: `ARQUITETURA_SISTEMA.md`.
- Relatórios: `REPORTS_OVERVIEW.md`.
- Pagamentos (Stripe): `PAGAMENTOS_STRIPE.md`.