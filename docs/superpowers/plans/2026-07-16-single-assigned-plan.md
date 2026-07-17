# Plano Único Atribuído no Registo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Stripe-subscription-status-based "single plan display" rule with a simpler, universal one: the tenant's plan (Founder or TimelyOne) is decided once at registration (`tenant.is_founder`/`tenant.plan_tier`) and is always the only plan shown or checked out against, in every state (trial, promotional, active subscription).

**Architecture:** Backend changes concentrate in `SubscriptionService.get_available_plans` (drop the `subscription_status` parameter, always filter by tenant's assigned plan), `UserRegistrationSerializer.create` (server decides `is_founder`, ignores client `plan` input), and `CreateCheckoutSession.post` (same — server decides the plan, client only controls `interval`). Frontend changes collapse `RegisterCheckout.jsx`/`PlanOnboarding.jsx` from a multi-card picker to a single, non-interactive plan card + the existing monthly/annual toggle.

**Tech Stack:** Django REST Framework, pytest/pytest-django (backend); React, Jest (frontend web).

**IMPORTANT — no automatic commits:** Every "Commit" step below is written for reference only. Do **NOT** run `git add` / `git commit`. Leave all changes in the working tree, tested and green. Pablo commits and pushes everything himself.

---

## Part 1 — Backend (`salonix-backend`, branch `be-plans-04-single-assigned-plan`)

### Task 1: Simplify `get_available_plans` — always filter by tenant's assigned plan

**Files:**
- Modify: `payments/services.py:264-363` (`SubscriptionService.get_available_plans`)
- Test: `payments/tests/test_payments_stripe.py`

- [ ] **Step 1: Write the failing tests**

Replace the existing `test_get_available_plans_shows_only_current_when_active` and `test_get_available_plans_shows_only_current_when_past_due` tests (they encode the old Stripe-status-driven rule) with tests for the new tenant-driven rule. Find both in `payments/tests/test_payments_stripe.py` and replace them with:

```python
@pytest.mark.django_db
def test_get_available_plans_shows_only_assigned_plan_for_basic_tenant(monkeypatch):
    from payments.services import SubscriptionService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    tenant = Tenant.objects.create(
        name="Basic Assigned Tenant", slug="basic-assigned-tenant", is_founder=False
    )

    available_plans = SubscriptionService.get_available_plans(tenant=tenant)

    assert len(available_plans) == 1
    assert available_plans[0]["plan_code"] == "basic"


@pytest.mark.django_db
def test_get_available_plans_shows_only_assigned_plan_for_founder_tenant():
    from payments.services import SubscriptionService
    from users.models import Tenant

    tenant = Tenant.objects.create(
        name="Founder Assigned Tenant", slug="founder-assigned-tenant", is_founder=True
    )

    available_plans = SubscriptionService.get_available_plans(tenant=tenant)

    assert len(available_plans) == 1
    assert available_plans[0]["plan_code"] == "founder"


@pytest.mark.django_db
def test_get_available_plans_shows_only_assigned_plan_regardless_of_subscription_status(
    monkeypatch,
):
    """A promotional-billing tenant (no Stripe subscription at all) still only
    sees their assigned plan — the rule no longer depends on Stripe status."""
    from payments.services import SubscriptionService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    tenant = Tenant.objects.create(
        name="Promotional Tenant",
        slug="promotional-tenant",
        is_founder=False,
        billing_mode=Tenant.BILLING_MODE_PROMOTIONAL,
    )

    available_plans = SubscriptionService.get_available_plans(tenant=tenant)

    assert len(available_plans) == 1
    assert available_plans[0]["plan_code"] == "basic"


@pytest.mark.django_db
def test_get_available_plans_returns_full_list_when_no_tenant(monkeypatch):
    """Without a tenant (e.g. a hypothetical pre-registration lookup), the full
    eligible list is still returned — there's no assignment to filter by yet."""
    from payments.services import SubscriptionService

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    available_plans = SubscriptionService.get_available_plans(tenant=None)

    plan_codes = {p["plan_code"] for p in available_plans}
    assert "basic" in plan_codes
    assert "founder" in plan_codes
```

Now update the four existing tests that assumed the old "shows all when trialing/no subscription" behavior. Find and replace each:

`test_get_available_plans_shows_all_when_trialing` — DELETE this test entirely (the "trialing" distinction no longer exists; superseded by `test_get_available_plans_shows_only_assigned_plan_for_basic_tenant` above, which doesn't pass any subscription-status concept at all since the parameter is being removed).

`test_get_available_plans_shows_all_when_no_subscription` — DELETE this test entirely (superseded by `test_get_available_plans_returns_full_list_when_no_tenant` above — the only case that still returns the full list is `tenant=None`, not "no subscription").

`test_get_available_plans_returns_correct_auto_renew_and_credits` (around line 734) — currently asserts both `basic_plan` and `founder_plan` are present simultaneously for a tenant with no `is_founder` set explicitly. Change the assertions: since this test's `tenant` has `is_founder` defaulting to `False`, only `basic_plan` will be returned now. Update:

```python
    # Procura pelos planos específicos
    basic_plan = next((p for p in available_plans if p["plan_code"] == "basic"), None)
    pro_plan = next((p for p in available_plans if p["plan_code"] == "pro"), None)
    founder_plan = next(
        (p for p in available_plans if p["plan_code"] == "founder"), None
    )

    # Validações
    assert basic_plan is not None
    assert basic_plan["comm_auto_renew"] is False
    assert basic_plan["credits_included"] == 5

    # BE-PLANS-01 (#481): Pro bloqueado não aparece na listagem pública
    assert pro_plan is None

    assert founder_plan is not None
    assert founder_plan["comm_auto_renew"] is False
    assert founder_plan["credits_included"] == 2
```

to:

```python
    # Procura pelo plano atribuído (tenant.is_founder=False por default)
    basic_plan = next((p for p in available_plans if p["plan_code"] == "basic"), None)

    # Validações
    assert len(available_plans) == 1
    assert basic_plan is not None
    assert basic_plan["comm_auto_renew"] is False
    assert basic_plan["credits_included"] == 5
```

Also update the `MockFounderService` in this same test — it no longer needs `is_basic_blocked` to gate anything meaningful for this test's assertions, but leave it in place unchanged (still needed so `get_available_plans` doesn't error on the call, since the method still calls `FounderService.is_basic_blocked`/`can_assign_founder` internally to compute `is_available` per-plan, even though the new filter happens after).

`test_get_available_plans_uses_public_plan_names` (around line 783) — same fix. The test creates a tenant with no `is_founder` set (defaults `False`), so only `basic_plan` will be returned. Change:

```python
    available_plans = SubscriptionService.get_available_plans(tenant=tenant)
    basic_plan = next((p for p in available_plans if p["plan_code"] == "basic"), None)
    founder_plan = next((p for p in available_plans if p["plan_code"] == "founder"), None)

    assert basic_plan is not None
    assert basic_plan["name"] == "TimelyOne"
    assert founder_plan is not None
    assert founder_plan["name"] == "TimelyOne Founder"
```

to two separate tests — keep this one asserting the basic tenant's name, and add a sibling for a founder tenant:

```python
    available_plans = SubscriptionService.get_available_plans(tenant=tenant)
    basic_plan = next((p for p in available_plans if p["plan_code"] == "basic"), None)

    assert basic_plan is not None
    assert basic_plan["name"] == "TimelyOne"


@pytest.mark.django_db
def test_get_available_plans_uses_public_plan_name_for_founder():
    from payments.services import SubscriptionService
    from users.models import Tenant

    tenant = Tenant.objects.create(
        name="Founder Naming Tenant", slug="founder-naming-tenant", is_founder=True
    )

    available_plans = SubscriptionService.get_available_plans(tenant=tenant)
    founder_plan = next(
        (p for p in available_plans if p["plan_code"] == "founder"), None
    )

    assert founder_plan is not None
    assert founder_plan["name"] == "TimelyOne Founder"
```

(Give the new sibling test a distinct name as shown — `test_get_available_plans_uses_public_plan_name_for_founder` — placed directly after the modified `test_get_available_plans_uses_public_plan_names`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest payments/tests/test_payments_stripe.py -v 2>&1 | tail -60`
Expected: several FAILs — the new tests fail because `get_available_plans` still returns the full list for a basic/founder tenant (old behavior); the modified existing tests fail because they now expect `len == 1` but still get 2.

- [ ] **Step 3: Simplify the implementation**

In `payments/services.py`, change the `get_available_plans` signature from:

```python
    @classmethod
    def get_available_plans(
        cls,
        current_plan: Optional[str] = None,
        tenant: Optional["Tenant"] = None,
        subscription_status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
```

to:

```python
    @classmethod
    def get_available_plans(
        cls,
        current_plan: Optional[str] = None,
        tenant: Optional["Tenant"] = None,
    ) -> List[Dict[str, Any]]:
```

Update the docstring's `Args:` block — remove the `subscription_status` line entirely, and update the `tenant` line to:

```python
            tenant: Tenant do usuário. Quando presente, a lista devolvida é
                sempre filtrada para conter apenas o plano já atribuído ao
                tenant ("founder" se tenant.is_founder, senão
                tenant.plan_tier) — independentemente de haver ou não uma
                subscrição Stripe ativa. Quando None (ainda não existe
                tenant, ex.: pré-registo), devolve a lista completa de
                planos elegíveis.
```

At the very end of the method, replace:

```python
        only_current = current_plan is not None and subscription_status in (
            "active",
            "past_due",
        )
        if only_current:
            plans = [p for p in plans if p["is_current"]]

        return plans
```

with:

```python
        if tenant is not None:
            assigned_plan = "founder" if tenant.is_founder else tenant.plan_tier
            filtered = [p for p in plans if p["plan_code"] == assigned_plan]
            if filtered:
                plans = filtered

        return plans
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest payments/tests/test_payments_stripe.py -v 2>&1 | tail -60`
Expected: all pass.

- [ ] **Step 5: Do NOT commit**

---

### Task 2: Update call sites to drop `subscription_status`

**Files:**
- Modify: `payments/services.py:825-835` (`BillingService.get_billing_overview`)
- Modify: `payments/views.py` (`AvailablePlansView.get`)
- Test: `payments/tests/test_payments_stripe.py`

- [ ] **Step 1: Write the failing test**

Add to `payments/tests/test_payments_stripe.py`:

```python
@pytest.mark.django_db
def test_billing_overview_shows_only_assigned_plan_for_promotional_tenant(
    monkeypatch, auth_client
):
    from payments.services import BillingService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    c, user = auth_client()
    tenant = Tenant.objects.create(
        name="Overview Promotional Tenant",
        slug="overview-promotional-tenant",
        is_founder=False,
        billing_mode=Tenant.BILLING_MODE_PROMOTIONAL,
    )
    user.tenant = tenant
    user.save()

    overview = BillingService.get_billing_overview(user)

    assert len(overview["available_plans"]) == 1
    assert overview["available_plans"][0]["plan_code"] == "basic"
```

This is the key regression test for the bug that motivated this whole redesign — a promotional-billing tenant (no Stripe subscription, `get_current_subscription` returns `None` for them) now correctly sees only their assigned plan.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest payments/tests/test_payments_stripe.py::test_billing_overview_shows_only_assigned_plan_for_promotional_tenant -v`
Expected: FAIL — `assert 2 == 1` (old behavior: promotional tenant with no subscription still sees both plans).

Wait — this will actually fail with a `TypeError` first, since `get_billing_overview` still tries to pass `subscription_status=` to `get_available_plans`, which no longer accepts that parameter (removed in Task 1). Either error confirms the fix is needed.

- [ ] **Step 3: Update `get_billing_overview`**

In `payments/services.py`, find `BillingService.get_billing_overview` and change:

```python
        current_subscription = SubscriptionService.get_current_subscription(user)
        available_plans = SubscriptionService.get_available_plans(
            current_subscription["plan_code"] if current_subscription else None,
            tenant=getattr(user, "tenant", None),
            subscription_status=(
                current_subscription["status"] if current_subscription else None
            ),
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

- [ ] **Step 4: Update `AvailablePlansView`**

In `payments/views.py`, find `AvailablePlansView.get` and change:

```python
            current_subscription = SubscriptionService.get_current_subscription(
                request.user
            )
            current_plan = (
                current_subscription["plan_code"] if current_subscription else None
            )
            subscription_status = (
                current_subscription["status"] if current_subscription else None
            )

            tenant = getattr(request.user, "tenant", None)
            plans = SubscriptionService.get_available_plans(
                current_plan, tenant=tenant, subscription_status=subscription_status
            )
```

to:

```python
            current_subscription = SubscriptionService.get_current_subscription(
                request.user
            )
            current_plan = (
                current_subscription["plan_code"] if current_subscription else None
            )

            tenant = getattr(request.user, "tenant", None)
            plans = SubscriptionService.get_available_plans(current_plan, tenant=tenant)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest payments/tests/test_payments_stripe.py -v 2>&1 | tail -20`
Expected: all pass.

- [ ] **Step 6: Search for any other reference to the removed parameter**

Run: `grep -rn "subscription_status" payments/ users/ --include="*.py"`
Expected: no remaining references (confirms the parameter was fully removed, not left dangling anywhere).

- [ ] **Step 7: Do NOT commit**

---

### Task 3: `UserRegistrationSerializer.create` — server decides `is_founder`, ignores client `plan`

**Files:**
- Modify: `users/serializers.py:262-322` (`UserRegistrationSerializer.create`)
- Test: `users/tests/test_founder_plan.py`

- [ ] **Step 1: Write the failing tests**

Find `TestRegistrationBasicBlockedByFounder` in `users/tests/test_founder_plan.py` and replace its 3 existing tests with:

```python
@pytest.mark.django_db
class TestRegistrationAssignsPlanServerSide:
    def test_registration_assigns_founder_when_vacancies_remain_regardless_of_requested_plan(
        self,
    ):
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
                "plan": "basic",
            },
        )
        assert response.status_code == 201
        tenant_slug = response.data["tenant"]["slug"]
        tenant = Tenant.objects.get(slug=tenant_slug)
        assert tenant.is_founder is True

    def test_registration_assigns_founder_when_plan_omitted_and_vacancies_remain(self):
        from django.urls import reverse
        from rest_framework.test import APIClient

        client = APIClient()
        url = reverse("register")
        response = client.post(
            url,
            {
                "username": "newowner2",
                "email": "newowner2@example.com",
                "password": "StrongPass123",
            },
        )
        assert response.status_code == 201
        tenant_slug = response.data["tenant"]["slug"]
        tenant = Tenant.objects.get(slug=tenant_slug)
        assert tenant.is_founder is True

    def test_registration_assigns_basic_when_founder_exhausted_regardless_of_requested_plan(
        self,
    ):
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
                    "plan": "founder",
                },
            )
        assert response.status_code == 201
        tenant_slug = response.data["tenant"]["slug"]
        tenant = Tenant.objects.get(slug=tenant_slug)
        assert tenant.is_founder is False
