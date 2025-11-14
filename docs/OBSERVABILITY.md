# 🇬🇧 Observability — Salonix Backend (EN)

## Overview
Consolidates logging, metrics, and monitoring practices across the backend. Focus on actionable visibility: structured logs, Prometheus-style metrics, and health signals.

## Logging
- Structured JSON logs with `X-Request-ID` and sanitized fields.
- Emitted across apps (users, reports, payments, ops).
- See `ERROR_HANDLING.md` for standardized error logs.

## Metrics
- Counters and histograms emitted via app-specific modules:
  - `users/observability.py`, `reports/observability.py`, `payments/observability.py`, `ops/observability.py`.
- Typical metrics: appointments created, report generation time, notification events, Stripe webhook handling.

## Health & Monitoring
- Integrate metrics collection and alerting in Ops.
- Surface key SLOs: request latency, error rate, cache hit rate.

## Links
- Architecture: `ARQUITETURA_SISTEMA.md` — Observability section.
- Error handling: `../ERROR_HANDLING.md`.
- Ops Runbook: `OPS_RUNBOOK.md`.

---

# 🇧🇷 Observabilidade — Salonix Backend (PT)

## Visão Geral
Consolida práticas de logs, métricas e monitoramento. Foco em visibilidade acionável: logs estruturados, métricas estilo Prometheus e sinais de saúde.

## Logs
- JSON estruturado com `X-Request-ID` e sanitização.
- Emitidos por apps (users, reports, payments, ops).
- Ver `ERROR_HANDLING.md` para erros padronizados.

## Métricas
- Contadores e histogramas nos módulos:
  - `users/observability.py`, `reports/observability.py`, `payments/observability.py`, `ops/observability.py`.
- Métricas típicas: criação de agendamentos, tempo de geração de relatórios, eventos de notificações, processamento de webhooks Stripe.

## Saúde & Monitoramento
- Integrar coleta e alertas no Ops.
- SLOs chave: latência, taxa de erro, acertos de cache.

## Links
- Arquitetura: `ARQUITETURA_SISTEMA.md` — seção de observabilidade.
- Tratamento de erros: `../ERROR_HANDLING.md`.
- Runbook de Ops: `OPS_RUNBOOK.md`.