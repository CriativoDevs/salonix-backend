#!/usr/bin/env bash
set -euo pipefail

DJANGO_ENV="${DJANGO_ENV:-dev}"
echo "[*] Seeding (DJANGO_ENV=$DJANGO_ENV)…"
DJANGO_ENV="$DJANGO_ENV" python manage.py seed_demo
echo "[OK] Seed concluído."