```

Note: these tests need `Tenant` imported at the top of `users/tests/test_founder_plan.py` — check with `grep -n "^from users.models import" users/tests/test_founder_plan.py` first; it already imports `Tenant` (confirmed from earlier work in this file), so no new import needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest users/tests/test_founder_plan.py::TestRegistrationAssignsPlanServerSide -v`
Expected: FAIL — `test_registration_assigns_founder_when_vacancies_remain_regardless_of_requested_plan` fails because the current code still honors the client's `plan="basic"` (creates a non-founder tenant); `test_registration_assigns_basic_when_founder_exhausted_regardless_of_requested_plan` fails because the current code would reject `plan="founder"` with a 400 validation error when founder is exhausted (current behavior: raises `ValidationError`), not silently downgrade to basic.

- [ ] **Step 3: Update the implementation**

In `users/serializers.py`, inside `UserRegistrationSerializer.create`, change:

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

to:

```python
        # BE-PLANS-04: o plano é sempre decidido pelo servidor, com base na
        # disponibilidade de vagas Founder no momento do registo — o campo
        # "plan" enviado pelo cliente (se houver) é ignorado para esta
        # decisão.
        is_founder = FounderService.can_assign_founder()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest users/tests/test_founder_plan.py -v 2>&1 | tail -40`
