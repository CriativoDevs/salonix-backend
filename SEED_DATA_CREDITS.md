# Seed Data - Sistema de Créditos de Comunicação

## Visão Geral

O sistema de seed data foi expandido para incluir diferentes cenários de créditos de comunicação, permitindo testar todas as funcionalidades do sistema de créditos em ambiente de desenvolvimento local.

## Como Executar

```bash
# Executar o seed completo
./seed.sh

# Ou executar diretamente o comando Django
python manage.py seed_demo
```

## Tenants Criados

O seed data cria os seguintes tenants com diferentes configurações de crédito:

### 1. Default Salon (Tenant Principal)
- **Créditos iniciais**: 10.00€
- **Auto-renovação**: Habilitada
- **Histórico**: Compras e consumos variados
- **Saldo final**: ~14.20€

### 2. Basic Salon Demo
- **Créditos iniciais**: 5.00€
- **Auto-renovação**: Desabilitada
- **Histórico**: Compra inicial + consumo básico
- **Saldo final**: ~4.50€

### 3. Pro Salon Demo
- **Créditos iniciais**: 25.00€
- **Auto-renovação**: Habilitada
- **Domínio customizado**: pro-salon.example.com
- **Histórico**: Múltiplas transações de consumo
- **Saldo final**: ~19.90€

### 4. Empty Credits Demo
- **Créditos iniciais**: 0.00€
- **Auto-renovação**: Desabilitada
- **Histórico**: Créditos consumidos completamente
- **Saldo final**: 0.00€ (para testar cenário de esgotamento)

## Histórico de Transações (CommLedger)

Cada tenant possui um histórico de transações realista:

- **Transações de compra** (`purchase`): Adição de créditos
- **Transações de consumo** (`consumption`): Uso de créditos para comunicação

## Verificação dos Dados

Para verificar se o seed foi executado corretamente:

```bash
python manage.py shell -c "
from core.models import Tenant
from users.models import CommLedger

print('=== TENANTS ===')
for t in Tenant.objects.all():
    print(f'{t.name}: {t.comm_credit_eur} créditos, auto_renew: {t.comm_auto_renew}')

print('\n=== COMM LEDGER ===')
for cl in CommLedger.objects.all().order_by('tenant', 'created_at'):
    print(f'{cl.tenant.name}: {cl.transaction_type} - {cl.amount_eur}€ (saldo: {cl.balance_after}€)')
"
```

## Cenários de Teste Disponíveis

Com este seed data, é possível testar:

1. **Tenant com créditos suficientes** (Default Salon, Pro Salon Demo)
2. **Tenant com poucos créditos** (Basic Salon Demo)
3. **Tenant sem créditos** (Empty Credits Demo)
4. **Auto-renovação habilitada vs desabilitada**
5. **Histórico completo de transações**
6. **Diferentes volumes de consumo**

## Políticas por Plano (Seeds)

- **`comm_auto_renew`**: habilitado para Standard e Pro (Standard+).
- **`custom_domain_enabled`**: apenas para Pro (Pro+).
- **`comm_extra_allowed`**: habilitado em todos os planos.

As configurações dos tenants no seed (`seed_demo.py`) refletem estas políticas.

## Credenciais de Acesso

- **Admin**: admin@demo.local / admin
- **Usuário PRO**: pro_smoke@demo.local / Smoke@123
- **Cliente**: client_smoke@demo.local / Smoke@123

## Personalização

Para alterar a senha padrão dos usuários de teste:

```bash
export SMOKE_USER_PASSWORD="MinhaNovaSenh@123"
./seed.sh
```

## Arquivos Relacionados

- `core/management/commands/seed_demo.py` - Comando principal de seed
- `seed.sh` - Script de execução

## Notas Importantes

- Este seed data é **apenas para desenvolvimento local**
- **Não deve ser executado em staging ou produção**
- Os dados são recriados a cada execução (limpa dados existentes)
- Todos os tenants criados têm configurações realistas para teste