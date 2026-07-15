# BE-MARKETING-03 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public, unauthenticated client self-registration endpoint, and fix the Founder/Basic plan-availability rule so it's enforced by the backend instead of only by frontend UI filtering.

**Architecture:** Part A adds `PublicClientRegistrationView` (new `APIView`, `AllowAny`) that reuses the existing `SalonCustomer` model and `send_customer_pwa_invite` magic-link flow. Part B adds a single new `FounderService.is_basic_blocked(tenant)` classmethod and wires it into the three places that currently let "basic" through unconditionally while Founder slots remain: checkout creation, billing overview, and initial registration.

**Tech Stack:** Django REST Framework, pytest/pytest-django, `django-simple-captcha` (via `enforce_captcha_or_raise`), DRF `ScopedRateThrottle`.

**IMPORTANT — no automatic commits:** Every "Commit" step below is written for reference only. Do **NOT** run `git add` / `git commit`. Leave all changes staged in the working tree, tested and green. Pablo commits and pushes everything himself.

---

## Part A — Public client self-registration endpoint

### Task A1: `PublicClientRegistrationSerializer`

**Files:**
- Modify: `core/serializers.py` (add new serializer near `SalonCustomerSerializer`, after line ~247)
- Test: `core/tests/test_public_client_registration.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/test_public_client_registration.py
import pytest
from core.serializers import PublicClientRegistrationSerializer


@pytest.mark.django_db
class TestPublicClientRegistrationSerializer:
    def test_valid_with_email_only(self):
        serializer = PublicClientRegistrationSerializer(
            data={"name": "Maria Silva", "email": "maria@example.com"}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["email"] == "maria@example.com"

    def test_valid_with_phone_only(self):
        serializer = PublicClientRegistrationSerializer(
            data={"name": "João Costa", "phone_number": "+351912345678"}
        )
        assert serializer.is_valid(), serializer.errors

    def test_missing_name_is_invalid(self):
        serializer = PublicClientRegistrationSerializer(
            data={"email": "maria@example.com"}
        )
        assert not serializer.is_valid()
        assert "name" in serializer.errors

    def test_missing_email_and_phone_is_invalid(self):
        serializer = PublicClientRegistrationSerializer(data={"name": "Maria Silva"})
        assert not serializer.is_valid()

    def test_email_is_normalized_to_lowercase(self):
        serializer = PublicClientRegistrationSerializer(
            data={"name": "Maria Silva", "email": "Maria@Example.COM"}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["email"] == "maria@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/test_public_client_registration.py -v`
Expected: FAIL with `ImportError: cannot import name 'PublicClientRegistrationSerializer'`

- [ ] **Step 3: Write the serializer**

Add to `core/serializers.py`, directly after the `SalonCustomerSerializer` class (after line ~247, before `class ScheduleSlotSerializer`):

```python
class PublicClientRegistrationSerializer(serializers.Serializer):
    """
    Serializer para auto-cadastro público de clientes (BE-MARKETING-03).
    Não é um ModelSerializer porque não expõe/aceita todos os campos de
    SalonCustomer (ex.: is_active, notes) — só os campos do formulário público.
    """

    name = serializers.CharField(max_length=120)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(
        max_length=32, required=False, allow_blank=True
    )
    marketing_opt_in = serializers.BooleanField(required=False, default=False)

    def validate_name(self, value):
        sanitized = sanitize_text_input(value, max_length=120)
        if not sanitized:
            raise serializers.ValidationError("Nome do cliente é obrigatório.")
        return sanitized

    def validate_email(self, value):
        if value:
            return value.strip().lower()
        return value

    def validate_phone_number(self, value):
        if not value:
            return value
        sanitized = sanitize_text_input(value, max_length=32)
        if not sanitized:
            return value
        try:
            validate_phone_number(sanitized)
        except Exception as exc:  # pragma: no cover
            raise serializers.ValidationError(str(exc)) from exc
        return sanitized

    def validate(self, data):
        email = data.get("email")
        phone = data.get("phone_number")
        if not email and not phone:
            raise serializers.ValidationError(
                "Informe pelo menos email ou telefone para o cliente."
            )
        return data
```

This reuses `sanitize_text_input` and `validate_phone_number`, both already imported at the top of `core/serializers.py` (used by `SalonCustomerSerializer` in the same file).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/test_public_client_registration.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit (Pablo does this — do not run)**

---

### Task A2: `UsersClientRegistrationThrottle`

**Files:**
- Modify: `users/throttling.py` (add after `UsersClientAccessLinkThrottle`, after line ~64)
- Modify: `salonix_backend/settings.py` (add `clients_registration` rate, after the `clients_access_link` block)
- Test: `users/tests/test_throttling.py` if it exists, otherwise inline test in `core/tests/test_public_client_registration.py` (see Task A4, which exercises this via the view)

- [ ] **Step 1: Write the throttle class**

Add to `users/throttling.py`, directly after `UsersClientAccessLinkThrottle` (after line ~64):

