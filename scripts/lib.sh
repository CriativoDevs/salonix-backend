#!/usr/bin/env bash
set -euo pipefail

need() { command -v "$1" >/dev/null 2>&1 || { echo "Faltando dependência: $1"; exit 1; }; }
need curl; need jq

get_token() {
  local base="$1" user="$2" pass="$3"
  local t
  t=$(curl -sS -X POST "$base/api/users/token/" \
      -H "Content-Type: application/json" \
      -d "{\"username\":\"$user\",\"password\":\"$pass\"}" | jq -r .access)
  [[ -n "$t" && "$t" != "null" ]] || { echo "ERRO: falha ao obter token ($user)" >&2; return 1; }
  echo "$t"
}