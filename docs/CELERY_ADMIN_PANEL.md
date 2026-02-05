# Como Ver Tasks do Celery no Django Admin

## 📋 Pré-requisitos

Para ver tasks no admin, elas precisam ser executadas **via Celery worker**, não diretamente.

## 🚀 Passo a Passo

### 1. Iniciar Redis (Broker)

```bash
# Se não tiver Redis instalado:
brew install redis

# Iniciar Redis
brew services start redis

# Verificar se está rodando
redis-cli ping
# Deve retornar: PONG
```

### 2. Iniciar Celery Worker

**Terminal 1:**
```bash
cd salonix-backend
celery -A salonix_backend worker --loglevel=info
```

Você verá:
```
-------------- celery@hostname v5.4.0
---- **** -----
--- * ***  * -- Darwin-arm64-2026-02-05 14:20:00
-- * - **** ---
- ** ---------- [config]
- ** ---------- .> app:         salonix_backend:0x...
- ** ---------- .> transport:   redis://localhost:6379/0
- ** ---------- .> results:     django-db
- *** --- * --- .> concurrency: 8 (prefork)
-- ******* ---- .> task events: OFF

[tasks]
  . core.check_expired_cancellations
  . core.hard_delete_tenant
```

### 3. Executar Task Assíncrona

**Terminal 2:**
```bash
cd salonix-backend
python manage.py shell
```

```python
from core.tasks import check_expired_cancellations

# Executa via Celery worker (assíncrono)
result = check_expired_cancellations.delay()

print(f"Task ID: {result.id}")
print(f"Status: {result.status}")

# Aguardar resultado (blocking)
# resultado = result.get(timeout=10)
```

### 4. Ver no Django Admin

1. Acesse: http://localhost:8000/admin/
2. Login com superuser
3. Procure seção **"CELERY RESULTS"**
4. Clique em **"Task results"**

Você verá:

| Task ID | Task Name | Date Done | Status | Worker |
|---------|-----------|-----------|--------|--------|
| abc123... | core.check_expired_cancellations | 2026-02-05 14:20 | SUCCESS | celery@hostname |

### 5. Ver Detalhes da Task

Clique em qualquer task para ver:
- ✅ **Result**: JSON com retorno da task
- ✅ **Traceback**: Se houver erro
- ✅ **Args/Kwargs**: Parâmetros passados
- ✅ **Date Created/Done**: Timestamps
- ✅ **Worker**: Nome do worker que executou

## 🧪 Testar Agora (Sem Worker)

Se quiser apenas ver como fica no admin **sem** configurar Redis/Celery:

```bash
python manage.py shell
```

```python
from django_celery_results.models import TaskResult
from django.utils import timezone

# Criar task fake manualmente
TaskResult.objects.create(
    task_id='test-123',
    task_name='core.check_expired_cancellations',
    status='SUCCESS',
    result='{"found": 0, "dispatched": 0}',
    date_created=timezone.now(),
    date_done=timezone.now(),
)

print("✅ Task fake criada! Veja em /admin/django_celery_results/taskresult/")
```

## 📊 Filtros Disponíveis no Admin

O admin do Celery tem filtros úteis:
- **Status**: SUCCESS, FAILURE, PENDING, RETRY, REVOKED
- **Task Name**: Filtra por nome da task
- **Date Done**: Filtra por data de execução
- **Worker**: Filtra por worker que executou

## 🔍 Buscar Tasks

Use a barra de busca para procurar por:
- Task ID completo
- Parte do nome da task

## ⚠️ Importante

**Por que tasks executadas diretamente não aparecem?**

Quando você executa:
```python
result = check_expired_cancellations()  # Direto
```

A task roda **no processo do shell**, não via Celery. Logo, não é registrada no `django-celery-results`.

Apenas tasks executadas via `.delay()` ou `.apply_async()` são registradas:
```python
result = check_expired_cancellations.delay()  # Via Celery worker
```

## 📚 Mais Informações

- Ver [docs/CELERY_HARD_DELETE.md](CELERY_HARD_DELETE.md) para guia completo de operação
- Documentação oficial: https://docs.celeryq.dev/
