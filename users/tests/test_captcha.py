import pytest
from unittest.mock import patch, Mock
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory
from users.security import enforce_captcha_or_raise
from captcha.models import CaptchaStore
from django.utils import timezone
from users.views_captcha import CaptchaGenerateView


@pytest.mark.django_db
class TestCaptchaService:
    def setup_method(self):
        self.factory = APIRequestFactory()

    def test_generate_captcha_view(self):
        view = CaptchaGenerateView.as_view()
        request = self.factory.get("/api/users/captcha/new/")
        response = view(request)

        assert response.status_code == 200
        assert "key" in response.data
        assert "image_url" in response.data

        # Verify it was created in DB
        assert CaptchaStore.objects.filter(hashkey=response.data["key"]).exists()

    def test_enforce_disabled(self):
        request = Mock()
        with patch("django.conf.settings.CAPTCHA_ENABLED", False):
            # Should not raise
            enforce_captcha_or_raise(request)

    def test_enforce_no_token(self):
        request = Mock()
        request.data = {}
        request.headers = {}

        with patch("django.conf.settings.CAPTCHA_ENABLED", True):
            with pytest.raises(ValidationError) as exc:
                enforce_captcha_or_raise(request)
            assert "Token de captcha ausente" in str(exc.value)

    def test_enforce_bypass(self):
        request = Mock()
        # Mock request data properly
        request.data = {"captcha_value": "bypass-secret", "captcha_key": "any-key"}
        request.headers = {}

        with patch("django.conf.settings.CAPTCHA_ENABLED", True), patch(
            "django.conf.settings.CAPTCHA_BYPASS_TOKEN", "bypass-secret"
        ):
            # Should not raise and not query DB
            enforce_captcha_or_raise(request)

    def test_enforce_validation_success(self):
        # Create a real captcha
        hash_key = CaptchaStore.generate_key()
        captcha = CaptchaStore.objects.get(hashkey=hash_key)

        request = Mock()
        request.data = {
            "captcha_key": hash_key,
            "captcha_value": captcha.response,  # Correct response
        }

        with patch("django.conf.settings.CAPTCHA_ENABLED", True):
            enforce_captcha_or_raise(request)

        # Should be deleted after use
        assert not CaptchaStore.objects.filter(hashkey=hash_key).exists()

    def test_enforce_validation_failure_wrong_response(self):
        hash_key = CaptchaStore.generate_key()

        request = Mock()
        request.data = {"captcha_key": hash_key, "captcha_value": "wrong"}

        with patch("django.conf.settings.CAPTCHA_ENABLED", True):
            with pytest.raises(ValidationError) as exc:
                enforce_captcha_or_raise(request)
            assert "Captcha incorreto" in str(exc.value)

    def test_enforce_validation_failure_expired_or_invalid_key(self):
        request = Mock()
        request.data = {"captcha_key": "invalid-key", "captcha_value": "anything"}

        with patch("django.conf.settings.CAPTCHA_ENABLED", True):
            with pytest.raises(ValidationError) as exc:
                enforce_captcha_or_raise(request)
            assert "Captcha inválido ou expirado" in str(exc.value)

    def test_case_insensitive_validation(self):
        # Create a real captcha
        hash_key = CaptchaStore.generate_key()
        captcha = CaptchaStore.objects.get(hashkey=hash_key)

        request = Mock()
        request.data = {
            "captcha_key": hash_key,
            "captcha_value": captcha.response.upper(),  # Uppercase
        }

        with patch("django.conf.settings.CAPTCHA_ENABLED", True):
            enforce_captcha_or_raise(request)

        assert not CaptchaStore.objects.filter(hashkey=hash_key).exists()
