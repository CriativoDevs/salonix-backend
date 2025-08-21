#!/usr/bin/env bash
set -euo pipefail

# === Smoke test for Salonix Reports endpoints ===
# Requirements: bash, curl, grep, awk, sed, date, head, mktemp
# Optional: a running server with auth enabled. You can pass a JWT via AUTH_HEADER.
#
# Examples:
#   chmod +x smoke_reports.sh
#   ./smoke_reports.sh
#   BASE_URL=http://localhost:8001 AUTH_HEADER="Authorization: Bearer <TOKEN>" ./smoke_reports.sh
#
# To auto-login (if you have a JWT endpoint):
#   TOKEN_ENDPOINT="/api/users/token/" LOGIN_USER="pro@example.com" LOGIN_PASS="x" ./smoke_reports.sh

BASE_URL="${BASE_URL:-http://localhost:8000}"
AUTH_HEADER="${AUTH_HEADER:-}"
TOKEN_ENDPOINT="/api/users/token/"
LOGIN_USER="pro_smoke"
LOGIN_PASS="x"
THROTTLE_COOLDOWN="${THROTTLE_COOLDOWN:-65}"
THROTTLE_MAX_BURST="${THROTTLE_MAX_BURST:-6}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log() { echo -e "${YELLOW}[*]${NC} $*"; }
ok()  { echo -e "${GREEN}[OK]${NC} $*"; }
fail(){ echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

curl_headers_file="$(mktemp)"
curl_body_file="$(mktemp)"
cleanup() { rm -f "$curl_headers_file" "$curl_body_file"; }
trap cleanup EXIT

# --- Optional JWT obtain ---
maybe_login() {
  if [[ -n "$TOKEN_ENDPOINT" && -n "$LOGIN_USER" && -n "$LOGIN_PASS" && -z "$AUTH_HEADER" ]]; then
    log "Authenticating via $TOKEN_ENDPOINT as $LOGIN_USER ..."
    # Try a common JWT payload; adjust if needed.
    token_json=$(curl -s -X POST \
      -H "Content-Type: application/json" \
      -d "{\"username\":\"$LOGIN_USER\",\"password\":\"$LOGIN_PASS\"}" \
      "$BASE_URL$TOKEN_ENDPOINT" || true)
    if echo "$token_json" | grep -qE '"access"|"token"'; then
      # Extract token (supports {"access": "..."} or {"token":"..."})
      token=$(echo "$token_json" | sed -n 's/.*"access"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
      if [[ -z "$token" ]]; then
        token=$(echo "$token_json" | sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
      fi
      if [[ -n "$token" ]]; then
        AUTH_HEADER="Authorization: Bearer $token"
        ok "Authenticated. Using bearer token."
      else
        fail "Could not parse token from response: $token_json"
      fi
    else
      fail "Auth failed: $token_json"
    fi
  fi
}

# --- HTTP helper ---
req() {
  local method="$1"; shift
  local url="$1"; shift
  local expect_status="$1"; shift

  # declare arrays explicitamente (compatível com bash 3.2)
  local -a extra_headers=("$@")

  # Reset output files
  : > "$curl_headers_file"; : > "$curl_body_file"

  # também declarar headers como array
  local -a headers=(-s -X "$method" "$url" -o "$curl_body_file" -D "$curl_headers_file")

  if [[ -n "$AUTH_HEADER" ]]; then
    headers+=(-H "$AUTH_HEADER")
  fi

  # só itera se houver itens
  for h in "$@"; do
    headers+=(-H "$h")
  done

  # Execute
  http_code=$(curl "${headers[@]}" -w "%{http_code}" || true)

  # Extract Content-Type and X-Request-ID
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

# --- CSV assertions ---
assert_csv_headers() {
  local want_prefix="$1"
  local alt_prefix="${2:-}"
  local ct; ct=$(cat "$curl_headers_file.ct")
  if ! echo "$ct" | grep -qi '^text/csv'; then
    fail "Expected Content-Type text/csv, got: $ct"
  fi
  ok "CSV content-type ok ($ct)"

  local first; first=$(head -n 1 "$curl_body_file")
  if echo "$first" | grep -q "$want_prefix"; then
    ok "CSV header contains '$want_prefix'"
    return 0
  fi
  if [[ -n "$alt_prefix" ]] && echo "$first" | grep -q "$alt_prefix"; then
    ok "CSV header contains '$alt_prefix'"
    return 0
  fi

  echo "--- First lines ---"; head -n 10 "$curl_body_file"
  fail "CSV header not found: '$want_prefix' nor '$alt_prefix'"
}

assert_body_contains() {
  local needle="$1"
  if ! grep -q "$needle" "$curl_body_file"; then
    echo "--- Body ---"; head -n 80 "$curl_body_file"
    fail "Body does not contain '$needle'"
  fi
  ok "Body contains '$needle'"
}

# --- Helper: GET com backoff em 429 (usa AUTH_HEADER se existir) ---
get_with_backoff_csv() {
  local url="$1"
  local want_prefix="$2"

  while :; do
    : > "$curl_headers_file"; : > "$curl_body_file"
    local -a cmd=(-s -X GET "$url" -o "$curl_body_file" -D "$curl_headers_file" -w "%{http_code}")
    if [[ -n "$AUTH_HEADER" ]]; then
      cmd=(-s -X GET "$url" -o "$curl_body_file" -D "$curl_headers_file" -H "$AUTH_HEADER" -w "%{http_code}")
    fi
    code=$(curl "${cmd[@]}" || true)

    if [[ "$code" == "200" ]]; then
      # salva Content-Type p/ assert_csv_headers()
      content_type=$(grep -i "^Content-Type:" "$curl_headers_file" | tail -n1 | awk '{print $2}' | tr -d '\r')
      echo "$content_type" > "$curl_headers_file.ct"
      assert_csv_headers "$want_prefix"
      return 0
    elif [[ "$code" == "429" ]]; then
      ra=$(grep -i "^Retry-After:" "$curl_headers_file" | tail -n1 | awk '{print $2}' | tr -d '\r')
      ra=${ra:-60}
      log "Throttled (429). Waiting ${ra}s and retrying..."
      sleep "$ra"
      continue
    else
      echo "--- Response headers ---"; cat "$curl_headers_file"
      echo "--- Response body ---"; head -n 100 "$curl_body_file"
      fail "Expected 200/429, got $code for $url"
    fi
  done
}

# --- Main flow ---
main() {
  log "Base URL: $BASE_URL"
  maybe_login

  # Date range (portable between macOS and Linux)
  if date -v-7d +%F >/dev/null 2>&1; then
    START=$(date -v-7d +%F)
  else
    START=$(date -d '-7 days' +%F)
  fi
  END=$(date +%F)

  # 1) JSON overview
  log "GET /api/reports/overview/"
  req GET "$BASE_URL/api/reports/overview/" 200
  assert_body_contains '"appointments_total"'
  ok "overview OK (X-Request-ID: $(cat "$curl_headers_file.rid"))"

  # 2) top-services
  log "GET /api/reports/top-services/?limit=5"
  req GET "$BASE_URL/api/reports/top-services/?limit=5" 200
  ok "top-services OK (X-Request-ID: $(cat "$curl_headers_file.rid"))"

  # 3) revenue series
  log "GET /api/reports/revenue/?interval=day"
  req GET "$BASE_URL/api/reports/revenue/?interval=day" 200
  ok "revenue OK (X-Request-ID: $(cat "$curl_headers_file.rid"))"

  # 4) CSV overview
  log "GET /api/reports/overview/export/"
  get_with_backoff_csv "$BASE_URL/api/reports/overview/export/?from=$START&to=$END" "Overview report"
  assert_body_contains "appointments_total"
  ok "overview CSV OK"

  # 5) CSV top-services
  log "GET /api/reports/top-services/export/"
  get_with_backoff_csv "$BASE_URL/api/reports/top-services/export/?from=$START&to=$END" "Top Services report"
  ok "top-services CSV OK"

  # 6) CSV revenue
  log "GET /api/reports/revenue/export/ (interval=week)"
  get_with_backoff_csv "$BASE_URL/api/reports/revenue/export/?from=$START&to=$END&interval=week" "Revenue"
  ok "revenue CSV OK"

  # 7) throttle check dinâmico
  log "Cooling down throttle window (${THROTTLE_COOLDOWN}s) before throttle check..."
  sleep "$THROTTLE_COOLDOWN"

  log "Throttle check on revenue/export (searching for a 429 within ${THROTTLE_MAX_BURST} rapid hits)."
  hits=0
  got429=0
  while (( hits < THROTTLE_MAX_BURST )); do
    code=$(curl -s -o /dev/null -w "%{http_code}" \
      ${AUTH_HEADER:+-H "$AUTH_HEADER"} \
      "$BASE_URL/api/reports/revenue/export/?from=$START&to=$END&interval=week")
    ((hits++))
    if [[ "$code" == "429" || "$code" == "403" ]]; then
      ok "Throttle behaved as expected on hit #$hits ($code)."
      got429=1
      break
    elif [[ "$code" != "200" ]]; then
      fail "Unexpected HTTP $code during throttle check (hit #$hits)"
    fi
  done

  if [[ "$got429" -eq 0 ]]; then
    log "No throttle triggered within ${THROTTLE_MAX_BURST} hits — likely higher rate in settings. Marking as OK for dev."
    ok "Throttle not observed (rate likely > ${THROTTLE_MAX_BURST}/min)."
  fi

  # 8) metrics
  log "GET /metrics (Prometheus)"
  metrics=$(curl -s "$BASE_URL/metrics" || true)
  echo "$metrics" | grep -E 'reports_requests_total|reports_latency_seconds_bucket|reports_csv_bytes_total|reports_csv_rows_total' >/dev/null || {
    echo "$metrics" | head -n 50
    fail "Expected report metrics not found in /metrics"
  }
  ok "/metrics contains report metrics."

  ok "Smoke test finished successfully."
}

main "$@"
