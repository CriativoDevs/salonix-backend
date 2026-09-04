# 🇬🇧 Raffles Overview — Salonix Backend (EN)

## Overview
`raffles` lets a tenant run a raffle among its clients and automatically hand the winner a voucher. Standby feature (BE-RAFFLE-01, #475) — backend only, no FE/MOB screens yet.

## Model
`Raffle` (`raffles/models.py`): `tenant`, `name`, `prize_description`, `prize_voucher_type` (reuses `Voucher.VoucherType`: percent/fixed/free_service), `prize_value`, `prize_service`, `status` (`draft`/`drawn`), `participants` (M2M `core.SalonCustomer`), `winner`, `winner_voucher` (`vouchers.ClientVoucher`), `drawn_at`, `created_at`.

Prize fields mirror `vouchers.Voucher` on purpose: drawing a raffle creates a real `Voucher` + `ClientVoucher` from them, reusing the same assignment pattern as `VoucherViewSet._assign_voucher_to_client`.

## Endpoints
All under `/api/raffles/`, owner/manager only except list/retrieve (any authenticated staff of the tenant):

- `POST /api/raffles/` — create a raffle.
- `GET/PATCH/DELETE /api/raffles/{id}/` — standard CRUD.
- `POST /api/raffles/{id}/add-participants/` — body `{"client_ids": [...]}` and/or `{"all": true}` (all active clients of the tenant). Rejects clients from other tenants. Blocked once the raffle is `drawn`.
- `POST /api/raffles/{id}/draw/` — draws one random participant, creates the prize `Voucher` + `ClientVoucher`, sets `winner`/`winner_voucher`/`drawn_at`, flips `status` to `drawn`. Requires at least one participant. Returns 400 if already drawn — **the status check runs before any side effect, so a repeated call never recreates a voucher or changes the winner.**

## Multi-tenancy & permissions
Same pattern as `vouchers/`: `TenantIsolatedMixin` scopes querysets, tenant always comes from the authenticated user's membership (never client-supplied), and mutating actions require owner/manager role.

## Tests
`raffles/tests/test_models.py` and `raffles/tests/test_views.py` (34 tests): random draw, draw idempotency, correct voucher generation/assignment, tenant isolation on add-participants and draw.

## Links
- Voucher system this feature builds on: see `vouchers/models.py` and `VoucherViewSet` in `vouchers/views.py`.

---

# 🇧🇷 Visão Geral de Sorteios (Raffles) — Salonix Backend (PT)

## Visão Geral
O app `raffles` permite que um tenant realize um sorteio entre seus clientes e atribua automaticamente um voucher ao vencedor. Feature em standby (BE-RAFFLE-01, #475) — apenas backend, sem telas de FE/MOB ainda.

## Modelo
`Raffle` (`raffles/models.py`): `tenant`, `name`, `prize_description`, `prize_voucher_type` (reaproveita `Voucher.VoucherType`: percent/fixed/free_service), `prize_value`, `prize_service`, `status` (`draft`/`drawn`), `participants` (M2M `core.SalonCustomer`), `winner`, `winner_voucher` (`vouchers.ClientVoucher`), `drawn_at`, `created_at`.

Os campos de prêmio espelham `vouchers.Voucher` de propósito: ao sortear, um `Voucher` real + `ClientVoucher` são criados a partir deles, reaproveitando o mesmo padrão de atribuição de `VoucherViewSet._assign_voucher_to_client`.

## Endpoints
Todos sob `/api/raffles/`, restritos a owner/manager exceto list/retrieve (qualquer staff autenticado do tenant):

- `POST /api/raffles/` — cria um sorteio.
- `GET/PATCH/DELETE /api/raffles/{id}/` — CRUD padrão.
- `POST /api/raffles/{id}/add-participants/` — body `{"client_ids": [...]}` e/ou `{"all": true}` (todos os clientes ativos do tenant). Rejeita clientes de outro tenant. Bloqueado depois que o sorteio vira `drawn`.
- `POST /api/raffles/{id}/draw/` — sorteia um participante aleatório, cria o `Voucher` + `ClientVoucher` do prêmio, define `winner`/`winner_voucher`/`drawn_at`, muda `status` para `drawn`. Exige ao menos um participante. Retorna 400 se já sorteado — **a checagem de status acontece antes de qualquer efeito colateral, então uma segunda chamada nunca recria voucher nem troca o vencedor.**

## Multi-tenancy & permissões
Mesmo padrão de `vouchers/`: `TenantIsolatedMixin` escopa as querysets, o tenant sempre vem do membership do usuário autenticado (nunca client-supplied), e ações de escrita exigem papel owner/manager.

## Testes
`raffles/tests/test_models.py` e `raffles/tests/test_views.py` (34 testes): sorteio aleatório, idempotência do sorteio, geração/atribuição correta do voucher, isolamento multi-tenant em add-participants e draw.

## Links
- Sistema de voucher em que esta feature se apoia: ver `vouchers/models.py` e `VoucherViewSet` em `vouchers/views.py`.
