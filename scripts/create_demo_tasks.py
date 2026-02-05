from django_celery_results.models import TaskResult
from django.utils import timezone

# Criar 3 tasks fake para demonstração
tasks = [
    {
        "task_id": "demo-check-expired-001",
        "task_name": "core.check_expired_cancellations",
        "status": "SUCCESS",
        "result": '{"checked_at": "2026-02-05T14:00:00Z", "found": 0, "dispatched": 0, "errors": 0}',
    },
    {
        "task_id": "demo-hard-delete-002",
        "task_name": "core.hard_delete_tenant",
        "status": "SUCCESS",
        "result": '{"success": true, "tenant_id": 92, "tenant_slug": "test-cancelamento", "backup_path": "/backups/test.json", "deleted_at": "2026-02-05T14:05:00Z"}',
    },
    {
        "task_id": "demo-check-expired-003",
        "task_name": "core.check_expired_cancellations",
        "status": "FAILURE",
        "result": None,
        "traceback": 'Traceback (most recent call last):\n  File "tasks.py", line 50\n    raise Exception("Exemplo de erro")\nException: Exemplo de erro',
    },
]

for task_data in tasks:
    TaskResult.objects.create(
        task_id=task_data["task_id"],
        task_name=task_data["task_name"],
        status=task_data["status"],
        result=task_data.get("result"),
        traceback=task_data.get("traceback"),
        date_created=timezone.now(),
        date_done=timezone.now(),
        worker="celery@demo-worker",
    )

print("✅ 3 tasks de demonstração criadas!")
print()
print("🔗 Acesse: http://localhost:8000/admin/django_celery_results/taskresult/")
print()
print("Você verá:")
print("  1. ✅ check_expired_cancellations - SUCCESS")
print("  2. ✅ hard_delete_tenant - SUCCESS")
print("  3. ❌ check_expired_cancellations - FAILURE")