```python
class UsersClientRegistrationThrottle(_BaseUsersThrottle):
    scope = "clients_registration"

    def get_cache_key(self, request, view):
        # Per tenant (do slug na URL), para não penalizar outros tenants
        tenant_slug = view.kwargs.get("tenant_slug") if hasattr(view, "kwargs") else None
        if tenant_slug:
            ident = str(tenant_slug).lower()
            return self.cache_format % {"scope": self.scope, "ident": ident}
        return super().get_cache_key(request, view)
```

- [ ] **Step 2: Add the throttle rate to settings**

In `salonix_backend/settings.py`, immediately after the `"clients_access_link": env_get(...)` block (ends around line ~475, look for the line containing `else "10/hour"` that closes that block), add:

```python
        "clients_registration": env_get(
            "CLIENTS_REGISTRATION_RATE",
            (
                "50/hour"
                if (
                    "test" in sys.argv
                    or "pytest" in sys.modules
                    or ENV in ("dev", "staging", "uat")
                )
                else "10/hour"
            ),
        ),
```

- [ ] **Step 3: Verify Django loads settings without error**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Commit (Pablo does this — do not run)**

---

### Task A3: `PublicClientRegistrationView`

**Files:**
- Modify: `core/views.py` (add new view directly after `PublicTenantDetailView`, after line ~535)
- Modify: `core/urls.py` (register route in the "Public routes" section, after line ~127)
- Test: `core/tests/test_public_client_registration.py` (extend from Task A1)

- [ ] **Step 1: Write the failing tests**

Add to `core/tests/test_public_client_registration.py` (same file as Task A1):

```python
from unittest.mock import patch
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from users.models import Tenant
from core.models import SalonCustomer


@pytest.mark.django_db
class TestPublicClientRegistrationView:
    def setup_method(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name="Salão Teste",
            slug="salao-teste",
            plan_tier=Tenant.PLAN_BASIC,
            pwa_client_enabled=True,
            is_active=True,
        )
        self.url = reverse(
            "public_client_registration", kwargs={"tenant_slug": self.tenant.slug}
        )

    @patch("core.views.send_customer_pwa_invite")
    def test_valid_registration_creates_customer_and_sends_invite(self, mock_send):
        mock_send.return_value = True
        response = self.client.post(
            self.url,
            {"name": "Maria Silva", "email": "maria@example.com"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "customer_id" in response.data

        customer = SalonCustomer.objects.get(tenant=self.tenant, email="maria@example.com")
        assert customer.name == "Maria Silva"
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        assert kwargs["tenant"] == self.tenant
        assert kwargs["customer"] == customer
        assert kwargs["invited_by"] is None

    def test_tenant_not_found_returns_404(self):
        url = reverse(
            "public_client_registration", kwargs={"tenant_slug": "does-not-exist"}
        )
        response = self.client.post(url, {"name": "Maria Silva", "email": "m@x.com"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_inactive_tenant_returns_404(self):
        self.tenant.is_active = False
        self.tenant.save()
        response = self.client.post(self.url, {"name": "Maria Silva", "email": "m@x.com"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_tenant_without_pwa_client_returns_404(self):
        self.tenant.pwa_client_enabled = False
        self.tenant.plan_tier = Tenant.PLAN_BASIC
        self.tenant.save()
        response = self.client.post(self.url, {"name": "Maria Silva", "email": "m@x.com"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("core.views.send_customer_pwa_invite")
    def test_duplicate_email_same_tenant_returns_400(self, mock_send):
        mock_send.return_value = True
        SalonCustomer.objects.create(
            tenant=self.tenant, name="Existing", email="maria@example.com"
        )
        response = self.client.post(
            self.url, {"name": "Maria Silva", "email": "maria@example.com"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_send.assert_not_called()

    @patch("core.views.send_customer_pwa_invite")
    def test_duplicate_email_case_insensitive(self, mock_send):
        mock_send.return_value = True
        SalonCustomer.objects.create(
            tenant=self.tenant, name="Existing", email="maria@example.com"
        )
        response = self.client.post(
            self.url, {"name": "Maria Silva", "email": "Maria@Example.com"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("core.views.send_customer_pwa_invite")
    def test_same_email_different_tenants_allowed(self, mock_send):
        mock_send.return_value = True
        other_tenant = Tenant.objects.create(
            name="Outro Salão",
            slug="outro-salao",
            plan_tier=Tenant.PLAN_BASIC,
            pwa_client_enabled=True,
            is_active=True,
        )
        SalonCustomer.objects.create(
            tenant=other_tenant, name="Existing", email="maria@example.com"
        )
        response = self.client.post(
            self.url, {"name": "Maria Silva", "email": "maria@example.com"}
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_missing_name_returns_400(self):
        response = self.client.post(self.url, {"email": "maria@example.com"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(CAPTCHA_ENABLED=True, CAPTCHA_BYPASS_TOKEN="")
    def test_invalid_captcha_returns_400(self):
        response = self.client.post(
            self.url, {"name": "Maria Silva", "email": "maria@example.com"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("core.views.send_customer_pwa_invite")
    @override_settings(CAPTCHA_ENABLED=True, CAPTCHA_BYPASS_TOKEN="dev-bypass")
    def test_captcha_bypass_token_allows_registration(self, mock_send):
        mock_send.return_value = True
        response = self.client.post(
            self.url,
            {
                "name": "Maria Silva",
                "email": "maria@example.com",
                "captcha_value": "dev-bypass",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

    @patch("core.views.send_customer_pwa_invite")
    @override_settings(
        REST_FRAMEWORK={
            "DEFAULT_THROTTLE_CLASSES": [
                "rest_framework.throttling.ScopedRateThrottle",
            ],
            "DEFAULT_THROTTLE_RATES": {"clients_registration": "2/hour"},
        },
    )
    def test_rate_limit_returns_429(self, mock_send):
        mock_send.return_value = True
        from django.core.cache import cache

        cache.clear()
        self.client.post(self.url, {"name": "A", "email": "a1@example.com"})
        self.client.post(self.url, {"name": "B", "email": "a2@example.com"})
        response = self.client.post(self.url, {"name": "C", "email": "a3@example.com"})
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/test_public_client_registration.py -v`
Expected: FAIL — `NoReverseMatch: 'public_client_registration' is not a registered namespace/URL name`