Expected: all pass.

- [ ] **Step 5: Do NOT commit**

---

### Task 4: `CreateCheckoutSession.post` — server decides the plan, client only controls `interval`

**Files:**
- Modify: `payments/views.py` (`CreateCheckoutSession.post`)
- Test: `payments/tests/test_founder_checkout.py`

- [ ] **Step 1: Update the existing tests first (TDD note: these edits ARE the failing-test step)**

The tests in `payments/tests/test_founder_checkout.py` currently send an explicit `plan` in the POST body and expect the server to honor/validate it. Under the new design, the server ignores the client's `plan` and always uses `tenant.is_founder`/`tenant.plan_tier`. Update `FounderCheckoutTest` in `payments/tests/test_founder_checkout.py`:

`test_create_checkout_session_founder_allowed` — add `self.tenant.is_founder = True; self.tenant.save()` before the request, and simplify the payload (the `plan` key becomes irrelevant, but leaving it is harmless — remove it for clarity per the new contract):

```python
    @patch("payments.views.stripe_utils.get_stripe")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("users.services.FounderService.can_assign_founder")
    def test_create_checkout_session_founder_allowed(
        self, mock_can_assign, mock_get_price, mock_get_stripe
    ):
        mock_can_assign.return_value = True
        mock_get_price.return_value = "price_founder_123"

        self.tenant.is_founder = True
        self.tenant.save()

        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.url = "http://checkout.url"
        mock_stripe.checkout.Session.create.return_value = mock_session
        mock_get_stripe.return_value = mock_stripe

        url = reverse("payments:create_checkout_session")

        response = self.client.post(url, {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["checkout_url"], "http://checkout.url")

        # Verify metadata
        args, kwargs = mock_stripe.checkout.Session.create.call_args
        self.assertEqual(kwargs["metadata"]["plan_code"], "founder")
```

