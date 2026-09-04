from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from raffles.models import Raffle
from vouchers.models import Voucher


@pytest.mark.django_db
class TestRaffleModel:
    def test_default_status_is_draft(self, tenant_fixture):
        raffle = Raffle.objects.create(
            tenant=tenant_fixture,
            name="Sorteio de aniversário",
            prize_voucher_type=Voucher.VoucherType.PERCENT,
            prize_value=Decimal("10.00"),
        )
        assert raffle.status == Raffle.Status.DRAFT

    def test_str(self, tenant_fixture):
        raffle = Raffle.objects.create(
            tenant=tenant_fixture,
            name="Sorteio de Natal",
            prize_voucher_type=Voucher.VoucherType.FIXED,
            prize_value=Decimal("5.00"),
        )
        assert str(raffle) == f"Sorteio de Natal ({tenant_fixture.id})"

    def test_clean_requires_prize_value_for_percent(self, tenant_fixture):
        raffle = Raffle(
            tenant=tenant_fixture,
            name="Sem valor",
            prize_voucher_type=Voucher.VoucherType.PERCENT,
        )
        with pytest.raises(ValidationError):
            raffle.clean()

    def test_clean_requires_prize_value_for_fixed(self, tenant_fixture):
        raffle = Raffle(
            tenant=tenant_fixture,
            name="Sem valor",
            prize_voucher_type=Voucher.VoucherType.FIXED,
        )
        with pytest.raises(ValidationError):
            raffle.clean()

    def test_clean_requires_prize_service_for_free_service(self, tenant_fixture):
        raffle = Raffle(
            tenant=tenant_fixture,
            name="Sem serviço",
            prize_voucher_type=Voucher.VoucherType.FREE_SERVICE,
        )
        with pytest.raises(ValidationError):
            raffle.clean()

    def test_clean_passes_for_free_service_with_service(
        self, tenant_fixture, service_fixture
    ):
        raffle = Raffle(
            tenant=tenant_fixture,
            name="Com serviço",
            prize_voucher_type=Voucher.VoucherType.FREE_SERVICE,
            prize_service=service_fixture,
        )
        raffle.clean()

    def test_participants_m2m(self, tenant_fixture):
        from core.models import SalonCustomer

        raffle = Raffle.objects.create(
            tenant=tenant_fixture,
            name="Sorteio",
            prize_voucher_type=Voucher.VoucherType.PERCENT,
            prize_value=Decimal("10.00"),
        )
        client1 = SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente 1")
        client2 = SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente 2")
        raffle.participants.add(client1, client2)

        assert raffle.participants.count() == 2
