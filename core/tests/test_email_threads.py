import pytest
from unittest.mock import patch, MagicMock
from core.email_utils import _send_email_safe
import time
import threading


@pytest.mark.django_db
def test_send_email_safe_with_retries():
    """
    Valida se o envio de e-mail tenta novamente (retry) em caso de falha.
    """
    subject = "TEST_THREAD_BYPASS: Teste Retry"
    body = "Conteúdo"
    to_email = "test@example.com"

    # Criamos um evento para sinalizar quando a thread terminar
    done_event = threading.Event()

    with patch("core.email_utils.EmailMultiAlternatives") as mock_email_class, patch(
        "time.sleep", return_value=None
    ):

        mock_instance = MagicMock()
        mock_email_class.return_value = mock_instance

        # Simula falha na primeira tentativa e sucesso na segunda
        calls = []

        def side_effect(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("[Errno 101] Network is unreachable")
            # Na segunda chamada, sinalizamos que terminou
            if len(calls) == 2:
                done_event.set()
            return True

        mock_instance.send.side_effect = side_effect

        # Chama a função
        result = _send_email_safe(subject, body, None, to_email)
        assert result is True

        # Aguarda a thread processar as duas tentativas (com timeout de segurança)
        # O wait() é muito mais confiável que time.sleep()
        completed = done_event.wait(timeout=2.0)

        assert completed, "A thread não completou as tentativas de envio a tempo"
        assert mock_instance.send.call_count == 2
