from unittest.mock import patch

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_command_calls_send_appointment_reminders_task():
    with patch(
        "notifications.management.commands.send_appointment_reminders.send_appointment_reminders"
    ) as mock_task:
        call_command("send_appointment_reminders")

    mock_task.assert_called_once_with()
