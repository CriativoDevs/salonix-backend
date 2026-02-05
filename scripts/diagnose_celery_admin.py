#!/usr/bin/env python
"""
Script de diagnóstico do Django Admin para Celery Results.
Uso: python manage.py runscript diagnose_celery_admin
"""
from django.conf import settings
from django.contrib import admin
from django_celery_results.models import TaskResult, GroupResult


def run():
    print("🔍 DIAGNÓSTICO DO DJANGO ADMIN - CELERY RESULTS")
    print("=" * 60)
    print()

    # 1. Verificar INSTALLED_APPS
    print("1️⃣ django_celery_results em INSTALLED_APPS?")
    if "django_celery_results" in settings.INSTALLED_APPS:
        print("   ✅ SIM - está instalado")
        idx = settings.INSTALLED_APPS.index("django_celery_results")
        print(f"   Posição: {idx} de {len(settings.INSTALLED_APPS)}")
    else:
        print("   ❌ NÃO - PROBLEMA: falta adicionar ao INSTALLED_APPS!")
        return
    print()

    # 2. Verificar modelos registrados
    print("2️⃣ Modelos registrados no Django Admin:")
    if admin.site.is_registered(TaskResult):
        admin_class = admin.site._registry[TaskResult]
        print(f"   ✅ TaskResult - REGISTRADO ({admin_class})")
    else:
        print("   ❌ TaskResult - NÃO REGISTRADO")

    if admin.site.is_registered(GroupResult):
        admin_class = admin.site._registry[GroupResult]
        print(f"   ✅ GroupResult - REGISTRADO ({admin_class})")
    else:
        print("   ⚠️  GroupResult - NÃO REGISTRADO (normal)")
    print()

    # 3. Verificar tasks no banco
    count = TaskResult.objects.count()
    print(f"3️⃣ Tasks no banco de dados: {count}")
    if count > 0:
        print("   ✅ Há tasks para mostrar no admin")
        print(f"   Últimas 3 tasks:")
        for task in TaskResult.objects.order_by("-date_done")[:3]:
            status_icon = "✅" if task.status == "SUCCESS" else "❌"
            print(f"      {status_icon} {task.task_name[:40]} - {task.status}")
    else:
        print("   ⚠️  Banco vazio - nenhuma task executada ainda")
    print()

    # 4. URL direta
    print("4️⃣ URLs para acessar:")
    print("   Admin home:")
    print("      http://0.0.0.0:8000/admin/")
    print("   ")
    print("   Celery Results (acesso direto):")
    print("      http://0.0.0.0:8000/admin/django_celery_results/taskresult/")
    print()

    print("=" * 60)
    print()
    print("⚡ CHECKLIST DE SOLUÇÃO:")
    print()
    print("   [ ] 1. Servidor Django está rodando?")
    print("          Comando: python manage.py runserver 0.0.0.0:8000")
    print()
    print("   [ ] 2. Você fez login no admin como superuser?")
    print("          Crie se necessário: python manage.py createsuperuser")
    print()
    print("   [ ] 3. Reiniciou o servidor após adicionar django_celery_results?")
    print("          Pare (Ctrl+C) e inicie novamente")
    print()
    print("   [ ] 4. Limpou o cache do navegador?")
    print("          Chrome/Firefox: Cmd+Shift+R (macOS)")
    print()
    print("   [ ] 5. Tente acessar a URL direta acima")
    print()
    print("Se ainda não aparecer na sidebar, é normal - alguns admins")
    print("só mostram apps com dados. Use a URL direta!")


if __name__ == "__main__":
    run()
