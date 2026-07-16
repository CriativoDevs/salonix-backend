# Plans: Nomenclatura Pública + Exibição de Plano Único Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename plan display names to their public brand ("TimelyOne"/"TimelyOne Founder") and make the backend return only the tenant's current plan (instead of all options) once they have an active paid subscription, so FEW and MOB both inherit the fix automatically.

**Architecture:** All the real logic lives in `SubscriptionService.get_available_plans` (`salonix-backend`), which both `BillingService.get_billing_overview` and `AvailablePlansView` already call. FEW needs only an i18n key addition (its display already prioritizes i18n over the backend's raw `name` field). MOB needs no code change at all — it renders `plan.name` and iterates `available_plans` directly, so it inherits both fixes for free; only a regression test is added there.

**Tech Stack:** Django REST Framework, pytest/pytest-django (backend); React, Jest (frontend web); React Native, Jest (mobile).

**IMPORTANT — no automatic commits:** Every "Commit" step below is written for reference only. Do **NOT** run `git add` / `git commit`. Leave all changes in the working tree, tested and green. Pablo commits and pushes everything himself — including, in the mobile repo, possibly an intermediate commit of his own on `86-mob-parity-01` to tidy up prior uncommitted work, unrelated to this plan's execution.

---

## Part 1 — Backend (`salonix-backend`, branch `be-plans-03-single-plan-display`)

### Task 1: Rename plan display names

**Files:**
- Modify: `payments/services.py:234-262` (`SubscriptionService.AVAILABLE_PLANS`)
- Modify: `payments/services.py:309-325` (inline Founder entry inside `get_available_plans`)
- Test: `payments/tests/test_payments_stripe.py`

- [ ] **Step 1: Write the failing test**

Add to `payments/tests/test_payments_stripe.py`, after `test_get_available_plans_returns_correct_auto_renew_and_credits`:

```python
@pytest.mark.django_db
def test_get_available_plans_uses_public_plan_names(monkeypatch):
    from payments.services import SubscriptionService
    from users.models import Tenant

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

    monkeypatch.setattr("users.services.FounderService", MockFounderService)

    tenant = Tenant.objects.create(name="Naming Tenant", slug="naming-tenant")

    available_plans = SubscriptionService.get_available_plans(tenant=tenant)
    basic_plan = next((p for p in available_plans if p["plan_code"] == "basic"), None)
    founder_plan = next((p for p in available_plans if p["plan_code"] == "founder"), None)

    assert basic_plan is not None
    assert basic_plan["name"] == "TimelyOne"
    assert founder_plan is not None
    assert founder_plan["name"] == "TimelyOne Founder"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest payments/tests/test_payments_stripe.py::test_get_available_plans_uses_public_plan_names -v`
Expected: FAIL — `assert 'Basic' == 'TimelyOne'` (current name is still the internal one)

- [ ] **Step 3: Rename in the implementation**

In `payments/services.py`, inside `AVAILABLE_PLANS["basic"]`, change:

```python
        "basic": {
            "name": "Basic",
```

to:

```python
        "basic": {
            "name": "TimelyOne",
```

Then, inside `get_available_plans`, in the inline Founder entry dict, change:

```python
                {
                    "plan_code": "founder",
                    "name": "Founder",
```

to:

```python
                {
                    "plan_code": "founder",
                    "name": "TimelyOne Founder",
```

Do NOT change `AVAILABLE_PLANS["pro"]["name"]` — Pro is blocked globally and out of scope.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest payments/tests/test_payments_stripe.py::test_get_available_plans_uses_public_plan_names -v`
Expected: 1 passed

- [ ] **Step 5: Run the existing naming-adjacent tests to check for incidental breaks**

Run: `pytest payments/tests/test_payments_stripe.py -k "get_available_plans" -v`
Expected: all pass. (`test_get_available_plans_returns_correct_auto_renew_and_credits` and the two `basic_unavailable`/`basic_available` tests from BE-MARKETING-03 assert on `is_available`/`credits_included`/`comm_auto_renew`, not on `name`, so they should be unaffected — but confirm, since any assertion on the literal string `"Basic"` or `"Founder"` would break here.)

- [ ] **Step 6: Do NOT commit**

---

### Task 2: `subscription_status` parameter on `get_available_plans`

**Files:**
- Modify: `payments/services.py:264-341` (`get_available_plans` signature and end of method body)
- Test: `payments/tests/test_payments_stripe.py`

- [ ] **Step 1: Write the failing tests**

Add to `payments/tests/test_payments_stripe.py`:

```python
@pytest.mark.django_db
def test_get_available_plans_shows_only_current_when_active(monkeypatch):
    from payments.services import SubscriptionService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    tenant = Tenant.objects.create(
        name="Active Basic Tenant", slug="active-basic-tenant", is_founder=False
    )

    available_plans = SubscriptionService.get_available_plans(
        current_plan="basic", tenant=tenant, subscription_status="active"
    )

    assert len(available_plans) == 1
    assert available_plans[0]["plan_code"] == "basic"
    assert available_plans[0]["is_current"] is True


@pytest.mark.django_db
def test_get_available_plans_shows_only_current_when_past_due(monkeypatch):
    from payments.services import SubscriptionService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    tenant = Tenant.objects.create(
        name="Past Due Founder Tenant",
        slug="past-due-founder-tenant",
        is_founder=True,
    )

    available_plans = SubscriptionService.get_available_plans(
        current_plan="founder", tenant=tenant, subscription_status="past_due"
    )

    assert len(available_plans) == 1
    assert available_plans[0]["plan_code"] == "founder"
    assert available_plans[0]["is_current"] is True


@pytest.mark.django_db
def test_get_available_plans_shows_all_when_trialing(monkeypatch):
    from payments.services import SubscriptionService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    tenant = Tenant.objects.create(
        name="Trialing Tenant", slug="trialing-tenant", is_founder=False
    )

    available_plans = SubscriptionService.get_available_plans(
        current_plan="basic", tenant=tenant, subscription_status="trialing"
    )

    plan_codes = {p["plan_code"] for p in available_plans}
    assert "basic" in plan_codes
    assert "founder" in plan_codes


@pytest.mark.django_db
def test_get_available_plans_shows_all_when_no_subscription(monkeypatch):
    from payments.services import SubscriptionService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    tenant = Tenant.objects.create(
        name="Fresh Tenant No Sub", slug="fresh-tenant-no-sub", is_founder=False
    )

    available_plans = SubscriptionService.get_available_plans(
        current_plan=None, tenant=tenant, subscription_status=None
    )

    plan_codes = {p["plan_code"] for p in available_plans}
    assert "basic" in plan_codes
    assert "founder" in plan_codes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest payments/tests/test_payments_stripe.py -k "shows_only_current or shows_all_when" -v`
Expected: FAIL — `TypeError: get_available_plans() got an unexpected keyword argument 'subscription_status'` (parameter doesn't exist yet)

- [ ] **Step 3: Add the parameter and filtering logic**

In `payments/services.py`, change the `get_available_plans` signature:

```python
    @classmethod
    def get_available_plans(
        cls, current_plan: Optional[str] = None, tenant: Optional["Tenant"] = None
    ) -> List[Dict[str, Any]]:
```

to:

```python
    @classmethod
    def get_available_plans(
        cls,
        current_plan: Optional[str] = None,
        tenant: Optional["Tenant"] = None,
        subscription_status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
```

Update the docstring's `Args:` block to add:

```python
            subscription_status: Status da subscrição atual (ex.: "active",
                "trialing", "past_due"). Quando "active" ou "past_due", a
                lista devolvida contém apenas o plano atual — trocar de
                plano pago para outro plano pago não é uma operação
                suportada nesta tela (usar o portal do Stripe / cancelar +
                reativar). Quando None ou "trialing", devolve a lista
                completa, para permitir a escolha inicial.
```

At the very end of the method, immediately before `return plans` (after the `logger.debug(...)` call), add:

```python
        only_current = current_plan is not None and subscription_status in (
            "active",
            "past_due",
        )
        if only_current:
            plans = [p for p in plans if p["is_current"]]

        return plans
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest payments/tests/test_payments_stripe.py -k "shows_only_current or shows_all_when" -v`
Expected: 4 passed

- [ ] **Step 5: Do NOT commit**

---

### Task 3: Wire `subscription_status` into both call sites

**Files:**
- Modify: `payments/services.py:810-816` (`BillingService.get_billing_overview`)
- Modify: `payments/views.py:1171-1189` (`AvailablePlansView.get`)
- Test: `payments/tests/test_payments_stripe.py`

- [ ] **Step 1: Write the failing test**

Add to `payments/tests/test_payments_stripe.py`:

```python
@pytest.mark.django_db
def test_billing_overview_shows_only_current_plan_when_active(monkeypatch, auth_client):
    from payments.services import BillingService
    from users.models import Tenant

    monkeypatch.setattr(
        "users.services.FounderService.get_availability",
        lambda: {"total_limit": 500, "used_count": 0, "remaining_count": 500},
    )

    c, user = auth_client()
    tenant = Tenant.objects.create(
        name="Overview Active Tenant", slug="overview-active-tenant", is_founder=False
    )
    user.tenant = tenant
    user.save()

    monkeypatch.setattr(
        "payments.services.SubscriptionService.get_current_subscription",
        lambda u: {
            "plan_code": "basic",
            "plan_name": "TimelyOne",
            "status": "active",
            "status_label": "Ativo",
            "current_period_end": None,
            "cancel_at_period_end": False,
            "next_billing_date": None,
            "price_monthly": Decimal("29.00"),
        },
    )

    overview = BillingService.get_billing_overview(user)

    assert len(overview["available_plans"]) == 1
    assert overview["available_plans"][0]["plan_code"] == "basic"
```

`Decimal` is already imported at the top of `payments/tests/test_payments_stripe.py` (used elsewhere in the file) — verify with `grep -n "^from decimal import Decimal" payments/tests/test_payments_stripe.py` before assuming; if missing, add it.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest payments/tests/test_payments_stripe.py::test_billing_overview_shows_only_current_plan_when_active -v`
Expected: FAIL — `assert 2 == 1` (both plans still returned, since `get_billing_overview` doesn't pass `subscription_status` yet)

- [ ] **Step 3: Update `get_billing_overview`**

In `payments/services.py`, change:

```python
        current_subscription = SubscriptionService.get_current_subscription(user)
        available_plans = SubscriptionService.get_available_plans(
            current_subscription["plan_code"] if current_subscription else None,
            tenant=getattr(user, "tenant", None),
        )
```

to:

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

- [ ] **Step 4: Update `AvailablePlansView`**

In `payments/views.py`, inside `AvailablePlansView.get`, change:

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

to:

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

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest payments/tests/test_payments_stripe.py::test_billing_overview_shows_only_current_plan_when_active -v`
Expected: 1 passed

- [ ] **Step 6: Do NOT commit**

---

### Task 4: Full backend regression sweep

**Files:** None (verification only)

- [ ] **Step 1: Run the full payments and users suites**

Run: `pytest payments/ users/ -q`
Expected: all passed, 0 failures. Pay particular attention to any test asserting the literal strings `"Basic"` or `"Founder"` as a plan `name`, or asserting `len(available_plans) == 2` for a tenant with an active/past_due subscription elsewhere in the suite (e.g. `test_billing_overview_reflects_auto_renewal_after_update` in `payments/tests/test_settings.py`) — if any such test breaks, it's a real regression caught by this change; fix the test's expectation to match the new correct behavior (only fix test assertions that were checking pre-existing, now-outdated behavior — do not weaken assertions that test something else).

- [ ] **Step 2: Run the complete backend suite**

Run: `pytest -q`
Expected: all passed, 0 failures, 0 errors.

- [ ] **Step 3: Run `python manage.py check`**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Do NOT commit**

---

## Part 2 — Frontend Web (`salonix-frontend-web`, branch `few-plans-03-single-plan-display`)

### Task 5: Add the missing i18n key

**Files:**
- Modify: `src/i18n/locales/pt.json`
- Modify: `src/i18n/locales/en.json`

- [ ] **Step 1: Update `pt.json`**

Find the `plans.options.founder` object (has `name`, `price`, `price_annual`, `badge`, `highlights` keys). Change:

```json
    "name": "Founder",
```

to:

```json
    "name": "TimelyOne Founder",
```

(This is the `name` key nested under `plans.options.founder` — do not confuse with `plans.options.basic.name`, which is already correctly `"TimelyOne"` and must NOT be changed.)

- [ ] **Step 2: Update `en.json`**

Same change, same nesting (`plans.options.founder.name`), same value `"TimelyOne Founder"` (it's a brand name, not translated).

- [ ] **Step 3: Verify both JSON files still parse**

Run: `node -e "JSON.parse(require('fs').readFileSync('src/i18n/locales/pt.json'))" && node -e "JSON.parse(require('fs').readFileSync('src/i18n/locales/en.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 4: Do NOT commit**

---

### Task 6: Confirm existing tests still pass unmodified

**Files:** None (verification only)

- [ ] **Step 1: Run the Plans/PlanOnboarding/RegisterCheckout test files**

Run: `npm test -- Plans.test.jsx PlanOnboarding.test.jsx RegisterCheckout.test.jsx`
Expected: all pass, same counts as before this change (3 + 3 + 2 = 8 tests) — these tests mock `useBillingOverview` directly with a fixed `available_plans` array, so they're unaffected by the backend's new filtering logic (that logic runs server-side, before the mocked data ever reaches the component).

- [ ] **Step 2: Run the full frontend suite**

Run: `npm test 2>&1 | tail -20`
Expected: same pass/fail counts as the FEW-MARKETING-04 baseline (447 passed, 5 failed — the same 4 pre-existing, unrelated failures in `RevenueChart.test.jsx`, `ErrorStates.test.jsx`, `installPrompt.test.jsx`, `ExportButton.test.jsx` — and 8 skipped). If the counts differ in any other file, investigate before proceeding.

- [ ] **Step 3: Do NOT commit**

---

## Part 3 — Mobile (`salonix-mobile`, branch `86-mob-parity-01`, already checked out — do NOT create a new branch)

### Task 7: Regression test for single-plan display

**Files:**
- Modify: `src/screens/__tests__/CreditsPlanScreen.test.tsx`

No component changes — `CreditsPlanScreen.tsx` already renders `plan.name` directly and iterates `availablePlans.map(...)` with no filtering logic of its own, so it inherits both the renamed plans and the single-plan filtering automatically once the backend changes (Part 1) are deployed. This task only adds a regression test pinning that inherited behavior.

- [ ] **Step 1: Write the failing test**

Add to `src/screens/__tests__/CreditsPlanScreen.test.tsx`, inside the `describe('CreditsPlanScreen', ...)` block, after the existing `it('shows the available plans, disabling the current one', ...)` test:

```typescript
  it('shows only the current plan when the backend returns a single available plan', async () => {
    mockFetchBillingOverview.mockResolvedValue({
      ...OVERVIEW,
      available_plans: [
        {
          plan_code: 'founder',
          name: 'TimelyOne Founder',
          price_monthly: 15,
          features: ['Preço Vitalício'],
          credits_included: 2,
          is_current: true,
          can_upgrade: false,
          is_available: true,
        },
      ],
    });

    const { getByText, queryByText } = await render(<CreditsPlanScreen />);

    await waitFor(() => expect(getByText('TimelyOne Founder (Atual)')).toBeTruthy());
    expect(queryByText('Basic')).toBeNull();
    expect(queryByText('Founder')).toBeNull();
  });
```

Check the exact rendering of the plan name + "(Atual)" suffix before finalizing this assertion — `CreditsPlanScreen.tsx` renders `{plan.name}{plan.is_current ? ' (Atual)' : ''}` inside a single `<Text>` element (confirmed at `src/screens/CreditsPlanScreen.tsx:200-202`), so `getByText('TimelyOne Founder (Atual)')` should match the concatenated text content of that `<Text>` node — if React Native Testing Library requires an exact/normalized string match that doesn't merge sibling text nodes the way you expect, adjust to `getByText((content) => content.includes('TimelyOne Founder'))` instead.

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx jest CreditsPlanScreen.test.tsx -t "shows only the current plan"`
Expected: at this point the test should actually FAIL for the wrong reason if run against unmodified `OVERVIEW` mock reuse — but since this test provides its own complete `available_plans` override via `mockFetchBillingOverview.mockResolvedValue({...OVERVIEW, available_plans: [...]})`, and the component has no filtering logic to remove, it may in fact PASS immediately since there was never any code in `CreditsPlanScreen.tsx` that would show more than what the mock returns. If it passes on the first run, that's expected and correct — it confirms the "no component changes needed" claim from the spec. Do not force it to fail artificially; just confirm the assertions are meaningful (they'd catch a regression where someone later adds client-side plan-list logic to this screen that duplicates or conflicts with the backend's filtering).

- [ ] **Step 3: Run the full `CreditsPlanScreen` test file**

Run: `npx jest CreditsPlanScreen.test.tsx`
Expected: all tests pass, including the new one (12 total: 11 pre-existing + 1 new).

- [ ] **Step 4: Do NOT commit**

Leave everything staged/modified in the working tree. Pablo may choose to make an intermediate commit of his own on `86-mob-parity-01` (covering this task and/or prior uncommitted MOB-PARITY-01 work) — that is his decision, not something to do automatically here.

---

## Final — Cross-repo status report

### Task 8: Summarize final state across all 3 repos

**Files:** None (verification only)

- [ ] **Step 1: Confirm backend test counts**

Run (in `salonix-backend`): `pytest -q 2>&1 | tail -5`

- [ ] **Step 2: Confirm frontend web test counts**

Run (in `salonix-frontend-web`): `npm test 2>&1 | tail -10`

- [ ] **Step 3: Confirm mobile test counts**

Run (in `salonix-mobile`): `npx jest CreditsPlanScreen.test.tsx 2>&1 | tail -10`

- [ ] **Step 4: Report to Pablo**

Summarize: tests green in all 3 repos, nothing committed anywhere, ready for Pablo to review and commit each repo independently (backend and frontend-web on their new branches; mobile on the existing `86-mob-parity-01`).

---

## Self-Review Notes (for the plan author, not a task)

- **Spec coverage:** Part 1 (naming + `subscription_status` param + both call sites + behavior table from the spec) → Tasks 1-4. Part 2 (i18n key + confirm no FEW code changes needed) → Tasks 5-6. Part 3 (MOB regression test only, no component change) → Task 7.
- **Regression risk called out explicitly:** Task 4 Step 1 flags that some pre-existing backend test elsewhere in the suite might assert `len(available_plans) == 2` for an active-subscription tenant (a case that becomes newly incorrect) or the literal string `"Basic"`/`"Founder"` — instructs fixing the test's expectation rather than reverting the behavior change, since the old expectation encoded the bug being fixed.
- **Type/name consistency:** `subscription_status` parameter name and its `("active", "past_due")` tuple check are defined once in Task 2 and consumed identically in Task 3's two call sites. The renamed strings `"TimelyOne"`/`"TimelyOne Founder"` are used identically across Task 1 (backend), Task 5 (FEW i18n), and Task 7 (MOB test fixture).
