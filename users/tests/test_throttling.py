from django.test import override_settings
from users.throttling import UsersClientRegistrationThrottle


class DummyView:
    def __init__(self, tenant_slug=None):
        self.kwargs = {"tenant_slug": tenant_slug} if tenant_slug else {}


class DummyRequest:
    user = None

    def __init__(self):
        pass


def test_clients_registration_throttle_cache_key_uses_tenant_slug():
    throttle = UsersClientRegistrationThrottle()
    view = DummyView(tenant_slug="Salao-Teste")
    request = DummyRequest()
    request.user = None
    key = throttle.get_cache_key(request, view)
    assert key is not None
    assert "salao-teste" in key


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
        "DEFAULT_THROTTLE_RATES": {"clients_registration": "50/hour"},
    }
)
def test_clients_registration_throttle_rate_is_configured():
    throttle = UsersClientRegistrationThrottle()
    assert throttle.get_rate() == "50/hour"
