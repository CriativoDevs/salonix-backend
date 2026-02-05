# Guia Operacional - Cancelamento de Conta

**Versão:** 1.0  
**Data:** Fevereiro 2026  
**Feature:** BE-ACCOUNT-CANCEL #396

---

## 📋 Índice

1. [Visão Geral](#visão-geral)
2. [Fluxo de Cancelamento](#fluxo-de-cancelamento)
3. [Operações Administrativas](#operações-administrativas)
4. [Backup e Restore](#backup-e-restore)
5. [Troubleshooting](#troubleshooting)
6. [Monitoramento](#monitoramento)
7. [FAQ](#faq)

---

## Visão Geral

### O que é o Cancelamento de Conta?

Sistema de soft-delete que permite tenants cancelarem suas contas com:
- **Período de retenção**: 30 dias para reativação
- **Cancelamento Stripe**: Automático de todas as assinaturas
- **Emails transacionais**: Confirmação, lembretes, reativação
- **Hard delete agendado**: Após período de retenção

### Estados do Tenant

```python
ACTIVE = 'active'           # Conta ativa e operacional
CANCELLED = 'cancelled'     # Cancelada, aguardando exclusão
DELETED = 'deleted'         # Hard delete executado (não restaurável)
```

### Timeline do Cancelamento

```
Dia 0: Cancelamento
├─ Status = 'cancelled'
├─ cancelled_at = now()
├─ scheduled_deletion_at = now() + 30 dias
├─ reactivation_token gerado
└─ Email de confirmação enviado

Dia 23: Lembrete automático
└─ Email 7 dias antes da exclusão

Dia 30: Hard Delete
├─ Backup exportado
├─ Dados deletados (GDPR compliant)
└─ Status = 'deleted'
```

---

## Fluxo de Cancelamento

### 1. Cancelamento pelo Owner

**Endpoint:** `POST /api/tenants/cancel/`

**Validações:**
- ✅ Usuário deve ser OWNER do tenant
- ✅ Senha obrigatória
- ✅ Texto de confirmação: "CANCELAR MINHA CONTA"

**Request:**
```json
{
  "password": "senhaDoUsuario",
  "confirmation_text": "CANCELAR MINHA CONTA"
}
```

**Response (Success):**
```json
{
  "message": "Conta cancelada com sucesso",
  "reactivation_deadline": "2026-03-07T14:30:00Z",
  "reactivation_token": "abc123...xyz"
}
```

**Ações Automáticas:**
1. Stripe: Cancela todas as assinaturas ativas
2. Tenant: Altera status para `cancelled`
3. Email: Envia confirmação com link de reativação
4. Logs: Registra operação no audit log

### 2. Reativação pelo Owner

**Endpoint:** `POST /api/tenants/reactivate/`

**Validações:**
- ✅ Token válido e não expirado
- ✅ Dentro do período de retenção (30 dias)
- ✅ Tenant em status `cancelled`

**Request:**
```json
{
  "token": "abc123...xyz"
}
```

**Response (Success):**
```json
{
  "message": "Conta reativada com sucesso",
  "tenant": {
    "id": 123,
    "status": "active",
    "name": "Salão Exemplo"
  }
}
```

**Ações Automáticas:**
1. Tenant: Volta para status `active`
2. Limpa: `cancelled_at`, `scheduled_deletion_at`, `reactivation_token`
3. Email: Envia boas-vindas de reativação

---

## Operações Administrativas

### Reverter Cancelamento (Django Admin)

**Quando usar:**
- Cliente pediu reativação via suporte
- Token de reativação expirado/perdido
- Erro no processo de cancelamento

**Passo a passo:**

1. **Via Django Admin** (Recomendado):
```bash
# Acesse /admin/core/tenant/
# Busque o tenant
# Edite os campos:
- status: 'active'
- cancelled_at: null
- scheduled_deletion_at: null
- reactivation_token: ''
```

2. **Via Django Shell**:
```python
from core.models import Tenant

tenant = Tenant.objects.get(id=123)
tenant.status = 'active'
tenant.cancelled_at = None
tenant.scheduled_deletion_at = None
tenant.reactivation_token = ''
tenant.save()

print(f"✅ Tenant {tenant.name} reativado com sucesso")
```

3. **Notificar o Cliente**:
```python
from core.email_utils import send_account_reactivation_email

send_account_reactivation_email(
    tenant=tenant,
    owner_email='owner@example.com',
    owner_name='João Silva'
)
```

### Adiar Hard Delete

**Cenário:** Cliente quer mais tempo para decidir

```python
from datetime import timedelta
from django.utils import timezone

tenant = Tenant.objects.get(id=123)

# Adicionar 15 dias ao prazo atual
tenant.scheduled_deletion_at += timedelta(days=15)
tenant.save()

print(f"🕐 Nova data de exclusão: {tenant.scheduled_deletion_at}")
```

### Forçar Hard Delete Imediato

**⚠️ ATENÇÃO: Operação irreversível!**

```python
from core.tasks import hard_delete_tenant_data

tenant = Tenant.objects.get(id=123)

# Fazer backup manual primeiro!
print(f"📦 Backup do tenant {tenant.id}...")
# ... export data ...

# Executar hard delete
hard_delete_tenant_data(tenant_id=tenant.id)

print("🗑️ Tenant deletado permanentemente")
```

### Cancelar Sem Retenção (Uso Interno)

**Cenário:** Fraude, violação de ToS, GDPR request

```python
from core.models import Tenant
from payments.services import SubscriptionService

tenant = Tenant.objects.get(id=123)

# 1. Cancelar assinaturas Stripe
result = SubscriptionService.cancel_tenant_subscriptions(tenant)
print(f"💳 Stripe: {result['cancelled_count']} assinaturas canceladas")

# 2. Hard delete imediato
tenant.status = 'deleted'
tenant.save()

# 3. Executar limpeza
from core.tasks import hard_delete_tenant_data
hard_delete_tenant_data(tenant_id=tenant.id)
```

---

## Backup e Restore

### Backup Automático

**Quando acontece:**
- Antes de cada hard delete
- Executado pela task `hard_delete_tenant_data`

**Localização:**
```
/backups/tenants/{tenant_id}_{timestamp}/
├── tenant_metadata.json
├── appointments.json
├── clients.json
├── professionals.json
├── services.json
└── README.txt
```

**Estrutura do Backup:**
```json
{
  "backup_date": "2026-02-05T14:30:00Z",
  "tenant_id": 123,
  "tenant_name": "Salão Exemplo",
  "tenant_slug": "salao-exemplo",
  "owner_email": "owner@example.com",
  "cancelled_at": "2026-01-05T14:30:00Z",
  "records": {
    "appointments": 1250,
    "clients": 450,
    "professionals": 8,
    "services": 25
  }
}
```

### Backup Manual

```python
from core.tasks import export_tenant_data

tenant = Tenant.objects.get(id=123)
backup_path = export_tenant_data(tenant)

print(f"✅ Backup salvo em: {backup_path}")
```

### Restore (Procedimento Manual)

**⚠️ Não há restore automático. Procedimento manual:**

1. **Localizar Backup:**
```bash
ls -la backups/tenants/123_*
```

2. **Criar Novo Tenant:**
```python
from core.models import Tenant

# Criar novo tenant com mesmo slug (ou novo)
new_tenant = Tenant.objects.create(
    name="Salão Exemplo (Restaurado)",
    slug="salao-exemplo-restored",
    status='active'
)
```

3. **Importar Dados:**
```python
import json

# Carregar backup
with open('backups/tenants/123_2026-02-05/clients.json') as f:
    clients_data = json.load(f)

# Recriar registros
from core.models import Client
for client_data in clients_data:
    Client.objects.create(
        tenant=new_tenant,
        name=client_data['name'],
        phone=client_data['phone'],
        # ... outros campos
    )
```

4. **Notificar Cliente:**
- Email informando sobre a restauração
- Novo link de acesso
- Instruções de redefinição de senha (se necessário)

---

## Troubleshooting

### Problema: Email de cancelamento não enviado

**Sintomas:**
- Cancelamento concluído mas owner não recebeu email

**Diagnóstico:**
```python
# Verificar logs do Celery
tail -f /var/log/celery/celery.log | grep "send_account_cancellation_email"

# Verificar status do tenant
tenant = Tenant.objects.get(id=123)
print(f"Status: {tenant.status}")
print(f"Cancelled at: {tenant.cancelled_at}")
print(f"Token: {tenant.reactivation_token[:20]}...")
```

**Solução:**
```python
# Reenviar email manualmente
from core.email_utils import send_account_cancellation_email

send_account_cancellation_email(
    tenant=tenant,
    owner_email='owner@example.com',
    owner_name='João Silva'
)
```

### Problema: Stripe não cancelou assinaturas

**Sintomas:**
- Tenant cancelado mas assinaturas ativas no Stripe

**Diagnóstico:**
```python
from payments.models import Subscription

# Verificar assinaturas
subs = Subscription.objects.filter(
    user__tenant=tenant,
    status='active'
)
print(f"📊 Assinaturas ativas: {subs.count()}")
```

**Solução:**
```python
from payments.services import SubscriptionService

result = SubscriptionService.cancel_tenant_subscriptions(tenant)
print(f"✅ Canceladas: {result['cancelled_count']}")
print(f"❌ Erros: {result['errors']}")
```

### Problema: Hard delete não executou

**Sintomas:**
- Data de exclusão passou mas tenant ainda existe

**Diagnóstico:**
```python
from django.utils import timezone

tenant = Tenant.objects.get(id=123)
print(f"Status: {tenant.status}")
print(f"Scheduled deletion: {tenant.scheduled_deletion_at}")
print(f"Agora: {timezone.now()}")
print(f"Atrasado: {timezone.now() > tenant.scheduled_deletion_at}")

# Verificar Celery Beat
# Confirmar que a task está agendada
```

**Solução:**
```python
# Executar manualmente
from core.tasks import check_expired_tenants, hard_delete_tenant_data

# Buscar tenants expirados
check_expired_tenants()

# Ou forçar hard delete específico
hard_delete_tenant_data(tenant_id=123)
```

### Problema: Token de reativação inválido

**Sintomas:**
- Cliente tenta reativar mas token não funciona

**Diagnóstico:**
```python
tenant = Tenant.objects.get(id=123)

# Verificar token salvo
print(f"Token salvo: {tenant.reactivation_token[:20]}...")

# Verificar prazo
from django.utils import timezone
print(f"Scheduled deletion: {tenant.scheduled_deletion_at}")
print(f"Expirado: {timezone.now() > tenant.scheduled_deletion_at}")
```

**Solução:**
```python
# Gerar novo token e estender prazo
from datetime import timedelta
from django.utils import timezone

tenant.reactivation_token = tenant.generate_reactivation_token()
tenant.scheduled_deletion_at = timezone.now() + timedelta(days=7)
tenant.save()

# Enviar novo email com token atualizado
from core.email_utils import send_account_cancellation_email
send_account_cancellation_email(
    tenant=tenant,
    owner_email='owner@example.com',
    owner_name='João Silva'
)
```

### Problema: Lembrete de exclusão não enviado

**Sintomas:**
- Tenant 7 dias antes da exclusão mas não recebeu lembrete

**Diagnóstico:**
```bash
# Verificar logs do Celery Beat
tail -f /var/log/celery/celery-beat.log

# Verificar agendamento da task
python manage.py shell
>>> from django_celery_beat.models import PeriodicTask
>>> task = PeriodicTask.objects.get(name='send-deletion-reminders')
>>> print(f"Enabled: {task.enabled}")
>>> print(f"Last run: {task.last_run_at}")
```

**Solução:**
```python
# Executar task manualmente
from core.tasks import send_deletion_reminders

send_deletion_reminders()

# Ou enviar email específico
from core.email_utils import send_deletion_reminder_email

tenant = Tenant.objects.get(id=123)
send_deletion_reminder_email(
    tenant=tenant,
    owner_email='owner@example.com',
    owner_name='João Silva',
    days_remaining=7
)
```

---

## Monitoramento

### Métricas Recomendadas

**1. Taxa de Cancelamento:**
```python
from django.utils import timezone
from datetime import timedelta

# Cancelamentos nos últimos 30 dias
last_month = timezone.now() - timedelta(days=30)
cancellations = Tenant.objects.filter(
    status='cancelled',
    cancelled_at__gte=last_month
).count()

total_active = Tenant.objects.filter(status='active').count()
churn_rate = (cancellations / total_active) * 100

print(f"📉 Taxa de cancelamento: {churn_rate:.2f}%")
```

**2. Taxa de Reativação:**
```python
# Tenants que reativaram após cancelar
reactivations = Tenant.objects.filter(
    status='active',
    cancelled_at__isnull=False  # Já cancelaram antes
).count()

reactivation_rate = (reactivations / cancellations) * 100
print(f"📈 Taxa de reativação: {reactivation_rate:.2f}%")
```

**3. Tenants Pendentes de Exclusão:**
```python
from django.utils import timezone

pending = Tenant.objects.filter(
    status='cancelled',
    scheduled_deletion_at__gt=timezone.now()
).count()

print(f"⏳ Pendentes de exclusão: {pending}")
```

**4. Hard Deletes Executados:**
```python
deleted = Tenant.objects.filter(status='deleted').count()
print(f"🗑️ Hard deletes executados: {deleted}")
```

### Logs a Monitorar

**1. Celery Worker:**
```bash
tail -f /var/log/celery/celery.log | grep -E "(hard_delete|check_expired|deletion_reminder)"
```

**2. Celery Beat:**
```bash
tail -f /var/log/celery/celery-beat.log
```

**3. Django Application:**
```bash
tail -f /var/log/django/app.log | grep -E "(TenantCancel|TenantReactivate)"
```

### Alertas Recomendados

1. **Spike de cancelamentos**: > 10% em 24h
2. **Hard delete falhou**: Tenant com scheduled_deletion_at no passado e status != deleted
3. **Emails não enviados**: Falhas no Celery task de email
4. **Stripe sync issues**: Erros ao cancelar assinaturas

---

## FAQ

### Q: Posso reverter um hard delete?

**A:** Não diretamente. O hard delete é permanente. Porém:
- ✅ Existe backup automático antes da exclusão
- ✅ Restore manual é possível (veja seção [Backup e Restore](#backup-e-restore))
- ⚠️ Requer criação de novo tenant e importação manual

### Q: O que acontece com assinaturas Stripe?

**A:** 
- Todas as assinaturas ativas são canceladas imediatamente
- Stripe é notificado via API
- Não há cobrança futura
- Período já pago permanece disponível até o fim

### Q: Clientes do salão recebem notificação?

**A:**
- ❌ Clientes NÃO recebem email automático
- ✅ Recomendado: Owner avisar clientes antes de cancelar
- ✅ Frontend pode mostrar banner/modal antes do cancelamento

### Q: Posso cancelar um tenant sem ser owner?

**A:**
- ❌ Apenas OWNER pode cancelar via API
- ✅ Django Admin pode cancelar (superuser/staff)
- ✅ Operações do sistema podem forçar cancelamento

### Q: Hard delete deleta tudo mesmo?

**A:**
Sim, são deletados:
- ✅ Appointments
- ✅ Clients
- ✅ Professionals
- ✅ Services
- ✅ TenantStaffMembers
- ✅ CustomUser (se não tiver outros tenants)
- ✅ Tenant metadata

Preservado:
- ✅ Backup em `/backups/tenants/`
- ✅ Logs de auditoria (se configurado)

### Q: Quanto tempo o backup fica armazenado?

**A:**
- Indefinidamente (ou conforme política de retenção)
- Recomendado: Mover para cold storage após 90 dias
- GDPR: Cliente pode solicitar exclusão de backup

### Q: Posso testar cancelamento em staging?

**A:**
Sim! Use dados de teste:
1. Crie tenant de teste
2. Use Stripe test keys
3. Execute cancelamento
4. Aguarde tasks Celery
5. Verifique emails (MailHog/Mailtrap)

### Q: Como debugar problemas com Celery?

**A:**
```bash
# Status dos workers
celery -A salonix_backend inspect active

# Tasks agendadas
celery -A salonix_backend inspect scheduled

# Ver logs em tempo real
tail -f /var/log/celery/celery.log

# Executar task manualmente
python manage.py shell
>>> from core.tasks import send_deletion_reminders
>>> send_deletion_reminders.delay()
```

---

## Compliance e GDPR

### Direito ao Esquecimento

O sistema de cancelamento atende ao GDPR:
- ✅ Exclusão permanente de dados pessoais após 30 dias
- ✅ Backup pode ser deletado sob request
- ✅ Processo documentado e auditável

### Procedimento GDPR Request

1. Cliente solicita exclusão imediata:
```python
# Sem período de retenção
tenant.status = 'deleted'
tenant.save()

# Hard delete imediato
from core.tasks import hard_delete_tenant_data
hard_delete_tenant_data(tenant_id=tenant.id)

# Deletar backup
import shutil
shutil.rmtree(f'/backups/tenants/{tenant.id}_*')
```

2. Documentar compliance:
- Registrar request no audit log
- Confirmar exclusão via email
- Manter registro da operação (sem PII)

---

## Contatos de Suporte

**Equipe de Operações:**
- Email: ops@timelyone.com
- Slack: #ops-support

**Emergências:**
- On-call: +55 11 99999-9999
- Escalation: tech-lead@timelyone.com

**Documentação Adicional:**
- [Celery Production Guide](celery_prod_run.md)
- [Arquitetura do Sistema](docs/ARQUITETURA_SISTEMA.md)
- [API OpenAPI](docs/API_OPENAPI.md)

---

**Última atualização:** Fevereiro 2026  
**Revisão:** v1.0  
**Próxima revisão:** Maio 2026
