#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

BASE_URL="${BASE_URL:-http://localhost:8000}"
FROM="2020-01-01"
TO="2030-01-01"
QS="from=$FROM&to=$TO&limit=${QS_LIMIT:-10}&offset=0"
SMOKE_PASSWORD="${SMOKE_USER_PASSWORD:-Smoke@123}"
PRO_SMOKE_PASSWORD="${PRO_SMOKE_PASSWORD:-$SMOKE_PASSWORD}"
CLIENT_SMOKE_PASSWORD="${CLIENT_SMOKE_PASSWORD:-$SMOKE_PASSWORD}"
PRO_SMOKE_EMAIL="${PRO_SMOKE_EMAIL:-pro_smoke@demo.local}"
CLIENT_SMOKE_EMAIL="${CLIENT_SMOKE_EMAIL:-client_smoke@demo.local}"

red()  { printf "\033[31m%s\033[0m\n" "$*"; }
grn()  { printf "\033[32m%s\033[0m\n" "$*"; }
ylw()  { printf "\033[33m%s\033[0m\n" "$*"; }
hdr()  { printf "\n==== %s ====\n" "$*"; }

# ---------- 1) tokens ----------
hdr "1) Tokens (pro_smoke e client_smoke)"
PRO_TOKEN=$(get_token "$BASE_URL" "pro_smoke" "$PRO_SMOKE_PASSWORD" "$PRO_SMOKE_EMAIL")
CLIENT_TOKEN=$(get_token "$BASE_URL" "client_smoke" "$CLIENT_SMOKE_PASSWORD" "$CLIENT_SMOKE_EMAIL")
grn "OK: tokens obtidos."

# ---------- 2) BEFORE ----------
hdr "2) Aquecendo cache (Top Services - BEFORE)"
CODE=$(curl -sS "$BASE_URL/api/reports/top-services/?$QS" \
  -H "Authorization: Bearer $PRO_TOKEN" \
  -D /tmp/hs_before.txt -o /tmp/body_before.json -w "%{http_code}")
if [[ "$CODE" != "200" ]]; then
  red "Erro $CODE ao consultar top-services BEFORE"
  echo "--- HEADERS ---"; cat /tmp/hs_before.txt
  echo "--- BODY (primeiros 100 linhas) ---"; head -n 100 /tmp/body_before.json
  exit 1
fi

grep -i -E '^(HTTP/|Content-Type|X-Total-Count|X-Limit|X-Offset|Link):' /tmp/hs_before.txt || true
LIMIT_VAL="${QS#*limit=}"; LIMIT_VAL="${LIMIT_VAL%%&*}"
ylw "Body BEFORE (top ${LIMIT_VAL}&offset=0):"
jq '.[] | {service_id, service_name, qty, revenue}' /tmp/body_before.json | head -n 30 || cat /tmp/body_before.json

REV_BEFORE=$(jq '([.[].revenue] | map(.//0)) | add // 0' /tmp/body_before.json 2>/dev/null || echo 0)
QTY_BEFORE=$(jq '([.[].qty]     | map(.//0)) | add // 0' /tmp/body_before.json 2>/dev/null || echo 0)

# SERVICE_ID: FORCE_SERVICE_ID (se setado) > Top-1 > 1º público > 1
SERVICE_ID="${FORCE_SERVICE_ID:-}"
if [[ -z "$SERVICE_ID" ]]; then
  SERVICE_ID="$(jq -r '.[0].service_id // empty' /tmp/body_before.json || true)"
fi
if [[ -z "$SERVICE_ID" ]]; then
  SERVICE_ID="$(curl -sS "$BASE_URL/api/public/services/" | jq -r '.[0].id // empty')"
fi
: "${SERVICE_ID:=1}"

# ---------- 3) encontrar slot/ profissional ----------
hdr "3) Encontrando um slot livre público"
FOUND_PROF=""; FOUND_SLOT=""

