"""
Pacote principal do projeto Salonix Backend.

Configura a aplicação Celery para funcionar com Django.
"""

# Importa o app Celery para que o Django o carregue automaticamente
from .celery import app as celery_app

__all__ = ("celery_app",)
