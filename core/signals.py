from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from core.models import Appointment
from reports.utils.cache import debounce_invalidate_many

PREFIXES = (
    "reports:overview:",
    "reports:top_services:",
    "reports:revenue:",
)


def _schedule_invalidation():
    # Coalesce invalidações por 2s (process-local). Seguro para bursts.
    debounce_invalidate_many(PREFIXES, wait_seconds=2.0)


@receiver(post_save, sender=Appointment, dispatch_uid="reports_cache_on_appt_save")
def reports_cache_on_appt_save(sender, instance, **kwargs):
    transaction.on_commit(_schedule_invalidation)


@receiver(post_delete, sender=Appointment, dispatch_uid="reports_cache_on_appt_delete")
def reports_cache_on_appt_delete(sender, instance, **kwargs):
    transaction.on_commit(_schedule_invalidation)
