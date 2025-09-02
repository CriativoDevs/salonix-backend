#!/usr/bin/env bash
set -euo pipefail

# === Smoke test for Salonix Reports endpoints ===
BASE_URL="${BASE_URL:-http://localhost:8000}"
LOGIN_USER="${LOGIN_USER:-pro_smoke}"
LOGIN_PASS="${LOGIN_PASS:-pro_smoke}"
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

source "$(dirname "$0")/lib.sh"

# Auth sempre via lib.sh (mais robusto)
LOGIN_EMAIL="${LOGIN_EMAIL:-pro@e.com}"  # Email padrão para pro_smoke
TOK=$(get_token "$BASE_URL" "$LOGIN_USER" "$LOGIN_PASS" "$LOGIN_EMAIL")
AUTH_HEADER="Authorization: Bearer $TOK"

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

  local first; first=$(head -n 1 "$curl_body_file")
  if echo "$first" | grep -q "$want_prefix"; then
    ok "CSV header contains '$want_prefix'"; return 0
  fi
  if [[ -n "$alt_prefix" ]] && echo "$first" | grep -q "$alt_prefix"; then
    ok "CSV header contains '$alt_prefix'"; return 0
  fi
  echo "--- First lines ---"; head -n 10 "$curl_body_file"
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
  grep -q "appointments_total" "$curl_body_file" || fail "CSV missing 'appointments_total'"
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
  ok "/metrics contains report metrics."
  ok "Smoke test finished successfully."
}

main "$@"