# percorre todos os profissionais
for pid in $(curl -sS "$BASE_URL/api/public/professionals/" | jq -r '.[].id'); do
  # lista de slots (compatível com bash 3.2: sem mapfile)
  slots=$(curl -sS "$BASE_URL/api/public/slots/?professional_id=$pid" | jq -r '.[].id')
  # itera slot a slot
  for sid in $slots; do
    [[ -n "${sid:-}" ]] || continue

    # tenta criar; se "já tem agendamento", tenta o próximo slot
    CREATE_RES=$(curl -sS -X POST "$BASE_URL/api/appointments/" \
      -H "Authorization: Bearer $CLIENT_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"service\": $SERVICE_ID, \"professional\": $pid, \"slot\": $sid}")

    if echo "$CREATE_RES" | jq -e '.id' >/dev/null 2>&1; then
      if ! echo "$CREATE_RES" | jq -e '.customer.id' >/dev/null 2>&1; then
        red "Resposta sem cliente associado. Conteúdo:"; echo "$CREATE_RES" | jq . || echo "$CREATE_RES"; exit 1
      fi

      FOUND_PROF="$pid"; FOUND_SLOT="$sid"
      grn "Criado: service=$SERVICE_ID prof=$pid slot=$sid"
      echo "$CREATE_RES" | jq .
      grn "Cliente vinculado: $(echo "$CREATE_RES" | jq -r '.customer.name // "(sem nome)"')"
      break 2
    fi

    if echo "$CREATE_RES" | jq -e '.slot? | type=="array"' >/dev/null 2>&1; then
      ylw "Slot $sid ocupado para prof $pid — tentando outro slot…"
      continue
    fi

    ylw "Falha no slot $sid (prof $pid). Resposta:"
    echo "$CREATE_RES" | jq . || echo "$CREATE_RES"
  done
done

if [[ -z "$FOUND_PROF" || -z "$FOUND_SLOT" ]]; then
  ylw "Não encontrei slot livre para criar agendamento agora (provável exaustão de slots)."
  ylw "Dica: rode 'make seed' para repor dados ou aumente o range de datas/slots."
  # segue para AFTER sem abortar
fi

# (opcional) promover para 'completed'
if [[ -n "$FOUND_SLOT" && "${MARK_COMPLETED:-1}" == "1" ]]; then
  hdr "4) Promovendo último appointment para 'completed'"
  python manage.py shell -c "
from core.models import Appointment;
a=Appointment.objects.latest('id'); a.status='completed'; a.save(); print('completed id=', a.id)
" >/dev/null
fi

# ---------- 5) AFTER ----------
hdr "5) Consultando Top Services - AFTER"
curl -sS "$BASE_URL/api/reports/top-services/?$QS" \
  -H "Authorization: Bearer $PRO_TOKEN" \
  -D /tmp/hs_after.txt -o /tmp/body_after.json >/dev/null
grep -i -E '^(HTTP/|Content-Type|X-Total-Count|X-Limit|X-Offset|Link):' /tmp/hs_after.txt || true
ylw "Body AFTER (top ${LIMIT_VAL}&offset=0):"
jq '.[] | {service_id, service_name, qty, revenue}' /tmp/body_after.json | head -n 30 || cat /tmp/body_after.json

REV_AFTER=$(jq '([.[].revenue] | map(.//0)) | add // 0' /tmp/body_after.json 2>/dev/null || echo 0)
QTY_AFTER=$(jq '([.[].qty]     | map(.//0)) | add // 0' /tmp/body_after.json 2>/dev/null || echo 0)

# ---------- 6) resultado ----------
hdr "6) Resultado"
echo "QTY: BEFORE=$QTY_BEFORE  AFTER=$QTY_AFTER"
echo "REV: BEFORE=$REV_BEFORE  AFTER=$REV_AFTER"

if (( QTY_AFTER > QTY_BEFORE )) || (( REV_AFTER > REV_BEFORE )); then
  grn "✓ Cache invalidado com sucesso: métricas mudaram após criar o appointment."
else
  ylw "! Métricas não mudaram — pode ser disputa no ranking, cache ainda quente ou nenhum slot criado."
  ylw "  Tente QS_LIMIT=50, defina FORCE_SERVICE_ID=3 (Corte Masculino) ou rode 'make seed' e repita."
fi
