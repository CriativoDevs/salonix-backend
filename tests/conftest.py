import pytest
from django.conf import settings


@pytest.fixture(autouse=True, scope="session")
def disable_outbound_emails_for_tests():
    settings.EMAIL_DISABLE_OUTBOUND = True
