from unittest.mock import patch

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_command_calls_purge_old_tenant_backups_function():
    with patch(
        "core.management.commands.purge_old_tenant_backups.purge_old_tenant_backups"
    ) as mock_fn:
        mock_fn.return_value = {"removed": 3, "kept": 5}
        call_command("purge_old_tenant_backups")

    mock_fn.assert_called_once_with(retention_days=90)


@pytest.mark.django_db
def test_command_accepts_custom_retention_days():
    with patch(
        "core.management.commands.purge_old_tenant_backups.purge_old_tenant_backups"
    ) as mock_fn:
        mock_fn.return_value = {"removed": 0, "kept": 0}
        call_command("purge_old_tenant_backups", "--retention-days", "30")

    mock_fn.assert_called_once_with(retention_days=30)