- [ ] **Step 3: Write the view**

Add to `core/views.py`, directly after `PublicTenantDetailView` (after line ~535, before `class AppointmentCreateView`):

```python
class PublicClientRegistrationView(APIView):
    """
    POST /api/public/<tenant_slug>/clients/register/

    Endpoint PÚBLICO (sem autenticação) para auto-cadastro de clientes via
    link partilhado pelo tenant (BE-MARKETING-03).

    Reaproveita a criação de SalonCustomer + o mesmo magic link de acesso
    (send_customer_pwa_invite) já usado quando staff adiciona um cliente
    manualmente. Não coleta senha no formulário — o cliente define a senha
    depois, ao seguir o link recebido por email.
    """

    permission_classes = [AllowAny]
    throttle_classes = [UsersClientRegistrationThrottle]
    throttle_scope = "clients_registration"

    @extend_schema(
        request=PublicClientRegistrationSerializer,
        responses={
            201: OpenApiResponse(response=OpenApiTypes.OBJECT),
            400: OpenApiResponse(response=OpenApiTypes.OBJECT),
            404: OpenApiResponse(response=OpenApiTypes.OBJECT),
        },
        description="Auto-cadastro público de cliente via link do tenant.",
    )
    def post(self, request, tenant_slug):
        try:
            enforce_captcha_or_raise(request)
        except ValidationError:
            return Response(
                {"detail": "Captcha inválido."}, status=drf_status.HTTP_400_BAD_REQUEST
            )

        try:
            tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
        except Tenant.DoesNotExist:
            return Response(
                {"detail": "Tenant não encontrado."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        if not tenant.can_use_pwa_client():
            return Response(
                {"detail": "Tenant não encontrado."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        serializer = PublicClientRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data.get("email")
        if email and SalonCustomer.objects.filter(
            tenant=tenant, email__iexact=email
        ).exists():
            return Response(
                {"detail": "Este email já está registado."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        customer = SalonCustomer.objects.create(
            tenant=tenant,
            name=data["name"],
            email=email or None,
            phone_number=data.get("phone_number") or None,
            marketing_opt_in=data.get("marketing_opt_in", False),
        )

        try:
            send_customer_pwa_invite(tenant=tenant, customer=customer, invited_by=None)
        except Exception:  # pragma: no cover
            logger.error(
                "Public client registration invite dispatch failed",
                exc_info=True,
                extra={"tenant_id": tenant.id, "customer_id": customer.id},
            )

        return Response(
            {
                "customer_id": customer.id,
                "message": "Cadastro realizado. Verifique o seu email para aceder.",
            },
            status=drf_status.HTTP_201_CREATED,
        )
```

