#!/usr/bin/env bash
set -euo pipefail

DJANGO_ENV="${DJANGO_ENV:-dev}"

# Configurações padrão
APPOINTMENTS=${APPOINTMENTS:-1000}
CUSTOMERS=${CUSTOMERS:-200}
PROFESSIONALS=${PROFESSIONALS:-5}
SERVICES=${SERVICES:-10}
DAYS_BACK=${DAYS_BACK:-30}
BATCH_SIZE=${BATCH_SIZE:-1000}

echo "[*] Gerando dados de teste em massa (DJANGO_ENV=$DJANGO_ENV)..."
echo "    - Agendamentos: $APPOINTMENTS"
echo "    - Clientes: $CUSTOMERS"
echo "    - Profissionais: $PROFESSIONALS"
echo "    - Serviços: $SERVICES"
echo "    - Dias no passado: $DAYS_BACK"
echo "    - Batch size: $BATCH_SIZE"
echo ""

# Verificar se seed básico foi executado
echo "[*] Verificando se seed básico existe..."
DJANGO_ENV="$DJANGO_ENV" python manage.py shell -c "
from users.models import Tenant
try:
    Tenant.objects.get(slug='default')
    print('✓ Tenant padrão encontrado')
except Tenant.DoesNotExist:
    print('✗ Tenant padrão não encontrado. Execute make seed primeiro.')
    exit(1)
"

echo ""
echo "[*] Iniciando geração de dados em massa..."
start_time=$(date +%s)

DJANGO_ENV="$DJANGO_ENV" python manage.py seed_mass_data \
    --appointments="$APPOINTMENTS" \
    --customers="$CUSTOMERS" \
    --professionals="$PROFESSIONALS" \
    --services="$SERVICES" \
    --days-back="$DAYS_BACK" \
    --batch-size="$BATCH_SIZE"

end_time=$(date +%s)
duration=$((end_time - start_time))

echo ""
echo "[OK] Dados de teste gerados em ${duration}s"
echo ""
echo "Para testar performance, use:"
echo "  curl 'http://localhost:8000/api/appointments/export_csv/' -H 'Authorization: Bearer <token>'"
echo "  curl 'http://localhost:8000/api/reports/overview/export/' -H 'Authorization: Bearer <token>'"
