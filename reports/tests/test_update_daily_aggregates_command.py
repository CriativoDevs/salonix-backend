from unittest.mock import patch

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_command_calls_update_daily_aggregates_task():
    with patch(
        "reports.management.commands.update_daily_aggregates.update_daily_aggregates"
    ) as mock_task:
        call_command("update_daily_aggregates")

    mock_task.assert_called_once_with()
