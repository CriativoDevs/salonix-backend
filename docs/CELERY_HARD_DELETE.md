# Celery + Hard Delete - Guia de Operação

## 📦 Instalação

Já instalado no projeto via `requirements.txt`:
```bash
celery[redis]==5.4.0
redis==5.0.3
django-celery-results==2.5.1
```

## 🚀 Executar Localmente

### 1. Redis (Broker)
```bash
# macOS com Homebrew
brew install redis
brew services start redis

# Ou Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### 2. Celery Worker
```bash
cd salonix-backend
celery -A salonix_backend worker --loglevel=info
```

### 3. Testar Task Manualmente
```python
from core.tasks import hard_delete_tenant, check_expired_cancellations

# Disparar task assíncrona
hard_delete_tenant.delay(tenant_id=123)

# Ou executar síncronamente (debug)
hard_delete_tenant(tenant_id=123)

# Verificar cancelamentos expirados
check_expired_cancellations()
```

## ⏰ Agendar Verificação Diária

### Opção A: Cron (PythonAnywhere/Railway)
```bash
# Editar crontab
crontab -e

# Adicionar linha (diariamente às 3:00 AM)
0 3 * * * cd /path/to/salonix-backend && python manage.py check_expired_tenants >> /var/log/celery-expired.log 2>&1
```

### Opção B: Celery Beat (Railway com Redis)
```bash
# Executar worker + beat juntos
celery -A salonix_backend worker --beat --loglevel=info
```

## 🗄️ Backups

### Localização
```bash
# Dev/Local
salonix-backend/backups/tenants/{slug}/backup_{timestamp}.json

# Railway Production
/data/backups/tenants/{slug}/backup_{timestamp}.json

# PythonAnywhere Staging
/home/username/backups/tenants/{slug}/backup_{timestamp}.json
```

### Estrutura do Backup
```json
{
  "metadata": {
    "tenant_id": 123,
    "tenant_slug": "salon-example",
    "plan_tier": "professional",
    "cancelled_at": "2026-02-05T10:00:00Z",
    "scheduled_deletion_at": "2026-04-06T10:00:00Z",
    "backup_created_at": "2026-04-06T10:05:00Z"
  },
  "data": {
    "tenant": [...],
    "users": [...],
    "staff_members": [...]
  }
}
```

## 📊 Monitoramento

### Django Admin
Acesse `/admin/django_celery_results/taskresult/` para ver:
- ✅ Tasks executadas
- ⏱️ Tempo de execução
- 📄 Resultado JSON
- ❌ Erros

### Logs
```bash
# Ver logs do worker
tail -f /var/log/celery-worker.log

# Ver logs do management command
tail -f /var/log/celery-expired.log
```

## 🛠️ Troubleshooting

### Celery não encontra tasks
```bash
# Verificar autodiscover
python manage.py shell -c "from salonix_backend import celery_app; print(celery_app.tasks.keys())"
```

### Redis não conecta
```bash
# Testar conexão
redis-cli ping
# Deve retornar: PONG

# Verificar settings.py
# CELERY_BROKER_URL = "redis://localhost:6379/0"
```

### Backup falha
```bash
# Verificar permissões do diretório
ls -la /data/backups/tenants/

# Criar manualmente se necessário
mkdir -p /data/backups/tenants
chmod 755 /data/backups/tenants
```

## 🔒 Segurança

- ✅ Backups contêm dados sensíveis → **NÃO** versionar no Git
- ✅ `.gitignore` configurado em `/backups/`
- ✅ Em produção, montar Volume persistente no Railway
- ✅ Logs de auditoria registram todas as operações

## 📝 Variáveis de Ambiente

```bash
# .env (desenvolvimento)
CELERY_BROKER_URL=redis://localhost:6379/0
BACKUP_ROOT=/Users/pablo/Project/salonix/salonix-backend/backups

# Railway (produção)
CELERY_BROKER_URL=redis://redis.railway.internal:6379/0
BACKUP_ROOT=/data/backups

# PythonAnywhere (staging)
# Não há Redis → usar management command + cron
BACKUP_ROOT=/home/username/backups
```
