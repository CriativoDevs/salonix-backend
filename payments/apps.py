from django.apps import AppConfig
from typing import ClassVar


class PaymentsConfig(AppConfig):
    default_auto_field: ClassVar[str] = 'django.db.models.BigAutoField'
    name = 'payments'
