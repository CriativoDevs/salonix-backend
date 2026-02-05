import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "salonix_backend.settings")
django.setup()

from django.conf import settings
from django.contrib import admin
from django_celery_results.models import TaskResult, GroupResult

print("🔍 DIAGNÓSTICO DO DJANGO ADMIN")
print("=" * 50)
print()

# 1. Verificar INSTALLED_APPS
print("1️⃣ django_celery_results em INSTALLED_APPS?")
if "django_celery_results" in settings.INSTALLED_APPS:
    print("   ✅ SIM - está instalado")
    idx = settings.INSTALLED_APPS.index("django_celery_results")
    print(f"   Posição: {idx} de {len(settings.INSTALLED_APPS)}")
else:
    print("   ❌ NÃO - falta adicionar ao INSTALLED_APPS!")
print()

# 2. Verificar modelos registrados
print("2️⃣ Modelos registrados no admin:")
if admin.site.is_registered(TaskResult):
    print("   ✅ TaskResult - REGISTRADO")
else:
    print("   ❌ TaskResult - NÃO REGISTRADO")

if admin.site.is_registered(GroupResult):
    print("   ✅ GroupResult - REGISTRADO")
else:
    print("   ❌ GroupResult - NÃO REGISTRADO")
print()

# 3. Verificar quantidade de tasks no banco
count = TaskResult.objects.count()
print(f"3️⃣ Tasks no banco: {count}")
if count > 0:
    print("   ✅ Há tasks para mostrar")
    print(f"   Últimas 3 tasks:")
    for task in TaskResult.objects.order_by("-date_done")[:3]:
        status_icon = "✅" if task.status == "SUCCESS" else "❌"
        print(f"      {status_icon} {task.task_name} - {task.status}")
else:
    print("   ⚠️  Banco vazio - execute o script de demo primeiro")
print()

# 4. Listar todas as apps no admin
print("4️⃣ Apps visíveis no admin sidebar:")
app_list = admin.site.get_app_list(request=None)
if app_list:
    for app in app_list:
        print(f'   📦 {app.get("name", "Unknown")} ({app.get("app_label", "?")})')
        for model in app.get("models", []):
            print(f'      - {model.get("name", "?")}')
else:
    print("   ⚠️  Não foi possível listar (precisa de request)")
print()

print("=" * 50)
print()
print("⚡ PRÓXIMOS PASSOS:")
print("   1. PARE o servidor Django (Ctrl+C no terminal do runserver)")
print("   2. Reinicie: python manage.py runserver 0.0.0.0:8000")
print("   3. Acesse: http://0.0.0.0:8000/admin/")
print("   4. Faça login como superuser")
print('   5. Procure a seção "CELERY RESULTS" na barra lateral')
print()
print("   Se ainda não aparecer, tente:")
print("   - Limpar cache do navegador (Cmd+Shift+R no Chrome/Firefox)")
print(
    "   - Acessar diretamente: http://0.0.0.0:8000/admin/django_celery_results/taskresult/"
)
