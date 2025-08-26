# Contribuindo para o Salonix Backend

Obrigado por contribuir! Este guia resume o fluxo de trabalho para manter o projeto consistente e o MVP avançando sem retrabalho.

## Pré-requisitos

- Python 3.11+
- Virtualenv ativo (`.venv`)
- Dependências instaladas: `pip install -r requirements.txt`

## Setup rápido

```bash
make venv
source .venv/bin/activate
make install
make migrate
make run
```