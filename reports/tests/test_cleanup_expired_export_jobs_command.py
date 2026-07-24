from unittest.mock import patch

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_command_calls_cleanup_expired_export_jobs_task():
    with patch(
        "reports.management.commands.cleanup_expired_export_jobs.cleanup_expired_export_jobs"
    ) as mock_task:
        mock_task.return_value = {"deleted_jobs": 2, "deleted_files": 1}
        call_command("cleanup_expired_export_jobs")

    mock_task.assert_called_once_with()
