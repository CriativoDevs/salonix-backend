#!/bin/sh

# Define os caminhos de origem e destino
SOURCE_FILE="/app/media/tenant_logos/generic.png"
DEST_DIR="/data/media/tenant_logos"
DEST_FILE="$DEST_DIR/generic.png"

# Garante que o diretório de destino exista
mkdir -p $DEST_DIR

# Verifica se o arquivo de logo padrão NÃO existe no volume persistente
if [ ! -f "$DEST_FILE" ]; then
  echo "Logo padrão não encontrado em $DEST_FILE. Copiando do repositório..."
  # Copia o arquivo do código da aplicação para o volume
  cp $SOURCE_FILE $DEST_FILE
else
  echo "Logo padrão já existe. Nenhuma ação necessária."
fi

# Inicia o servidor da aplicação
# Substitua 'salonix_backend.wsgi:application' pelo caminho correto do seu WSGI se for diferente
# --workers 5: (2 x 2 vCPU) + 1, formula padrão do Gunicorn para a alocação atual do Railway (2 vCPU / 2GB)
# --timeout 30: default do Gunicorn, explícito para documentar a intenção
echo "Iniciando Gunicorn..."
exec gunicorn salonix_backend.wsgi:application --bind 0.0.0.0:$PORT --workers 5 --timeout 30 --worker-class sync
