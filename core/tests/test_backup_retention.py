"""
BE-RGPD-01 / Art. 17: retencao dos backups de tenant.

Os backups criados no hard-delete (BACKUP_ROOT/tenants/{slug}/backup_*.json)
contem PII e nao devem ficar indefinidamente. `purge_old_tenant_backups` remove
os ficheiros mais antigos que o periodo de retencao.
"""

import os
import time

from django.test import override_settings

from core.tasks import purge_old_tenant_backups


def test_purge_removes_old_backups_keeps_recent(tmp_path):
    backups = tmp_path / "tenants" / "some-salon"
    backups.mkdir(parents=True)
    old = backups / "backup_old.json"
    recent = backups / "backup_recent.json"
    old.write_text("{}")
    recent.write_text("{}")

    # Envelhecer o ficheiro "old" para 100 dias atras
    old_ts = time.time() - 100 * 86400
    os.utime(old, (old_ts, old_ts))

    with override_settings(BACKUP_ROOT=str(tmp_path)):
        result = purge_old_tenant_backups(retention_days=90)

    assert not old.exists()
    assert recent.exists()
    assert result["removed"] == 1
    assert result["kept"] == 1
