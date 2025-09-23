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
