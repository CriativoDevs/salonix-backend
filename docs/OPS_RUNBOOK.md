# 📚 OPS Console Runbook

Este documento orienta a equipe de suporte/operations no uso do backend Ops do Salonix.

## 🔐 Acesso e Autenticação

- Criar/atualizar staff Ops:
  ```bash
  make ops-bootstrap EMAIL=staff@example.com [ROLE=ops_support|ops_admin]
  ```
- Endpoints principais:
  - `POST /api/ops/auth/login/`
  - `POST /api/ops/auth/refresh/`
- Tokens incluem scope (`ops_admin` | `ops_support`) e estão isolados do painel tenant.

## 📊 Métricas (OPS-BE-03)

- `GET /api/ops/metrics/overview/`
  - Totais: tenants ativos, trials que expiram em 7 dias, alertas abertos.
  - MRR estimado (EUR) com breakdown por plano (Basic/Standard/Pro).
  - Série diária (últimos 7 dias) de notificações bem-sucedidas por canal (`sms`, `whatsapp`, etc.).
- Plano de preços usado (estimativa):
  | Plano      | MRR (EUR) |
  |------------|-----------|
  | Basic      | 29.00     |
  | Standard   | 59.00     |
  | Pro        | 99.00     |

## 🚨 Alertas

- `GET /api/ops/alerts/` retorna alertas abertos (falhas de notificação, incidentes, etc.).
- Filtros:
  - `?resolved=true|false`
  - `?category=notification_failure|security_incident|system`
  - `?severity=info|warning|critical`
- Resolver alerta:
  ```http
  POST /api/ops/alerts/{id}/resolve/
  ```
  Registra auditoria (`OpsSupportAuditLog`) com actor e timestamp.

## 🛠️ Serviços de Suporte

### Reenviar notificações
- Endpoint: `POST /api/ops/support/resend-notification/`
- Payload:
  ```json
  { "notification_log_id": 123 }
  ```
- Regras:
  - Permite apenas logs com `status` `failed` ou `pending`.
  - Define `metadata.ops_resends += 1` e atualiza `status` para `sent` em caso de sucesso.
  - Métrica Prometheus: `ops_notifications_resend_total{channel, result}`.
  - Auditoria: ação `resend_notification` em `OpsSupportAuditLog`.

### Limpar lockouts
- Apenas `ops_admin`:
  - `POST /api/ops/support/clear-lockout/`
  - Payload opcional com nota:
    ```json
    { "lockout_id": 45, "note": "Unlock manual" }
    ```
  - Marca `lockout.resolved_at`, ativa novamente o usuário se estava bloqueado e registra audit log.
  - Métrica Prometheus: `ops_lockouts_cleared_total{result}` (`success` | `noop`).

## 🧾 Auditoria

- Modelo: `ops.models.OpsSupportAuditLog`.
- Armazena `actor`, `action`, `payload`, `result` e timestamp.
- Consultar via Django Admin (`/admin/ops/`).

## 🎯 Checklist Operacional

1. [ ] Validar migrações: `python manage.py migrate`.
2. [ ] Garantir staff Ops via `make ops-bootstrap`.
3. [ ] Monitorar métricas em `/api/ops/metrics/overview/` e Prometheus (`ops_*`).
4. [ ] Revisar alertas abertos diariamente (`/api/ops/alerts/`).
5. [ ] Registrar qualquer operação manual no audit log (já automático pelas APIs).

## 🔄 Próximos Passos

- Integrar alertas automáticos a partir de falhas críticas (ex.: webhook Stripe, detectores de segurança).
- Expor painel Ops no frontend, consumindo estes endpoints.
- Conectar métricas ao sistema de observabilidade central (Grafana/Prometheus).

---

## 🇬🇧 OPS Console Runbook – English Summary

**Purpose**: guide the support/operations team when using the Salonix Ops backend.

**Access & Auth**
- Bootstrap Ops staff with `make ops-bootstrap EMAIL=... ROLE=ops_support|ops_admin`.
- Main endpoints: `POST /api/ops/auth/login/`, `POST /api/ops/auth/refresh/` (JWT scopes `ops_admin` / `ops_support`).

**Metrics (OPS-BE-03)**
- `GET /api/ops/metrics/overview/` shows active tenants, trials expiring soon, alert counts, estimated MRR per plan, 7-day notification series.

**Alerts**
- List with `GET /api/ops/alerts/` (filters for resolved/category/severity).
- Resolve via `POST /api/ops/alerts/{id}/resolve/`; audit trail captured automatically.

**Support services**
- Resend notification: `POST /api/ops/support/resend-notification/` (only failed/pending logs). Updates metrics `ops_notifications_resend_total` and audit logs.
- Clear lockouts (admins only): `POST /api/ops/support/clear-lockout/` with optional note; sets `resolved_at`, re-enables user and records audit entry + metric `ops_lockouts_cleared_total`.

**Audit Log**
- Model `OpsSupportAuditLog` stores actor/action/payload/result. Browse via Django Admin.

**Operational checklist**
1. Run migrations.
2. Ensure Ops staff exists.
3. Monitor metrics via `/api/ops/metrics/overview/` + Prometheus.
4. Review open alerts daily.
5. Use the provided endpoints so every manual action is auto-audited.

**Next steps**
- Automate alert ingestion (Stripe webhooks, security detectors).
- Provide Ops frontend dashboards.
- Hook Prometheus metrics into Grafana or central monitoring.
