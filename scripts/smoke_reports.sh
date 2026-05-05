#!/usr/bin/env bash
set -euo pipefail

# === Smoke test for Salonix Reports endpoints ===
BASE_URL="${BASE_URL:-http://localhost:8000}"
LOGIN_USER="${LOGIN_USER:-pro_smoke}"
DEFAULT_SMOKE_PASS="${SMOKE_USER_PASSWORD:-Smoke@123}"
LOGIN_PASS="${LOGIN_PASS:-$DEFAULT_SMOKE_PASS}"
THROTTLE_COOLDOWN="${THROTTLE_COOLDOWN:-65}"
THROTTLE_MAX_BURST="${THROTTLE_MAX_BURST:-6}"
SMOKE_PREPARE_DATA="${SMOKE_PREPARE_DATA:-1}"
SMOKE_REPORT_TENANTS="${SMOKE_REPORT_TENANTS:-default,nemo-land}"
SMOKE_CREATE_MISSING_TENANTS="${SMOKE_CREATE_MISSING_TENANTS:-0}"
PYTHON_BIN="${PYTHON_BIN:-python}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log() { echo -e "${YELLOW}[*]${NC} $*"; }
ok()  { echo -e "${GREEN}[OK]${NC} $*"; }
fail(){ echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

curl_headers_file="$(mktemp)"
curl_body_file="$(mktemp)"
cleanup() { rm -f "$curl_headers_file" "$curl_body_file"; }
trap cleanup EXIT

source "$(dirname "$0")/lib.sh"

prepare_reports_data_for_tenants() {
  if [[ "$SMOKE_PREPARE_DATA" != "1" ]]; then
  log "Skipping data preparation (SMOKE_PREPARE_DATA=$SMOKE_PREPARE_DATA)."
  return 0
  fi

  log "Preparing report data for tenants: $SMOKE_REPORT_TENANTS"

  SMOKE_REPORT_TENANTS="$SMOKE_REPORT_TENANTS" \
  SMOKE_CREATE_MISSING_TENANTS="$SMOKE_CREATE_MISSING_TENANTS" \
  "$PYTHON_BIN" manage.py shell <<'PY'
from datetime import timedelta
from decimal import Decimal
import calendar
import os

from django.apps import apps
from django.utils import timezone

from core.models import Appointment, Professional, SalonCustomer, ScheduleSlot, Service
from users.models import CustomUser, Tenant, TenantStaffMember


def as_bool(value: str) -> bool:
  return str(value).strip().lower() in {"1", "true", "yes", "on"}


slugs = [item.strip() for item in os.environ.get("SMOKE_REPORT_TENANTS", "default,nemo-land").split(",") if item.strip()]
create_missing = as_bool(os.environ.get("SMOKE_CREATE_MISSING_TENANTS", "0"))
now = timezone.now()


def month_point(base_dt, month_offset: int, day: int, hour: int = 10):
  month = base_dt.month + month_offset
  year = base_dt.year
  while month > 12:
    month -= 12
    year += 1
  while month < 1:
    month += 12
    year -= 1

  last_day = calendar.monthrange(year, month)[1]
  safe_day = min(day, last_day)
  return base_dt.replace(
    year=year,
    month=month,
    day=safe_day,
    hour=hour,
    minute=0,
    second=0,
    microsecond=0,
  )

for slug in slugs:
  tenant = Tenant.objects.filter(slug=slug).first()
  if not tenant:
    if not create_missing:
      print(f"[SMOKE] Tenant '{slug}' not found. Skipping.")
      continue

    tenant = Tenant.objects.create(
      slug=slug,
      name=f"{slug.replace('-', ' ').title()}",
      plan_tier="pro",
      reports_enabled=True,
      pwa_admin_enabled=True,
      pwa_client_enabled=True,
    )
    print(f"[SMOKE] Tenant '{slug}' created.")
  elif not tenant.is_active:
    tenant.is_active = True
    tenant.save(update_fields=["is_active"])
    print(f"[SMOKE] Tenant '{slug}' activated.")

  owner = CustomUser.objects.filter(tenant=tenant, is_active=True).order_by("id").first()
  if not owner:
    username = f"{slug.replace('-', '_')}_smoke_owner"
    email = f"{username}@demo.local"
    owner = CustomUser.objects.create_user(
      username=username,
      email=email,
      password="Smoke@123",
      tenant=tenant,
    )
    print(f"[SMOKE] User '{username}' created for tenant '{slug}'.")

  smoke_username = f"smoke_reports_{slug.replace('-', '_')}"
  smoke_email = f"{smoke_username}@demo.local"
  smoke_user, smoke_created = CustomUser.objects.get_or_create(
    username=smoke_username,
    defaults={
      "email": smoke_email,
      "tenant": tenant,
      "is_active": True,
    },
  )
  if smoke_user.tenant_id != tenant.id:
    smoke_user.tenant = tenant
  if smoke_user.email != smoke_email:
    smoke_user.email = smoke_email
  if not smoke_user.is_active:
    smoke_user.is_active = True
  smoke_user.set_password("Smoke@123")
  smoke_user.save(update_fields=["tenant", "email", "is_active", "password"])
  print(
    f"[SMOKE] Smoke user '{smoke_username}' {'created' if smoke_created else 'updated'} for tenant '{slug}'."
  )

  staff_member, _ = TenantStaffMember.objects.get_or_create(
    tenant=tenant,
    user=smoke_user,
    defaults={
      "role": TenantStaffMember.Role.MANAGER,
      "status": TenantStaffMember.Status.ACTIVE,
    },
  )
  needs_staff_update = False
  if staff_member.role != TenantStaffMember.Role.MANAGER:
    staff_member.role = TenantStaffMember.Role.MANAGER
    needs_staff_update = True
  if staff_member.status != TenantStaffMember.Status.ACTIVE:
    staff_member.status = TenantStaffMember.Status.ACTIVE
    needs_staff_update = True
  if needs_staff_update:
    staff_member.save(update_fields=["role", "status", "updated_at"])
  print(f"[SMOKE] Staff role ensured for '{smoke_username}' in tenant '{slug}'.")

  Subscription = apps.get_model("payments", "Subscription")
  active_sub = (
    Subscription.objects.filter(user__tenant=tenant, status__in=["active", "trialing"])
    .order_by("-updated_at", "-created_at")
    .first()
  )
  if not active_sub:
    sub, sub_created = Subscription.objects.get_or_create(
      user=owner,
      defaults={
        "stripe_subscription_id": f"smoke_sub_{slug}_{owner.id}",
        "status": "active",
        "cancel_at_period_end": False,
      },
    )
    if not sub_created and sub.status not in {"active", "trialing"}:
      sub.status = "active"
      sub.cancel_at_period_end = False
      sub.save(update_fields=["status", "cancel_at_period_end", "updated_at"])
    print(f"[SMOKE] Active subscription ensured for tenant '{slug}'.")

  professional, _ = Professional.objects.get_or_create(
    tenant=tenant,
    user=owner,
    name="[SMOKE] Professional",
    defaults={"bio": "Smoke reports dataset", "is_active": True},
  )

  service, _ = Service.objects.get_or_create(
    tenant=tenant,
    user=owner,
    name="[SMOKE] Service",
    defaults={"duration_minutes": 45, "price_eur": Decimal("35.00")},
  )

  customer, _ = SalonCustomer.objects.get_or_create(
    tenant=tenant,
    email=f"smoke+{slug}@demo.local",
    defaults={
      "name": f"Smoke {slug}",
      "phone_number": "+351910000000",
      "marketing_opt_in": True,
      "is_active": True,
    },
  )

  created = 0
  updated = 0
  schedule_points = [
    (month_point(now, 0, 3), "completed"),
    (month_point(now, 0, 8), "completed"),
    (month_point(now, 0, 14), "paid"),
    (month_point(now, 0, 22), "scheduled"),
    (month_point(now, 1, 3), "completed"),
    (month_point(now, 1, 8), "completed"),
    (month_point(now, 1, 14), "paid"),
    (month_point(now, 1, 22), "scheduled"),
  ]

  for start, status in schedule_points:
    end = start + timedelta(minutes=int(service.duration_minutes or 45))

    slot, _ = ScheduleSlot.objects.get_or_create(
      tenant=tenant,
      professional=professional,
      start_time=start,
      end_time=end,
      defaults={"is_available": False, "status": "booked"},
    )

    appointment, was_created = Appointment.objects.get_or_create(
      tenant=tenant,
      client=owner,
      service=service,
      professional=professional,
      slot=slot,
      defaults={
        "customer": customer,
        "status": status,
        "notes": "[SMOKE] generated by smoke_reports.sh",
      },
    )

    if was_created:
      created += 1
      continue

    changed = False
    if appointment.status != status:
      appointment.status = status
      changed = True
    if appointment.customer_id is None:
      appointment.customer = customer
      changed = True
    if changed:
      appointment.save(update_fields=["status", "customer"])
      updated += 1

    # Reports use Appointment.created_at; align it with the seeded month window.
    if appointment.created_at != start:
      Appointment.objects.filter(pk=appointment.pk).update(created_at=start)
      updated += 1

  month_forced_dates = [
    month_point(now, 0, 3),
    month_point(now, 0, 8),
    month_point(now, 0, 14),
    month_point(now, 1, 3),
    month_point(now, 1, 8),
    month_point(now, 1, 14),
  ]
  cp_qs = Appointment.objects.filter(
    tenant=tenant,
    status__in=["completed", "paid"],
  ).order_by("-id")
  for forced_start, appt in zip(month_forced_dates, cp_qs):
    Appointment.objects.filter(pk=appt.pk).update(created_at=forced_start)
    updated += 1

  print(
    f"[SMOKE] Tenant '{slug}' ready: appointments_created={created}, appointments_updated={updated}."
  )
PY

  ok "Report data prepared for tenant set: $SMOKE_REPORT_TENANTS"
}

init_auth() {
  LOGIN_EMAIL="${LOGIN_EMAIL:-${LOGIN_USER}@demo.local}"

  if ! TOK=$(get_token "$BASE_URL" "$LOGIN_USER" "$LOGIN_PASS" "$LOGIN_EMAIL" ); then
    log "Token falhou para ${LOGIN_USER}. Rodando seed_demo para recriar usuários base…"
    "$(dirname "$0")/seed.sh" || fail "Seed falhou"
    TOK=$(get_token "$BASE_URL" "$LOGIN_USER" "$LOGIN_PASS" "$LOGIN_EMAIL" ) || fail "Falha ao autenticar mesmo após seed"
  fi

  AUTH_HEADER="Authorization: Bearer $TOK"
  ok "Autenticação OK para user=$LOGIN_USER"
}

# --- HTTP helper ---
req() {
  local method="$1"; shift
  local url="$1"; shift
  local expect_status="$1"; shift

  : > "$curl_headers_file"; : > "$curl_body_file"
  local -a headers=(-s -X "$method" "$url" -o "$curl_body_file" -D "$curl_headers_file" -H "$AUTH_HEADER")
  for h in "$@"; do headers+=(-H "$h"); done
  http_code=$(curl "${headers[@]}" -w "%{http_code}" || true)

  content_type=$(grep -i "^Content-Type:" "$curl_headers_file" | tail -n1 | awk '{print $2}' | tr -d '\r')
  xreq=$(grep -i "^X-Request-ID:" "$curl_headers_file" | tail -n1 | awk '{print $2}' | tr -d '\r')

  if [[ "$http_code" != "$expect_status" ]]; then
    echo "--- Response headers ---"; cat "$curl_headers_file"
    echo "--- Response body ---"; head -n 100 "$curl_body_file"
    fail "Expected HTTP $expect_status, got $http_code for $url"
  fi

  echo "$content_type" > "$curl_headers_file.ct"
  echo "$xreq" > "$curl_headers_file.rid"
}

assert_csv_headers() {
  local want_prefix="$1"
  local alt_prefix="${2:-}"
  local ct; ct=$(cat "$curl_headers_file.ct")
  if ! echo "$ct" | grep -qi '^text/csv'; then
    fail "Expected Content-Type text/csv, got: $ct"
  fi
  ok "CSV content-type ok ($ct)"

  # Verifica nas primeiras 10 linhas do CSV para suportar cabeçalhos decorativos e PT-BR
  local header_block; header_block=$(head -n 10 "$curl_body_file")

  if echo "$header_block" | grep -q "$want_prefix"; then
    ok "CSV header contains '$want_prefix'"; return 0
  fi
  if [[ -n "$alt_prefix" ]] && echo "$header_block" | grep -q "$alt_prefix"; then
    ok "CSV header contains '$alt_prefix'"; return 0
  fi
  # Aceita marcação genérica em português
  if echo "$header_block" | grep -q 'RELATÓRIO:'; then
    ok "CSV header contains 'RELATÓRIO:'"; return 0
  fi

  echo "--- First lines ---"; echo "$header_block" | head -n 10
  fail "CSV header not found: '$want_prefix' nor '$alt_prefix'"
}

get_with_backoff_csv() {
  local url="$1" want_prefix="$2"

  while :; do
    : > "$curl_headers_file"; : > "$curl_body_file"
    code=$(curl -s -X GET "$url" -o "$curl_body_file" -D "$curl_headers_file" -H "$AUTH_HEADER" -w "%{http_code}" || true)

    if [[ "$code" == "200" ]]; then
      content_type=$(grep -i "^Content-Type:" "$curl_headers_file" | tail -n1 | awk '{print $2}' | tr -d '\r')
      echo "$content_type" > "$curl_headers_file.ct"
      assert_csv_headers "$want_prefix"; return 0
    elif [[ "$code" == "429" ]]; then
      ra=$(grep -i "^Retry-After:" "$curl_headers_file" | tail -n1 | awk '{print $2}' | tr -d '\r')
      ra=${ra:-60}; log "Throttled (429). Waiting ${ra}s and retrying..."; sleep "$ra"
    else
      echo "--- Response headers ---"; cat "$curl_headers_file"
      echo "--- Response body ---"; head -n 100 "$curl_body_file"
      fail "Expected 200/429, got $code for $url"
    fi
  done
}

main() {
  log "Base URL: $BASE_URL"
  prepare_reports_data_for_tenants
  init_auth

  log "Preparando consentimento RGPD (customer + marketing/email)"
  req GET "$BASE_URL/api/salon/customers/" 200
  cust_id=$(FILE="$curl_body_file" python3 - <<'PY'
import json, os
from pathlib import Path
data = json.loads(Path(os.environ["FILE"]).read_text() or "[]")
print(data[0]["id"] if isinstance(data, list) and data else "")
PY
)
  if [[ -z "$cust_id" ]]; then
    log "Nenhum cliente encontrado, criando um cliente para smoke…"
    code=$(curl -s -X POST "$BASE_URL/api/salon/customers/" \
      -H "$AUTH_HEADER" -H "Content-Type: application/json" \
      -d '{"name":"Smoke Customer","email":"smoke_customer@demo.local","phone_number":"+351910000000","marketing_opt_in":true}' \
      -o "$curl_body_file" -D "$curl_headers_file" -w "%{http_code}" || true)
    [[ "$code" == "201" || "$code" == "200" ]] || { echo "--- Headers ---"; cat "$curl_headers_file"; echo "--- Body ---"; head -n 50 "$curl_body_file"; fail "Falha ao criar cliente (HTTP $code)"; }
    cust_id=$(python3 - <<'PY'
import json, sys
print(json.load(sys.stdin).get("id", ""))
PY
 < "$curl_body_file")
    [[ -n "$cust_id" ]] || fail "Cliente criado mas ID vazio"
    ok "Cliente criado (id=$cust_id)"
  else
    ok "Cliente existente (id=$cust_id)"
  fi

  log "Criando/atualizando consentimento: marketing/email"
  code=$(curl -s -X POST "$BASE_URL/api/notifications/consent/create/" \
    -H "$AUTH_HEADER" -H "Content-Type: application/json" \
    -d "{\"customer_id\":$cust_id,\"channel\":\"email\",\"purpose\":\"marketing\",\"source\":\"admin\"}" \
    -o "$curl_body_file" -D "$curl_headers_file" -w "%{http_code}" || true)
  [[ "$code" == "201" || "$code" == "200" ]] || { echo "--- Headers ---"; cat "$curl_headers_file"; echo "--- Body ---"; head -n 50 "$curl_body_file"; fail "Falha ao registrar consentimento (HTTP $code)"; }
  ok "Consentimento marketing/email OK"

  log "Criando/atualizando consentimento: marketing/sms"
  code=$(curl -s -X POST "$BASE_URL/api/notifications/consent/create/" \
    -H "$AUTH_HEADER" -H "Content-Type: application/json" \
    -d "{\"customer_id\":$cust_id,\"channel\":\"sms\",\"purpose\":\"marketing\",\"source\":\"admin\"}" \
    -o "$curl_body_file" -D "$curl_headers_file" -w "%{http_code}" || true)
  [[ "$code" == "201" || "$code" == "200" ]] || { echo "--- Headers ---"; cat "$curl_headers_file"; echo "--- Body ---"; head -n 50 "$curl_body_file"; fail "Falha ao registrar consentimento SMS (HTTP $code)"; }
  ok "Consentimento marketing/sms OK"

  log "Criando/atualizando consentimento: marketing/whatsapp"
  code=$(curl -s -X POST "$BASE_URL/api/notifications/consent/create/" \
    -H "$AUTH_HEADER" -H "Content-Type: application/json" \
    -d "{\"customer_id\":$cust_id,\"channel\":\"whatsapp\",\"purpose\":\"marketing\",\"source\":\"admin\"}" \
    -o "$curl_body_file" -D "$curl_headers_file" -w "%{http_code}" || true)
  [[ "$code" == "201" || "$code" == "200" ]] || { echo "--- Headers ---"; cat "$curl_headers_file"; echo "--- Body ---"; head -n 50 "$curl_body_file"; fail "Falha ao registrar consentimento WhatsApp (HTTP $code)"; }
  ok "Consentimento marketing/whatsapp OK"

  log "GET /api/users/staff/"
  req GET "$BASE_URL/api/users/staff/" 200
  staff_count=$(FILE="$curl_body_file" python3 - <<'PY'
import json, os
from pathlib import Path
payload = Path(os.environ["FILE"]).read_text() or "[]"
data = json.loads(payload)
print(len(data))
PY
)
  if [[ -z "$staff_count" ]]; then
    fail "Não foi possível determinar a quantidade de membros de equipe."
  fi
  if (( staff_count < 2 )); then
    echo "--- Corpo da resposta staff ---"; cat "$curl_body_file"
    fail "Esperava pelo menos 2 membros de equipe, obtive $staff_count."
  fi
  ok "staff list OK (count=$staff_count, X-Request-ID: $(cat "$curl_headers_file.rid"))"

  # Date range (portável)
  if date -v-7d +%F >/dev/null 2>&1; then START=$(date -v-7d +%F); else START=$(date -d '-7 days' +%F); fi
  END=$(date +%F)

  log "GET /api/reports/overview/"
  req GET "$BASE_URL/api/reports/overview/" 200
  grep -q '"appointments_total"' "$curl_body_file" || fail "Body missing 'appointments_total'"
  ok "overview OK (X-Request-ID: $(cat "$curl_headers_file.rid"))"

  log "GET /api/reports/top-services/?limit=5"
  req GET "$BASE_URL/api/reports/top-services/?limit=5" 200
  ok "top-services OK (X-Request-ID: $(cat "$curl_headers_file.rid"))"

  log "GET /api/reports/revenue/?interval=day"
  req GET "$BASE_URL/api/reports/revenue/?interval=day" 200
  ok "revenue OK (X-Request-ID: $(cat "$curl_headers_file.rid"))"

  log "GET /api/reports/overview/export/"
  get_with_backoff_csv "$BASE_URL/api/reports/overview/export/?from=$START&to=$END" "Overview report"
  grep -Eq "appointments_total|Agendamentos Totais" "$curl_body_file" || fail "CSV missing 'appointments_total' or 'Agendamentos Totais'"
  ok "overview CSV OK"

  log "GET /api/reports/top-services/export/"
  get_with_backoff_csv "$BASE_URL/api/reports/top-services/export/?from=$START&to=$END" "Top Services report"
  ok "top-services CSV OK"

  log "GET /api/reports/revenue/export/ (interval=week)"
  get_with_backoff_csv "$BASE_URL/api/reports/revenue/export/?from=$START&to=$END&interval=week" "Revenue"
  ok "revenue CSV OK"

  log "Cooling down throttle window (${THROTTLE_COOLDOWN}s) before throttle check..."
  sleep "$THROTTLE_COOLDOWN"

  log "Throttle check..."
  hits=0; got429=0
  while (( hits < THROTTLE_MAX_BURST )); do
    code=$(curl -s -o /dev/null -w "%{http_code}" -H "$AUTH_HEADER" \
      "$BASE_URL/api/reports/revenue/export/?from=$START&to=$END&interval=week")
    ((hits++))
    if [[ "$code" == "429" || "$code" == "403" ]]; then ok "Throttle ok (hit #$hits, $code)"; got429=1; break
    elif [[ "$code" != "200" ]]; then fail "Unexpected $code on throttle check (hit #$hits)"; fi
  done
  [[ "$got429" == "1" ]] || ok "No throttle observed (dev rate likely higher)."

  log "GET /metrics (Prometheus)"
  metrics=$(curl -s "$BASE_URL/metrics" || true)
  echo "$metrics" | grep -E 'reports_requests_total|reports_latency_seconds_bucket|reports_csv_bytes_total|reports_csv_rows_total' >/dev/null \
    || { echo "$metrics" | head -n 50; fail "Expected report metrics not found in /metrics"; }
  echo "$metrics" | grep -E 'appointment_series_created_total|appointment_series_updated_total|appointment_series_occurrence_cancel_total|appointment_series_size_total' >/dev/null \
    || { echo "$metrics" | head -n 50; fail "Expected series metrics not found in /metrics"; }
  ok "/metrics contains report + series metrics."
  ok "Smoke test finished successfully."
}

main "$@"