`test_create_checkout_session_founder_annual` — same `is_founder = True` addition, and the payload keeps only `interval`:

```python
    @patch("payments.views.stripe_utils.get_stripe")
    @patch("payments.views.stripe_utils.get_price_id_for_plan")
    @patch("users.services.FounderService.can_assign_founder")
    def test_create_checkout_session_founder_annual(
        self, mock_can_assign, mock_get_price, mock_get_stripe
    ):
        mock_can_assign.return_value = True
        mock_get_price.return_value = "price_founder_yearly_123"

        self.tenant.is_founder = True
        self.tenant.save()

        mock_stripe = MagicMock()
        mock_session = MagicMock()
        mock_session.url = "http://checkout.url"
        mock_stripe.checkout.Session.create.return_value = mock_session
        mock_get_stripe.return_value = mock_stripe

        url = reverse("payments:create_checkout_session")
        data = {"interval": "annual"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["checkout_url"], "http://checkout.url")

        # Verify get_price_id_for_plan was called with interval='annual'
        mock_get_price.assert_called_with("founder", interval="annual")
```

`test_create_checkout_session_founder_denied` — same `is_founder = True` addition (the tenant is assigned Founder, but eligibility re-check via the mocked `can_assign_founder` returns False — an edge case, e.g. Founder status revoked mid-session):

