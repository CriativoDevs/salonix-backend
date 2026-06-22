import threading
from unittest.mock import patch, MagicMock

import pytest

from core.email_utils import _send_email_safe


@pytest.mark.django_db
def test_emails_use_today_sender_and_default_reply_to():
    """
    BE-EMAIL-01: todos os emails devem sair com remetente em timelyone.today
    (default do codigo, sem env var) e com Reply-To support@timelyone.today.
    """
    done = threading.Event()

    with patch("core.email_utils.EmailMultiAlternatives") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance

        def send_side_effect(*args, **kwargs):
            done.set()
            return True

        instance.send.side_effect = send_side_effect

        # Prefixo TEST_THREAD_BYPASS forca o caminho real mesmo com outbound desativado.
        _send_email_safe(
            "TEST_THREAD_BYPASS: sender check", "corpo", None, "cliente@example.com"
        )

        assert done.wait(timeout=2.0), "thread de envio nao completou a tempo"

        kwargs = mock_cls.call_args.kwargs
        assert "@timelyone.today" in kwargs["from_email"], kwargs["from_email"]
        assert "timelyone.com" not in kwargs["from_email"], kwargs["from_email"]
        assert kwargs["reply_to"] == ["support@timelyone.today"], kwargs["reply_to"]


@pytest.mark.django_db
def test_explicit_reply_to_is_preserved():
    """Um reply_to explicito tem prioridade sobre o default."""
    done = threading.Event()

    with patch("core.email_utils.EmailMultiAlternatives") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.send.side_effect = lambda *a, **k: done.set() or True

        _send_email_safe(
            "TEST_THREAD_BYPASS: explicit reply",
            "corpo",
            None,
            "cliente@example.com",
            reply_to=["booking@timelyone.today"],
        )

        assert done.wait(timeout=2.0)
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["reply_to"] == ["booking@timelyone.today"]
