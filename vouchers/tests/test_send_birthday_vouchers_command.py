from unittest.mock import patch

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_command_calls_send_birthday_vouchers_task():
    with patch(
        "vouchers.management.commands.send_birthday_vouchers.send_birthday_vouchers"
    ) as mock_task:
        mock_task.return_value = {"vouchers_sent": 3}
        call_command("send_birthday_vouchers")

    mock_task.assert_called_once_with()