```python
    @patch("payments.views.stripe_utils.get_stripe")
    @patch("users.services.FounderService.can_assign_founder")
    def test_create_checkout_session_founder_denied(
        self, mock_can_assign, mock_get_stripe
    ):
        mock_can_assign.return_value = False

        self.tenant.is_founder = True
        self.tenant.save()

        url = reverse("payments:create_checkout_session")

        response = self.client.post(url, {})

        self.assertEqual(response.status_code, 400)
        self.assertIn("não está mais disponível", response.data["detail"])
```

`test_create_checkout_session_basic_blocked_when_founder_available` and `test_create_checkout_session_basic_allowed_when_founder_exhausted` — no changes needed. `self.tenant.is_founder` is `False` in `setUp`, so the server-derived plan is naturally `"basic"` (from `tenant.plan_tier`, which defaults to `Tenant.PLAN_BASIC`) in both — the same as what these tests already exercise. The `{"plan": "basic"}` payload they send becomes inert (ignored by the server) but doesn't need to be removed — leave these two tests exactly as they are.

`test_create_checkout_session_basic_allowed_for_active_founder_tenant` — **DELETE this test.** It exercises a capability (a Founder tenant using checkout to voluntarily "downgrade" to Basic by sending `{"plan": "basic"}`) that no longer exists under the new design — checkout always uses the tenant's already-assigned plan (`tenant.is_founder=True` → always "founder"), so there is no client-driven way to request a different plan via checkout anymore. Leaving Founder is only possible via subscription cancellation (Stripe portal → webhook sets `is_founder=False`), which is covered by the separate webhook tests (`test_webhook_subscription_deleted_removes_founder_status`) already in this file, unaffected by this change.

- [ ] **Step 2: Run the modified tests to verify they fail against the current implementation**

Run: `pytest payments/tests/test_founder_checkout.py -v 2>&1 | tail -40`
Expected: `test_create_checkout_session_founder_allowed`, `test_create_checkout_session_founder_annual`, `test_create_checkout_session_founder_denied` all FAIL — the current view still reads `plan` from `request.data` (defaulting to `"basic"` when absent), so with an empty/interval-only payload it treats the request as `plan=basic`, not `founder`, giving a 200 with `plan_code=basic` metadata (wrong) or skipping the founder validation branch entirely (for the denied test, no validation triggers because `requested_plan != "founder"`, so it returns 200 instead of the expected 400).

- [ ] **Step 3: Update the view implementation**

In `payments/views.py`, inside `CreateCheckoutSession.post`, change:

```python
        requested_plan = (request.data.get("plan") or "basic").lower()
        requested_interval = (request.data.get("interval") or "monthly").lower()

        # BE-PLANS-01 (#481): plano Pro bloqueado para novas subscrições.
        allowed_plans = {
            "basic",
            "founder",
        }

        if requested_plan not in allowed_plans:
            return Response({"detail": "Plano inválido."}, status=400)

        # 3) Permissão: somente OWNER ativo do tenant pode criar checkout
        tenant = _require_active_billing_owner(request.user)

        # Validar elegibilidade do Founder para este tenant específico

        if requested_plan == "founder":
```

to:

```python
        requested_interval = (request.data.get("interval") or "monthly").lower()

        # 3) Permissão: somente OWNER ativo do tenant pode criar checkout
        tenant = _require_active_billing_owner(request.user)

        # BE-PLANS-04: o plano é sempre o já atribuído ao tenant no registo
        # ("founder" ou tenant.plan_tier) — nunca um valor enviado pelo
        # cliente. Isto elimina qualquer possibilidade de o checkout criar
        # uma subscrição num plano diferente do que o tenant tem atribuído.
        requested_plan = "founder" if tenant.is_founder else tenant.plan_tier

        if requested_plan not in {"basic", "founder"}:
            return Response({"detail": "Plano inválido."}, status=400)

        # Validar elegibilidade do Founder para este tenant específico

        if requested_plan == "founder":
```

