"""
Configuração do Celery para o projeto Salonix.

Este arquivo define a app Celery e configura o autodiscovery de tasks
a partir de cada app Django.

Referência: https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html
"""

import os

from celery import Celery

# Define as configurações Django para o Celery
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "salonix_backend.settings")

# Cria a instância do Celery
app = Celery("salonix_backend")

# Carrega configurações a partir do namespace "CELERY" no settings.py
# Ex: CELERY_BROKER_URL, CELERY_RESULT_BACKEND, etc.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Autodescobre tasks.py em cada app instalado
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Task de debug para validar que o Celery está funcionando."""
    print(f"Request: {self.request!r}")
