#!/usr/bin/env bash
set -euo pipefail

DJANGO_ENV="${DJANGO_ENV:-dev}"
PYTHON_BIN="${PYTHON_BIN:-python}"

# Configurações padrão
APPOINTMENTS=${APPOINTMENTS:-1000}
CUSTOMERS=${CUSTOMERS:-200}
PROFESSIONALS=${PROFESSIONALS:-5}
SERVICES=${SERVICES:-10}
DAYS_BACK=${DAYS_BACK:-120}
DAYS_FORWARD=${DAYS_FORWARD:-40}
BATCH_SIZE=${BATCH_SIZE:-1000}
TENANT_SLUG=${TENANT_SLUG:-nemo-land}

echo "[*] Gerando dados de teste em massa (DJANGO_ENV=$DJANGO_ENV)..."
echo "    - Agendamentos: $APPOINTMENTS"
echo "    - Clientes: $CUSTOMERS"
echo "    - Profissionais: $PROFESSIONALS"
echo "    - Serviços: $SERVICES"
echo "    - Tenant: $TENANT_SLUG"
echo "    - Dias no passado: $DAYS_BACK"
echo "    - Dias no futuro: $DAYS_FORWARD"
echo "    - Batch size: $BATCH_SIZE"
echo ""

# Verificar se seed básico foi executado
echo "[*] Verificando se seed básico existe..."
DJANGO_ENV="$DJANGO_ENV" "$PYTHON_BIN" manage.py shell -c "
from users.models import Tenant
try:
    Tenant.objects.get(slug='$TENANT_SLUG')
    print('✓ Tenant alvo encontrado')
except Tenant.DoesNotExist:
    print('✗ Tenant alvo não encontrado. Execute make seed primeiro ou ajuste TENANT_SLUG.')
    exit(1)
"

echo ""
echo "[*] Iniciando geração de dados em massa..."
start_time=$(date +%s)

DJANGO_ENV="$DJANGO_ENV" "$PYTHON_BIN" manage.py seed_mass_data \
    --tenant-slug="$TENANT_SLUG" \
    --appointments="$APPOINTMENTS" \
    --customers="$CUSTOMERS" \
    --professionals="$PROFESSIONALS" \
    --services="$SERVICES" \
    --days-back="$DAYS_BACK" \
    --days-forward="$DAYS_FORWARD" \
    --batch-size="$BATCH_SIZE"

end_time=$(date +%s)
duration=$((end_time - start_time))

echo ""
echo "[OK] Dados de teste gerados em ${duration}s"

# Invalidar cache de relatórios para evitar dados obsoletos no ambiente dev
if DJANGO_ENV="$DJANGO_ENV" "$PYTHON_BIN" manage.py shell -c "
from reports.utils.cache import invalidate_many
invalidate_many(['reports:overview', 'reports:top_services', 'reports:revenue'])
print('[OK] Cache de relatórios invalidado.')
" 2>/dev/null; then
    : # sucesso já impresso pelo Python
else
    echo "[WARN] Não foi possível invalidar o cache de relatórios (ignorado)."
fi

echo ""
echo "Para testar performance, use:"
echo "  curl 'http://localhost:8000/api/appointments/export_csv/' -H 'Authorization: Bearer <token>'"
echo "  curl 'http://localhost:8000/api/reports/overview/export/' -H 'Authorization: Bearer <token>'"
