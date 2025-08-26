# =========
# Salonix Makefile
# =========

.RECIPEPREFIX := >
.DEFAULT_GOAL := help

# Variáveis
PY ?= python
PIP ?= pip
MANAGE = $(PY) manage.py
DJANGO_ENV ?= dev

# ---- Ajuda ----
.PHONY: help
help:
> echo "Comandos mais úteis:"
> echo "  make venv           - cria o virtualenv .venv (se não existir)"
> echo "  make install        - instala dependências do requirements.txt"
> echo "  make check          - django system check"
> echo "  make migrate        - aplica migrações"
> echo "  make run            - inicia o servidor em 0.0.0.0:8000 (DJANGO_ENV=$(DJANGO_ENV))"
> echo "  make env-example    - cria .env.example com variáveis padrão"
> echo "  make env-local      - cria .env local (cópia do example, se não existir)"
> echo "  make test           - roda pytest completo"
> echo "  make test-reports   - roda apenas os testes de reports/"
> echo "  make openapi        - gera schema com drf-spectacular em api-schema.yaml"
> echo "  make smoke          - roda o scripts/smoke_reports.sh"
> echo "  make seed           - roda o management command seed_demo"
> echo "  make cache-clear    - limpa o cache do Django (cuidado!)"
> echo "  make lint           - (opcional) ruff check ."
> echo "  make format         - (opcional) ruff format . && black ."

# ---- Env helpers ----
.PHONY: env-example env-local
env-example:
> echo "Gerando .env.example (não sobrescreve existente)…"
> if [ -f .env.example ]; then echo ".env.example já existe. Nada a fazer."; exit 0; fi
> printf '%s\n' \
> 'DJANGO_ENV=dev' \
> 'DEBUG=true' \
> 'SECRET_KEY=change-me' \
> 'ALLOWED_HOSTS=localhost,127.0.0.1' \
> 'DATABASE_URL=sqlite:///db.sqlite3' \
> 'CACHE_URL=locmem://' \
> 'STRIPE_SECRET_KEY=' \
> 'STRIPE_WEBHOOK_SECRET=' \
> > .env.example
> echo "OK: .env.example criado."

env-local:
> echo "Criando .env local a partir do example (não sobrescreve)…"
> if [ -f .env ]; then echo ".env já existe. Nada a fazer."; exit 0; fi
> if [ ! -f .env.example ]; then $(MAKE) env-example; fi
> cp .env.example .env
> echo "OK: .env criado."

# ---- Ambiente ----
.PHONY: venv
venv:
> if [ ! -d ".venv" ]; then $(PY) -m venv .venv; fi
> echo "Ative com: source .venv/bin/activate"

.PHONY: install
install:
> $(PIP) install -r requirements.txt

# ---- Django ----
.PHONY: check
check:
> DJANGO_ENV=$(DJANGO_ENV) $(MANAGE) check

.PHONY: migrate
migrate:
> DJANGO_ENV=$(DJANGO_ENV) $(MANAGE) migrate

.PHONY: run
run:
> DJANGO_ENV=$(DJANGO_ENV) $(MANAGE) runserver 0.0.0.0:8000

# ---- Seed (dados de demonstração) ----
.PHONY: seed
seed:
> DJANGO_ENV=$(DJANGO_ENV) $(MANAGE) seed_demo

.PHONY: reset-seed
reset-seed:
> DJANGO_ENV=$(DJANGO_ENV) $(MANAGE) migrate
> DJANGO_ENV=$(DJANGO_ENV) $(MANAGE) seed_demo

.PHONY: seed-sh
seed-sh:
> mkdir -p scripts
> DJANGO_ENV=$(DJANGO_ENV) ./scripts/seed.sh

# ---- Testes ----
.PHONY: test
test:
> DJANGO_ENV=$(DJANGO_ENV) pytest

.PHONY: test-reports
test-reports:
> DJANGO_ENV=$(DJANGO_ENV) pytest reports/tests/

# ---- OpenAPI ----
.PHONY: openapi
openapi:
> DJANGO_ENV=$(DJANGO_ENV) $(MANAGE) spectacular --file api-schema.yaml

# ---- Smoke ----
.PHONY: smoke
smoke:
> chmod +x scripts/smoke_reports.sh
> DJANGO_ENV=$(DJANGO_ENV) ./scripts/smoke_reports.sh

# ---- Cache ----
.PHONY: cache-clear
cache-clear:
> DJANGO_ENV=$(DJANGO_ENV) $(MANAGE) shell -c "from django.core.cache import cache; cache.clear(); print('Cache limpo.')"

.PHONY: smoke-cache
smoke-cache:
> chmod +x scripts/smoke_cache.sh
> BASE_URL=http://localhost:8000 DJANGO_ENV=$(DJANGO_ENV) ./scripts/smoke_cache.sh

# ---- Qualidade (opcional) ----
.PHONY: lint
lint:
> -ruff check .

.PHONY: format
format:
> -ruff format .
> -black .