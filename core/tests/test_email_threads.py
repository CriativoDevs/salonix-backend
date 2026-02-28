import pytest
from unittest.mock import patch, MagicMock
from core.email_utils import _send_email_safe
import time

@pytest.mark.django_db
def test_send_email_safe_is_asynchronous():
    """
    Valida se o envio de e-mail é assíncrono (Threaded).
    A função deve retornar o controle quase instantaneamente, mesmo que o envio demore.
    """
    subject = "Teste Assíncrono"
    body = "Conteúdo"
    to_email = "test@example.com"

    # Mock do envio de e-mail com atraso artificial
    with patch("core.email_utils.EmailMultiAlternatives") as mock_email_class:
        mock_instance = MagicMock()
        mock_email_class.return_value = mock_instance
        
        # Simula um servidor SMTP lento (0.5 segundos)
        def slow_send(*args, **kwargs):
            time.sleep(0.5)
            return True
        
        mock_instance.send.side_effect = slow_send

        start_time = time.time()
        
        # Dispara o envio
        result = _send_email_safe(subject, body, None, to_email)
        
        duration = time.time() - start_time

        # A função deve ter retornado True imediatamente (muito antes de 0.5s)
        assert result is True
        assert duration < 0.1, f"O envio bloqueou a thread principal por {duration:.4f}s"
        
        # Aguarda um tempo suficiente para a thread terminar seu trabalho
        time.sleep(0.7)
        
        # Garante que o método send foi chamado dentro da thread
        assert mock_instance.send.called
        assert mock_email_class.called