(The rest of the method — the `if requested_plan == "founder": ...` and `if requested_plan == "basic" and FounderService.is_basic_blocked(...): ...` blocks, and everything after — stays exactly as it is; only the plan-source lines above change.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest payments/tests/test_founder_checkout.py -v 2>&1 | tail -40`
Expected: all pass (9 tests: was 10, minus the 1 deleted).

- [ ] **Step 5: Do NOT commit**

---

### Task 5: Full backend regression sweep

**Files:** None (verification only)

- [ ] **Step 1: Run the full payments and users suites**

Run: `pytest payments/ users/ -q`
Expected: all passed, 0 failures. If any other pre-existing test elsewhere breaks (e.g. a test that registers a tenant and asserts `is_founder is False` by relying on the old client-trusting behavior, or asserts `len(available_plans) == 2` for some other tenant fixture), fix that test's expectation to match the new correct behavior — do not weaken assertions that test something unrelated.

- [ ] **Step 2: Run the complete backend suite**

Run: `pytest -q`
Expected: all passed, 0 failures, 0 errors.

- [ ] **Step 3: Run `python manage.py check`**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Do NOT commit**

---

## Part 2 — Frontend Web (`salonix-frontend-web`, branch `few-plans-04-single-assigned-plan`)

### Task 6: `RegisterCheckout.jsx` — single non-interactive plan card

**Files:**
- Modify: `src/pages/RegisterCheckout.jsx`
- Test: `src/pages/__tests__/RegisterCheckout.test.jsx`

- [ ] **Step 1: Update the existing tests first**

`src/pages/__tests__/RegisterCheckout.test.jsx` (from the `few-plans-03` work) already mocks `useBillingOverview` to return an `available_plans` array with exactly 1 item per test (matching the new backend behavior already) — re-read the file to confirm. If it does, no changes needed to the mocks themselves, but add one new test confirming there's no clickable second option:

```typescript
  it('does not render a plan-selection grid when there is only one plan', async () => {
    mockOverview = {
      available_plans: [
        { plan_code: 'founder', is_available: true, is_current: false, can_upgrade: false },
      ],
    };

    render(
      <MemoryRouter>
        <RegisterCheckout />
      </MemoryRouter>
    );

    await screen.findByText(/Continuar para checkout/i);
    // Only one plan name should render; there should be no second, different plan name to click.
    expect(screen.queryByText('TimelyOne')).not.toBeInTheDocument();
  });
```

(Adjust the mock's `PLAN_OPTIONS` in this test file if needed — check the existing `jest.mock('../../api/billing', ...)` block first; it should already define `PLAN_OPTIONS` with both `basic`/`founder` entries as static marketing copy, per the `few-plans-03` work. If the mocked `PLAN_OPTIONS` only has `code: 'founder'` matching, `mergePlanAvailability` will only ever be able to return that one regardless — the real behavior under test here is that the component doesn't render leftover UI implying a second choice exists, like a grid layout or "or choose another plan" text.)

- [ ] **Step 2: Run tests to verify the new test fails**

Run: `npm test -- RegisterCheckout.test.jsx`
Expected: the new test likely already passes today by coincidence (since the mock already provides only 1 plan) — if so, that's fine, it's a regression-pinning test, not one that must fail first. Move on to Step 3 regardless.

- [ ] **Step 3: Update the component**

In `src/pages/RegisterCheckout.jsx`, remove the `selected` state and derive the single plan directly. Change:

```jsx
  const [selected, setSelected] = useState('basic');
  const [billingCycle, setBillingCycle] = useState(
    searchParams.get('interval') === 'annual' ? 'annual' : 'monthly'
  );
```

to:

```jsx
  const [billingCycle, setBillingCycle] = useState(
    searchParams.get('interval') === 'annual' ? 'annual' : 'monthly'
  );
```

Change the `onContinue` callback's use of `selected`:

```jsx
  const onContinue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { url } = await createCheckoutSession(selected, {
        slug,
        interval: billingCycle,
      });
```

to:

```jsx
  const onContinue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { url } = await createCheckoutSession(plans[0]?.code, {
        slug,
        interval: billingCycle,
      });
```

Update the `useCallback` dependency array on the same function — change `[selected, slug, billingCycle, t]` to `[plans, slug, billingCycle, t]`.

Change:

```jsx
  const selectedPlan = plans.find((p) => p.code === selected);
```

to:

```jsx
  const selectedPlan = plans[0];
```

Replace the plan-cards `.map()` block:

```jsx
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {plans.map((p) => {
            const isAnnual = billingCycle === 'annual';
            const showPrice =
              isAnnual && p.price_annual ? p.price_annual : p.price;

            return (
              <button
                key={p.code}
                type="button"
                className={`relative rounded border p-4 text-left transition hover:shadow ${
                  selected === p.code
                    ? 'border-brand-primary ring-2 ring-brand-primary/40'
                    : 'border-brand-border'
                }`}
                onClick={() => setSelected(p.code)}
              >
                <div className="text-lg font-semibold text-brand-surfaceForeground">
                  {t(`plans.options.${p.code}.name`, p.name)}
                </div>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="text-xl font-bold text-brand-surfaceForeground">
                    {t(
                      `plans.options.${p.code}.price_${isAnnual ? 'annual' : 'monthly'}`,
                      showPrice
                    )}
                  </span>
                  <span className="text-xs text-brand-surfaceForeground/60">
                    {isAnnual ? t('plans.per_year') : t('plans.per_month')}
                  </span>
                </div>

                {isAnnual && p.price_annual && (
                  <p className="mt-1 text-[10px] font-bold text-emerald-600">
                    Poupe 2 meses
                  </p>
                )}

                {Array.isArray(p.highlights) && p.highlights.length ? (
                  <ul className="mt-3 list-disc pl-4 text-xs text-brand-surfaceForeground/60">
                    {p.highlights.slice(0, 4).map((h, idx) => (
                      <li key={idx}>
                        {t(`plans.options.${p.code}.highlights.${idx}`, h)}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </button>
            );
          })}
        </div>
```

with:

```jsx
        {selectedPlan && (
          <div className="mt-6">
            {(() => {
              const p = selectedPlan;
              const isAnnual = billingCycle === 'annual';
              const showPrice =
                isAnnual && p.price_annual ? p.price_annual : p.price;

              return (
                <div className="relative rounded border border-brand-primary p-4 text-left">
                  <div className="text-lg font-semibold text-brand-surfaceForeground">
                    {t(`plans.options.${p.code}.name`, p.name)}
                  </div>
                  <div className="mt-1 flex items-baseline gap-1">
                    <span className="text-xl font-bold text-brand-surfaceForeground">
                      {t(
                        `plans.options.${p.code}.price_${isAnnual ? 'annual' : 'monthly'}`,
                        showPrice
                      )}
                    </span>
                    <span className="text-xs text-brand-surfaceForeground/60">
                      {isAnnual ? t('plans.per_year') : t('plans.per_month')}
                    </span>
                  </div>

                  {isAnnual && p.price_annual && (
                    <p className="mt-1 text-[10px] font-bold text-emerald-600">
                      Poupe 2 meses
                    </p>
                  )}

                  {Array.isArray(p.highlights) && p.highlights.length ? (
                    <ul className="mt-3 list-disc pl-4 text-xs text-brand-surfaceForeground/60">
                      {p.highlights.slice(0, 4).map((h, idx) => (
                        <li key={idx}>
                          {t(`plans.options.${p.code}.highlights.${idx}`, h)}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              );
            })()}
          </div>
        )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- RegisterCheckout.test.jsx`
Expected: all pass (2 pre-existing + 1 new = 3).

- [ ] **Step 5: Do NOT commit**

---

### Task 7: `PlanOnboarding.jsx` — single non-interactive plan card, remove founder-warning modal

**Files:**
- Modify: `src/pages/PlanOnboarding.jsx`
- Test: `src/pages/__tests__/PlanOnboarding.test.jsx`

- [ ] **Step 1: Check the existing test file's mocks**

`src/pages/__tests__/PlanOnboarding.test.jsx` (from `few-plans-03`) already mocks `useBillingOverview` with a fixed `available_plans` array. Read it — if it currently provides more than 1 plan in `available_plans`, trim it to exactly 1 (matching the new backend behavior). The 3 existing tests (`abre modal de confirmação...`, `persiste progresso...`, `mostra erro amigável...`) should continue to work with a single-plan mock, since none of them click between multiple plan cards — verify this by reading each test body before making changes.

- [ ] **Step 2: Run the existing tests to confirm current state**

Run: `npx jest PlanOnboarding.test.jsx` (or `npm test -- PlanOnboarding.test.jsx`, whichever this project's test script conventions use for this file)
Expected: establish the baseline (should be 3 passed) before touching the component.

- [ ] **Step 3: Update the component**

In `src/pages/PlanOnboarding.jsx`, remove the `selected` state and the `showFounderWarning` state (both become obsolete — there's no click-to-select anymore, so no need to warn before selecting Founder). Change:

```jsx
  const [selected, setSelected] = useState('basic');
  const [billingCycle, setBillingCycle] = useState('monthly');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [showFounderWarning, setShowFounderWarning] = useState(false);
```

to:

```jsx
  const [billingCycle, setBillingCycle] = useState('monthly');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
```

Find the `useEffect` that syncs `selected` from `overview`/`plan` (around where it reads `overview?.current_subscription?.plan_code`/`plan?.tier`) — read the full block first (search for `setSelected(candidate)` in the file), then DELETE that entire `useEffect` — it no longer has anywhere to write to.

In `confirmCheckout`, change:

```jsx
      const { url } = await createCheckoutSession(selected, {
        slug,
        interval: billingCycle,
      });
```

to:

```jsx
      const { url } = await createCheckoutSession(plans[0]?.code, {
        slug,
        interval: billingCycle,
      });
```

Update `confirmCheckout`'s `useCallback` dependency array — change `[selected, slug, t, billingCycle]` to `[plans, slug, t, billingCycle]`.

Find and DELETE the `onContinue` callback's founder-branch — actually `onContinue` itself (`const onContinue = useCallback(() => { setConfirmOpen(true); }, []);`) stays unchanged, it just opens the confirm modal; leave it as-is.

Change:

```jsx
  const selectedPlan = plans.find((p) => p.code === selected);
```

to:

```jsx
  const selectedPlan = plans[0];
```

Replace the plan-cards `.map()` block (the one with the yellow Founder styling and `onClick={() => { if (p.code === 'founder') { setShowFounderWarning(true); } else { setSelected(p.code); } }}`) with a single non-interactive card, following the same simplification pattern as Task 6 — read the current block in full first (it has Founder-specific badge/styling branches: the `limited_badge`, the `badge` span, the `annual_savings` vs `savings` text), then replace the `<div className="grid gap-3 sm:grid-cols-2">{plans.map((p) => {...})}</div>` wrapper with a single-card equivalent that keeps all of the Founder-specific conditional rendering (badges, annual-savings copy) but drives it off `selectedPlan` directly instead of iterating, and removes the `onClick`/`setShowFounderWarning`/`setSelected` interactivity entirely (just a static `<div>`, not a `<button>`).

DELETE the entire "Modal de Warning do Plano Founder" block at the bottom of the JSX (the `{showFounderWarning && (...)}` block with the amber warning dialog, "Cancelar"/"Entendi, Continuar" buttons) — it's unreachable now that there's no click-driven Founder selection to warn about.

In the confirm modal's summary section, change:

```jsx
            <p className="text-sm text-brand-surfaceForeground/70">
              {t(`plans.options.${selected}.name`, selected)}
            </p>
```

to:

```jsx
            <p className="text-sm text-brand-surfaceForeground/70">
              {t(`plans.options.${selectedPlan?.code}.name`, selectedPlan?.code)}
            </p>
```

And change:

```jsx
              {(() => {
                const p = plans.find((pl) => pl.code === selected) || {};
                const isAnnual = billingCycle === 'annual';
                const showPrice =
                  isAnnual && p.price_annual ? p.price_annual : p.price;
                return t(
                  `plans.options.${selected}.price_${isAnnual ? 'annual' : 'monthly'}`,
                  showPrice
                );
              })()}
```

to:

```jsx
              {(() => {
                const p = selectedPlan || {};
                const isAnnual = billingCycle === 'annual';
                const showPrice =
                  isAnnual && p.price_annual ? p.price_annual : p.price;
                return t(
                  `plans.options.${p.code}.price_${isAnnual ? 'annual' : 'monthly'}`,
                  showPrice
                );
              })()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- PlanOnboarding.test.jsx`
Expected: all 3 pre-existing tests still pass. If any test specifically clicked a "Founder" card or asserted the warning modal's text, that test needs its own update to match the new single-card flow — read each failure carefully and adjust the test's interaction steps (e.g. remove the "click Founder card, see warning, click Entendi" sequence, since there's no such interaction anymore) rather than deleting coverage outright.

- [ ] **Step 5: Do NOT commit**

---

### Task 8: Full frontend regression sweep

**Files:** None (verification only)

- [ ] **Step 1: Run the three plan-related test files**

Run: `npm test -- Plans.test.jsx PlanOnboarding.test.jsx RegisterCheckout.test.jsx`
Expected: all pass.

- [ ] **Step 2: Run the full frontend suite**

Run: `npm test 2>&1 | tail -20`
Expected: same baseline as before this change — 447 passed (or updated count reflecting new tests added in Tasks 6-7), same 4 pre-existing unrelated failures (`RevenueChart.test.jsx`, `ErrorStates.test.jsx`, `installPrompt.test.jsx`, `ExportButton.test.jsx`), same 8 skipped. If any other file's count differs, investigate before proceeding.

- [ ] **Step 3: Run the production build**

Run: `npm run build 2>&1 | tail -20`
Expected: succeeds with no new errors (only the pre-existing chunk-size warnings).

- [ ] **Step 4: Do NOT commit**

Leave everything staged/modified in the working tree. Report the final test counts to Pablo and stop.

---

## Self-Review Notes (for the plan author, not a task)

- **Spec coverage:** Part 1 (BE — `get_available_plans` simplification, registration auto-decides, checkout auto-decides, all listed test rewrites) → Tasks 1-5. Part 2 (FEW — both plan-choice pages collapsed to single card) → Tasks 6-8. MOB explicitly out of scope per the spec (no registration flow exists there) — no task needed.
- **Deliberate behavior removal flagged explicitly:** Task 4 documents and justifies deleting `test_create_checkout_session_basic_allowed_for_active_founder_tenant` — the "downgrade via checkout" capability it tested is intentionally eliminated by this redesign (leaving Founder now only happens via Stripe-portal cancellation + webhook), not an oversight.
- **Type/name consistency:** `assigned_plan = "founder" if tenant.is_founder else tenant.plan_tier` (Task 1) is the same expression used in Task 4's `requested_plan = "founder" if tenant.is_founder else tenant.plan_tier` — same derivation logic in both places, matching the spec's single source of truth. `plans[0]` (not a `selected`-driven lookup) is used consistently in both Task 6 and Task 7's frontend changes.