**Imports required in `core/views.py`** — check each is present at the top of the file before adding the view; add any missing ones next to the existing import blocks:
- `from core.models import SalonCustomer` (already imported — used by `SalonCustomerSerializer` usage elsewhere in the file)
- `from core.serializers import PublicClientRegistrationSerializer` (add to the existing `from core.serializers import (...)` block)
- `from users.models import Tenant` (already imported at module level — confirm; if only imported inside `PublicTenantDetailView.get`, add a top-level import instead, since the new view needs it too, or keep the local `from users.models import Tenant` inside `post()` for consistency with `PublicTenantDetailView`'s pattern of local imports)
- `from users.security import enforce_captcha_or_raise` (already imported — used by `PublicClientAccessLinkView`)
- `from notifications.services import send_customer_pwa_invite` (already imported — used by `SalonCustomerViewSet.perform_create`)
- `from users.throttling import UsersClientRegistrationThrottle` (add to the existing `from users.throttling import (...)` block, alongside `UsersClientAccessLinkThrottle`)

Use local `from users.models import Tenant` inside `post()` (matching `PublicTenantDetailView.get`'s existing pattern) rather than assuming a top-level import — grep first:

Run: `grep -n "^from users.models import Tenant$" core/views.py`

If it returns a top-level import, use `Tenant` directly. If not, add `from users.models import Tenant` as the first line inside `post()`.

- [ ] **Step 4: Register the URL**

In `core/urls.py`, add to the "Public routes" section, directly after the `public/clients/access-link/` entry (after line ~123):

```python
    path(
        "public/<slug:tenant_slug>/clients/register/",
        PublicClientRegistrationView.as_view(),
        name="public_client_registration",
    ),
```

Add `PublicClientRegistrationView` to the view import at the top of `core/urls.py` (find the existing `from core.views import (...)` block and add it there, alongside `PublicClientAccessLinkView`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest core/tests/test_public_client_registration.py -v`
Expected: 12 passed

- [ ] **Step 6: Commit (Pablo does this — do not run)**

---

### Task A4: Full-app sanity check for Part A

**Files:** None (verification only)

- [ ] **Step 1: Run the full core and users test suites**

Run: `pytest core/ users/ -q`
Expected: all passed, 0 failures (Part A touches no existing endpoints, so this should be a pure addition)

- [ ] **Step 2: Run `python manage.py check` once more**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

---

## Part B — Founder/Basic backend validation

### Task B1: `FounderService.is_basic_blocked`

**Files:**
- Modify: `users/services.py` (add classmethod to `FounderService`, after `can_assign_founder`, after line ~365)
- Test: `users/tests/test_founder_plan.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `users/tests/test_founder_plan.py`:

```python
class TestFounderIsBasicBlocked:
    @pytest.mark.django_db
    def test_blocked_when_vacancies_remain_and_tenant_has_no_history(self):
        tenant = Tenant.objects.create(
            name="Fresh Tenant", slug="fresh-tenant", is_founder=False
        )
        with patch.object(FounderService, "FOUNDER_LIMIT", 500):
            assert FounderService.is_basic_blocked(tenant=tenant) is True

    @pytest.mark.django_db
    def test_not_blocked_when_tenant_is_active_founder(self):
        tenant = Tenant.objects.create(
            name="Founder Tenant", slug="founder-tenant", is_founder=True
        )
        assert FounderService.is_basic_blocked(tenant=tenant) is False

    @pytest.mark.django_db
    @patch("payments.stripe_utils.get_plan_code_from_price")
    def test_not_blocked_when_tenant_left_founder_before(self, mock_get_plan):
        mock_get_plan.return_value = "founder"
        from payments.models import Subscription

        tenant = Tenant.objects.create(
            name="Ex Founder", slug="ex-founder", is_founder=False
        )
        owner = CustomUser.objects.create_user(
            username="ex_founder_owner",
            email="exfounder@example.com",
            password="pass",
            tenant=tenant,
        )
        Subscription.objects.create(
            user=owner,
            stripe_subscription_id="sub_ex_founder",
            price_id="price_founder_old",
            status="canceled",
        )
        assert FounderService.is_basic_blocked(tenant=tenant) is False

    @pytest.mark.django_db
    def test_not_blocked_when_founder_vacancies_exhausted(self):
        tenant = Tenant.objects.create(
            name="Fresh Tenant 2", slug="fresh-tenant-2", is_founder=False
        )
        with patch.object(FounderService, "FOUNDER_LIMIT", 0):
            assert FounderService.is_basic_blocked(tenant=tenant) is False

    @pytest.mark.django_db
    def test_blocked_with_no_tenant_and_vacancies_remain(self):
        with patch.object(FounderService, "FOUNDER_LIMIT", 500):
            assert FounderService.is_basic_blocked(tenant=None) is True

    @pytest.mark.django_db
    def test_not_blocked_with_no_tenant_and_vacancies_exhausted(self):
        with patch.object(FounderService, "FOUNDER_LIMIT", 0):
            assert FounderService.is_basic_blocked(tenant=None) is False
```

Add `from unittest.mock import patch` to the top of `users/tests/test_founder_plan.py` if not already present (it already is, per line 9 of the existing file — verify with `grep -n "from unittest.mock import patch" users/tests/test_founder_plan.py`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest users/tests/test_founder_plan.py::TestFounderIsBasicBlocked -v`
Expected: FAIL with `AttributeError: type object 'FounderService' has no attribute 'is_basic_blocked'`

- [ ] **Step 3: Implement the classmethod**

In `users/services.py`, add directly after the `can_assign_founder` method ends (after line ~365, before `class SMSRateLimiter:`):

```python
    @classmethod
    def is_basic_blocked(cls, tenant: Optional[Tenant] = None) -> bool:
        """
        Retorna True se o plano Basic NÃO deve estar disponível porque ainda
        há vagas Founder (das 500) e o tenant nunca teve Founder (nem é
        Founder atualmente).

        Regra de negócio: enquanto houver vagas Founder, só Founder é
        oferecido a tenants novos; Basic só aparece depois de esgotar as
        vagas. Um tenant que já é (ou já foi) Founder pode sempre escolher
        Basic livremente — essa transição nunca é bloqueada.
        """
        availability = cls.get_availability()
        if availability["remaining_count"] <= 0:
            return False

        if tenant is None:
            return True

        if tenant.is_founder:
            return False

        return cls.can_assign_founder(tenant=tenant)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest users/tests/test_founder_plan.py::TestFounderIsBasicBlocked -v`
Expected: 6 passed

- [ ] **Step 5: Commit (Pablo does this — do not run)**

---

### Task B2: Block Basic in `CreateCheckoutSession`

**Files:**
- Modify: `payments/views.py:79-120` (`CreateCheckoutSession.post`)
- Test: `payments/tests/test_founder_checkout.py` (extend)
- Fix (pre-existing tests that will regress): `payments/tests/test_payments_stripe.py`, `payments/tests/test_checkout_trial.py`

- [ ] **Step 1: Write the failing tests**

Add to `payments/tests/test_founder_checkout.py`, inside `class FounderCheckoutTest(TestCase)`:

```python
    @patch("payments.views.stripe_utils.get_stripe")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("users.services.FounderService.get_availability")
    def test_create_checkout_session_basic_blocked_when_founder_available(
        self, mock_availability, mock_get_price, mock_get_stripe
    ):
        mock_availability.return_value = {
            "total_limit": 500,
            "used_count": 0,
            "remaining_count": 500,
        }

        url = reverse("payments:create_checkout_session")
        response = self.client.post(url, {"plan": "basic"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("Founder", response.data["detail"])
        mock_get_price.assert_not_called()

    @patch("payments.views.stripe_utils.get_stripe")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("users.services.FounderService.get_availability")
    def test_create_checkout_session_basic_allowed_when_founder_exhausted(
        self, mock_availability, mock_get_price, mock_get_stripe
    ):
        mock_availability.return_value = {
            "total_limit": 500,
            "used_count": 500,
            "remaining_count": 0,
        }
        mock_get_price.return_value = "price_basic_123"

        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.url = "http://checkout.url"
        mock_stripe.checkout.Session.create.return_value = mock_session
        mock_get_stripe.return_value = mock_stripe

        url = reverse("payments:create_checkout_session")
        response = self.client.post(url, {"plan": "basic"})

        self.assertEqual(response.status_code, 200)

    @patch("payments.views.stripe_utils.get_stripe")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("users.services.FounderService.get_availability")
    def test_create_checkout_session_basic_allowed_for_active_founder_tenant(
        self, mock_availability, mock_get_price, mock_get_stripe
    ):
        # Vagas Founder ainda existem, mas o tenant JÁ É founder — deve poder
        # fazer downgrade voluntário para Basic sem bloqueio.
        mock_availability.return_value = {
            "total_limit": 500,
            "used_count": 1,
            "remaining_count": 499,
        }
        mock_get_price.return_value = "price_basic_123"

        self.tenant.is_founder = True
        self.tenant.save()

        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.url = "http://checkout.url"
        mock_stripe.checkout.Session.create.return_value = mock_session
        mock_get_stripe.return_value = mock_stripe

        url = reverse("payments:create_checkout_session")
        response = self.client.post(url, {"plan": "basic"})

        self.assertEqual(response.status_code, 200)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest payments/tests/test_founder_checkout.py -k basic_blocked -v`
Expected: FAIL — `test_create_checkout_session_basic_blocked_when_founder_available` gets `200` instead of `400` (no blocking logic exists yet)

- [ ] **Step 3: Implement the check**

In `payments/views.py`, inside `CreateCheckoutSession.post`, modify the existing block (lines ~100-113):

```python
        # 3) Permissão: somente OWNER ativo do tenant pode criar checkout
        tenant = _require_active_billing_owner(request.user)

        # Validar elegibilidade do Founder para este tenant específico

        if requested_plan == "founder":
            print(
                f"[CreateCheckoutSession] Tentativa de checkout Founder para tenant {tenant.slug}"
            )
            can_assign = FounderService.can_assign_founder(tenant=tenant)
            print(
                f"[CreateCheckoutSession] can_assign_founder({tenant.slug}) = {can_assign}"
            )
            if not can_assign:
                return Response(
                    {"detail": "O plano Founder não está mais disponível para você."},
                    status=400,
                )

        if requested_plan == "basic" and FounderService.is_basic_blocked(tenant=tenant):
            return Response(
                {"detail": "O plano Basic ainda não está disponível — restam vagas Founder."},
                status=400,
            )

        price_id = stripe_utils.get_price_id_for_plan(
            requested_plan, interval=requested_interval
        )
```

(`FounderService` is already imported at the top of `payments/views.py` — line 27: `from users.services import CreditService, FounderService`.)

- [ ] **Step 4: Run new tests to verify they pass**

Run: `pytest payments/tests/test_founder_checkout.py -v`
Expected: all passed (9 tests: 6 pre-existing + 3 new)

- [ ] **Step 5: Fix pre-existing tests that now regress**

Run: `pytest payments/tests/test_payments_stripe.py payments/tests/test_checkout_trial.py -v`
Expected at this point: several FAILs with 400 instead of 200, because these tests post `{"plan": "basic"}` without any Founder-exhaustion setup, and the test DB has no Founder subscriptions (so `FounderService.get_availability()` returns 500 remaining — basic gets blocked).

Fix by mocking Founder exhaustion in each affected test.

In `payments/tests/test_payments_stripe.py`, add this line as the first line inside each of these 4 test functions (right after the `def test_...(...):` signature, before any other code):

```python
    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 500, "remaining_count": 0},
    )
```

Apply to:
- `test_create_checkout_session_basic_plan` (starts line 104)
- `test_checkout_trial_suppressed_for_existing_subscription` (starts line 141)
- `test_checkout_trial_suppressed_for_other_user_in_same_tenant` (starts line 182)
- `test_checkout_trial_applied_for_new_customer` (starts line 240)

Each of these functions already receives `monkeypatch` as a parameter (check the signature — all 4 do, since they already use it for `stripe_utils.get_stripe`).

In `payments/tests/test_checkout_trial.py`, add a patcher in `CheckoutTrialTestCase.setUp` (the class applies to all 4 tests in the file uniformly), directly after the existing `self.patcher` block (after the `self.mock_stripe.Customer.create.return_value = {"id": "cus_test_123"}` line):

```python
        # BE-MARKETING-03: simula vagas Founder esgotadas para não bloquear
        # os testes de trial, que usam plan="basic" sem relação com Founder.
        self.founder_patcher = patch(
            "users.services.FounderService.get_availability",
            return_value={"total_limit": 500, "used_count": 500, "remaining_count": 0},
        )
        self.founder_patcher.start()
```

And in `tearDown`, add:

```python
        self.founder_patcher.stop()
```

`patch` is already imported at the top of `payments/tests/test_checkout_trial.py` (`from unittest.mock import MagicMock, patch`).

Also fix `payments/tests/test_payments_stripe.py::test_get_available_plans_returns_correct_auto_renew_and_credits` (line ~718) — its `MockFounderService` class replaces the whole `FounderService` and is missing the methods that `get_available_plans` will call after Task B3. Update the `MockFounderService` class (lines ~727-729) to:

```python
    class MockFounderService:
        @staticmethod
        def can_assign_founder(tenant=None):
            return True

        @staticmethod
        def get_availability():
            return {"total_limit": 500, "used_count": 0, "remaining_count": 500}

        @staticmethod
        def is_basic_blocked(tenant=None):
            return False
```

(This test's assertions don't check `is_available` on the basic plan, so `is_basic_blocked` always returning `False` is a safe, minimal stand-in — it just needs to exist so `get_available_plans`, after Task B3, doesn't raise `AttributeError`.)

- [ ] **Step 6: Run the fixed test files to verify they pass**

Run: `pytest payments/tests/test_payments_stripe.py payments/tests/test_checkout_trial.py -v`
Expected: all passed, 0 failures

- [ ] **Step 7: Commit (Pablo does this — do not run)**

---

### Task B3: Fix `BillingService.get_billing_overview` and `SubscriptionService.get_available_plans`

**Files:**
- Modify: `payments/services.py:265-341` (`SubscriptionService.get_available_plans`)
- Modify: `payments/services.py:806-812` (`BillingService.get_billing_overview`)
- Test: `payments/tests/test_payments_stripe.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `payments/tests/test_payments_stripe.py`, after `test_get_available_plans_returns_correct_auto_renew_and_credits`:

```python
@pytest.mark.django_db
def test_get_available_plans_basic_unavailable_when_founder_has_vacancies(monkeypatch):
    from payments.services import SubscriptionService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    tenant = Tenant.objects.create(
        name="Fresh Tenant Plans", slug="fresh-tenant-plans", is_founder=False
    )

    available_plans = SubscriptionService.get_available_plans(tenant=tenant)
    basic_plan = next((p for p in available_plans if p["plan_code"] == "basic"), None)

    assert basic_plan is not None
    assert basic_plan["is_available"] is False


@pytest.mark.django_db
def test_get_available_plans_basic_available_when_founder_exhausted(monkeypatch):
    from payments.services import SubscriptionService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 500, "remaining_count": 0},
    )

    tenant = Tenant.objects.create(
        name="Fresh Tenant Plans 2", slug="fresh-tenant-plans-2", is_founder=False
    )

    available_plans = SubscriptionService.get_available_plans(tenant=tenant)
    basic_plan = next((p for p in available_plans if p["plan_code"] == "basic"), None)

    assert basic_plan is not None
    assert basic_plan["is_available"] is True


@pytest.mark.django_db
def test_billing_overview_passes_tenant_to_available_plans(monkeypatch, auth_client):
    from payments.services import BillingService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    c, user = auth_client()
    tenant = Tenant.objects.create(
        name="Billing Overview Tenant", slug="billing-overview-tenant", is_founder=False
    )
    user.tenant = tenant
    user.save()

    overview = BillingService.get_billing_overview(user)
    basic_plan = next(
        (p for p in overview["available_plans"] if p["plan_code"] == "basic"), None
    )

    assert basic_plan is not None
    assert basic_plan["is_available"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest payments/tests/test_payments_stripe.py -k "basic_unavailable_when_founder or basic_available_when_founder_exhausted or billing_overview_passes_tenant" -v`
Expected: FAIL — `basic_plan["is_available"]` is `True` in the first test (currently hardcoded `True`), and the third test fails because `get_billing_overview` never passes `tenant=` so it can't distinguish.

- [ ] **Step 3: Fix `get_available_plans`**

In `payments/services.py`, inside `get_available_plans` (around line ~305), change:

```python
                    "is_current": plan_code == current_plan,
                    "can_upgrade": i > current_index,
                    "is_available": True,  # Planos padrão sempre disponíveis
                }
            )
```

to:

```python
                    "is_current": plan_code == current_plan,
                    "can_upgrade": i > current_index,
                    "is_available": (
                        not FounderService.is_basic_blocked(tenant=tenant)
                        if plan_code == "basic"
                        else True
                    ),
                }
            )
```

(`FounderService` is already imported locally inside this method via `from users.services import FounderService`, a few lines above this loop.)

- [ ] **Step 4: Fix `get_billing_overview`**

In `payments/services.py`, inside `BillingService.get_billing_overview` (around line ~806-810), change:

```python
        current_subscription = SubscriptionService.get_current_subscription(user)
        available_plans = SubscriptionService.get_available_plans(
            current_subscription["plan_code"] if current_subscription else None
        )
```

to:

```python
        current_subscription = SubscriptionService.get_current_subscription(user)
        available_plans = SubscriptionService.get_available_plans(
            current_subscription["plan_code"] if current_subscription else None,
            tenant=getattr(user, "tenant", None),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest payments/tests/test_payments_stripe.py -v`
Expected: all passed (including the 2 pre-existing Founder-availability tests, fixed in Task B2 Step 5, plus the 3 new ones from this task)

- [ ] **Step 6: Commit (Pablo does this — do not run)**

---

### Task B4: Fix `UserRegistrationSerializer.create`

**Files:**
- Modify: `users/serializers.py:262-285` (`UserRegistrationSerializer.create`)
- Test: `users/tests/test_founder_plan.py` (extend)
- Fix (pre-existing tests that will regress): `users/tests/test_auth.py`, `tests/test_business_logging.py`, `users/tests/test_users_security_throttle.py`

- [ ] **Step 1: Write the failing tests**

Add to `users/tests/test_founder_plan.py`:

```python
@pytest.mark.django_db
class TestRegistrationBasicBlockedByFounder:
    def test_registration_blocked_when_plan_omitted_and_founder_available(self):
        from django.urls import reverse
        from rest_framework.test import APIClient

        client = APIClient()
        url = reverse("register")
        response = client.post(
            url,
            {
                "username": "newowner",
                "email": "newowner@example.com",
                "password": "StrongPass123",
            },
        )
        assert response.status_code == 400

    def test_registration_allowed_with_explicit_founder_plan(self):
        from django.urls import reverse
        from rest_framework.test import APIClient

        client = APIClient()
        url = reverse("register")
        response = client.post(
            url,
            {
                "username": "newfounder",
                "email": "newfounder@example.com",
                "password": "StrongPass123",
                "plan": "founder",
            },
        )
        assert response.status_code == 201

    def test_registration_allowed_with_basic_when_founder_exhausted(self):
        from unittest.mock import patch
        from django.urls import reverse
        from rest_framework.test import APIClient

        client = APIClient()
        url = reverse("register")
        with patch(
            "users.services.FounderService.get_availability",
            return_value={"total_limit": 500, "used_count": 500, "remaining_count": 0},
        ):
            response = client.post(
                url,
                {
                    "username": "newbasic",
                    "email": "newbasic@example.com",
                    "password": "StrongPass123",
                    "plan": "basic",
                },
            )
        assert response.status_code == 201
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest users/tests/test_founder_plan.py::TestRegistrationBasicBlockedByFounder -v`
Expected: `test_registration_blocked_when_plan_omitted_and_founder_available` FAILs (gets 201 instead of 400); the other two already pass (no regression there yet).

- [ ] **Step 3: Implement the check**

In `users/serializers.py`, inside `UserRegistrationSerializer.create` (around line ~273-280), change:

```python
        # Verifica plano Founder
        is_founder = False
        if data.get("plan") == "founder":
            if not FounderService.can_assign_founder():
                raise serializers.ValidationError(
                    {"plan": "O plano Founder não está mais disponível."}
                )
            is_founder = True
```

to:

```python
        # Verifica plano Founder
        is_founder = False
        requested_plan = data.get("plan", "basic")
        if requested_plan == "founder":
            if not FounderService.can_assign_founder():
                raise serializers.ValidationError(
                    {"plan": "O plano Founder não está mais disponível."}
                )
            is_founder = True
        elif requested_plan == "basic" and FounderService.is_basic_blocked():
            raise serializers.ValidationError(
                {"plan": "O plano Basic ainda não está disponível — restam vagas Founder."}
            )
```

(No `tenant` argument is passed to `is_basic_blocked` here — the tenant doesn't exist yet at this point in registration, matching the existing `can_assign_founder()` call a few lines above, which is also called without `tenant=`.)

- [ ] **Step 4: Run new tests to verify they pass**

Run: `pytest users/tests/test_founder_plan.py::TestRegistrationBasicBlockedByFounder -v`
Expected: 3 passed

- [ ] **Step 5: Fix pre-existing tests that now regress**

Run: `pytest users/tests/test_auth.py tests/test_business_logging.py users/tests/test_users_security_throttle.py -v`
Expected at this point: several FAILs (201 expected, 400 received) — the same rule now blocks any registration test that omits `plan` while Founder still has vacancies (test DB always starts with 0 Founder subscriptions, so vacancies always "remain" unless a test says otherwise).

Fix each by adding `"plan": "founder"` to the payload (this doesn't change what these tests actually verify — `plan_tier` stays `"basic"` for Founder tenants too, since Founder is a flag on top of the Basic tier, not a separate `plan_tier` value; see `Tenant.plan_tier` comment in `FounderService`'s class docstring).

In `users/tests/test_auth.py`:

- `test_successful_registration` (line ~25-29): add `"plan": "founder"` to the payload dict.
- `test_registration_generates_unique_slug` (line ~71-84): add `"plan": "founder"` to both `first_payload` and `second_payload`.

```python
    def test_successful_registration(self):
        payload = {
            "username": "lucas",
            "email": "lucas@salonix.com",
            "password": "strongpassword123",
            "plan": "founder",
        }
```

```python
    def test_registration_generates_unique_slug(self):
        first_payload = {
            "username": "ana",
            "email": "ana@example.com",
            "password": "strongpass123",
            "salon_name": "Studio Glam",
            "plan": "founder",
        }
        second_payload = {
            "username": "carla",
            "email": "carla@example.com",
            "password": "anotherpass123",
            "salon_name": "Studio Glam",
            "plan": "founder",
        }
```

In `tests/test_business_logging.py`, `test_user_registration_logs` (around line 157-162): add `"plan": "founder"` to `data`:

```python
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "strongpassword123",
            "salon_name": "New Salon Log",
            "plan": "founder",
        }
```

In `users/tests/test_users_security_throttle.py`, `test_register_is_throttled` (around line 84-95): add `"plan": "founder"` to all 3 payloads (`p`, `p2`, `p3`):

```python
    p = {
        "username": "x",
        "email": "x1@example.com",
        "password": "StrongPass123",
        "plan": "founder",
    }
    r1 = client.post(url, data=p)
    assert r1.status_code == status.HTTP_201_CREATED
    p2 = {
        "username": "y",
        "email": "x2@example.com",
        "password": "StrongPass123",
        "plan": "founder",
    }
    r2 = client.post(url, data=p2)
    assert r2.status_code == status.HTTP_201_CREATED
    p3 = {
        "username": "z",
        "email": "x3@example.com",
        "password": "StrongPass123",
        "plan": "founder",
    }
```

(The 3rd request, `p3`, is expected to hit the throttle limit at 429 regardless of plan — that assertion is unaffected.)

- [ ] **Step 6: Run the fixed test files to verify they pass**

Run: `pytest users/tests/test_auth.py tests/test_business_logging.py users/tests/test_users_security_throttle.py -v`
Expected: all passed, 0 failures

- [ ] **Step 7: Commit (Pablo does this — do not run)**

---

### Task B5: Full regression sweep

**Files:** None (verification only)

- [ ] **Step 1: Run the complete backend test suite**

Run: `pytest -q`
Expected: all passed, 0 failures, 0 errors (matches or exceeds the 937 passed / 5 skipped baseline from before this task — plus all new tests added in Tasks A1-B4)

- [ ] **Step 2: Run `python manage.py check`**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Update `docs/to_see.md`**

Remove (or mark as resolved) the entry "Backend: regra Founder/Basic só é aplicada no frontend, nunca validada no backend" in `/Users/pablo/Project/Salonix/to_see.md` — this task closes all 4 suggested actions listed there. Do not delete the historical context; instead prepend `**[RESOLVIDO em BE-MARKETING-03]**` to the entry's heading, so the investigation history is preserved for reference.

- [ ] **Step 4: Do NOT commit**

Leave everything staged/modified in the working tree. Report the final test counts to Pablo and stop — he commits and pushes both the code changes and the `to_see.md` update himself.

---

## Self-Review Notes (for the plan author, not a task)

- **Spec coverage:** All 8 items from the spec's "Testes" section (Part A) are covered across Tasks A1/A3. All 6 Founder/Basic test bullets are covered across Tasks B1-B4. The spec's "Fora de escopo" items (FEW, MOB, Pro plan) are correctly untouched.
- **Regression risk called out explicitly:** Task B2 Step 5 and Task B4 Step 5 enumerate every pre-existing test file this change breaks, with exact fixes — this was verified by grepping the whole backend for every call site that posts `plan=basic` (checkout) or omits `plan` (registration) before writing the plan, not guessed.
- **Type/name consistency:** `FounderService.is_basic_blocked(tenant=...)` is defined once in Task B1 and consumed identically (same signature) in Tasks B2, B3, and B4.
