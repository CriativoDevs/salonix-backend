import datetime
from unittest.mock import patch

import pytest
from django.utils import timezone

from core.models import SalonCustomer
from users.models import Tenant
from vouchers.models import BirthdayVoucherConfig, BirthdayVoucherLog, ClientVoucher, Voucher
from vouchers.tasks import send_birthday_vouchers, send_voucher_email_task


def _capture_send():
    calls = []

    def fake(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return True

    return calls, fake


@pytest.mark.django_db
class TestSendVoucherEmailTask:
    def _client_voucher(self, tenant_fixture, **voucher_kwargs):
        voucher = Voucher.objects.create(
            tenant=tenant_fixture,
            code=voucher_kwargs.pop("code", "TASKCODE"),
            type=voucher_kwargs.pop("type", Voucher.VoucherType.PERCENT),
            value=voucher_kwargs.pop("value", 10),
            **voucher_kwargs,
        )
        client = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Cliente Task", email="task@test.com"
        )
        return ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=client
        )

    def test_sends_email_and_records_sent_at(self, tenant_fixture):
        client_voucher = self._client_voucher(tenant_fixture)
        calls, fake = _capture_send()

        with patch("vouchers.tasks.send_voucher_email", side_effect=fake):
            send_voucher_email_task(client_voucher.id)

        assert len(calls) == 1
        kwargs = calls[0]["kwargs"]
        assert kwargs["to_email"] == "task@test.com"
        assert kwargs["voucher_code"] == "TASKCODE"

        client_voucher.refresh_from_db()
        assert client_voucher.sent_at is not None

    def test_resend_updates_sent_at_again(self, tenant_fixture):
        client_voucher = self._client_voucher(tenant_fixture)
        _, fake = _capture_send()

        with patch("vouchers.tasks.send_voucher_email", side_effect=fake):
            send_voucher_email_task(client_voucher.id)
            client_voucher.refresh_from_db()
            first_sent_at = client_voucher.sent_at

            send_voucher_email_task(client_voucher.id)
            client_voucher.refresh_from_db()

        assert client_voucher.sent_at is not None
        assert client_voucher.sent_at >= first_sent_at

    def test_missing_client_voucher_does_not_raise(self, db):
        with patch("vouchers.tasks.send_voucher_email") as mock_send:
            send_voucher_email_task(999999)
        mock_send.assert_not_called()

    def test_client_without_email_does_not_send(self, tenant_fixture):
        voucher = Voucher.objects.create(
            tenant=tenant_fixture,
            code="NOEMAIL1",
            type=Voucher.VoucherType.FIXED,
            value=5,
        )
        client = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Sem Email"
        )
        client_voucher = ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=client
        )

        with patch("vouchers.tasks.send_voucher_email") as mock_send:
            send_voucher_email_task(client_voucher.id)

        mock_send.assert_not_called()
        client_voucher.refresh_from_db()
        assert client_voucher.sent_at is None


def _birthday_on(month: int, day: int) -> datetime.date:
    """Data de nascimento com mês/dia dados, ano fixo no passado."""
    return datetime.date(1990, month, day)


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        slug="birthday-tenant-b",
        name="Tenant B",
        plan_tier=Tenant.PLAN_BASIC,
    )


@pytest.mark.django_db
class TestSendBirthdayVouchersTask:
    def test_sends_voucher_to_client_born_today_when_config_active(self, tenant_fixture):
        today = timezone.localdate()
        config = BirthdayVoucherConfig.objects.create(
            tenant=tenant_fixture,
            voucher_type=Voucher.VoucherType.PERCENT,
            voucher_value=20,
            validity_days=15,
            is_selected=True,
        )
        client = SalonCustomer.objects.create(
            tenant=tenant_fixture,
            name="Aniversariante",
            email="aniversariante@test.com",
            birthday=_birthday_on(today.month, today.day),
        )

        with patch("vouchers.tasks.send_voucher_email_task.delay") as mock_delay:
            result = send_birthday_vouchers()

        assert result["vouchers_sent"] == 1
        mock_delay.assert_called_once()

        client_voucher = ClientVoucher.objects.get(client=client)
        assert client_voucher.tenant == tenant_fixture
        assert client_voucher.voucher.type == Voucher.VoucherType.PERCENT
        assert client_voucher.voucher.value == 20
        assert client_voucher.voucher.valid_until == today + datetime.timedelta(days=15)

        log = BirthdayVoucherLog.objects.get(tenant=tenant_fixture, client=client)
        assert log.sent_date == today
        assert log.client_voucher == client_voucher
        assert config  # sanity: config used above

    def test_config_not_selected_is_skipped(self, tenant_fixture):
        today = timezone.localdate()
        BirthdayVoucherConfig.objects.create(
            tenant=tenant_fixture, is_selected=False
        )
        SalonCustomer.objects.create(
            tenant=tenant_fixture,
            name="Aniversariante",
            email="a@test.com",
            birthday=_birthday_on(today.month, today.day),
        )

        with patch("vouchers.tasks.send_voucher_email_task.delay") as mock_delay:
            result = send_birthday_vouchers()

        assert result["vouchers_sent"] == 0
        mock_delay.assert_not_called()
        assert not ClientVoucher.objects.exists()
        assert not BirthdayVoucherLog.objects.exists()

    def test_job_uses_selected_template_when_tenant_has_multiple(
        self, tenant_fixture
    ):
        today = timezone.localdate()
        BirthdayVoucherConfig.objects.create(
            tenant=tenant_fixture,
            voucher_type=Voucher.VoucherType.PERCENT,
            voucher_value=5,
            is_selected=False,
        )
        BirthdayVoucherConfig.objects.create(
            tenant=tenant_fixture,
            voucher_type=Voucher.VoucherType.FIXED,
            voucher_value=25,
            is_selected=True,
        )
        client = SalonCustomer.objects.create(
            tenant=tenant_fixture,
            name="Aniversariante",
            email="aniversariante@test.com",
            birthday=_birthday_on(today.month, today.day),
        )

        with patch("vouchers.tasks.send_voucher_email_task.delay"):
            result = send_birthday_vouchers()

        assert result["vouchers_sent"] == 1
        client_voucher = ClientVoucher.objects.get(client=client)
        assert client_voucher.voucher.type == Voucher.VoucherType.FIXED
        assert client_voucher.voucher.value == 25

    def test_no_config_at_all_is_skipped(self, tenant_fixture):
        today = timezone.localdate()
        SalonCustomer.objects.create(
            tenant=tenant_fixture,
            name="Aniversariante",
            email="a@test.com",
            birthday=_birthday_on(today.month, today.day),
        )

        with patch("vouchers.tasks.send_voucher_email_task.delay") as mock_delay:
            result = send_birthday_vouchers()

        assert result["vouchers_sent"] == 0
        mock_delay.assert_not_called()

    def test_ignores_clients_not_born_today(self, tenant_fixture):
        today = timezone.localdate()
        not_today = (today + datetime.timedelta(days=1)).replace(
            year=1990
        ) if today.month != 12 or today.day != 31 else datetime.date(1990, 1, 1)
        BirthdayVoucherConfig.objects.create(tenant=tenant_fixture, is_selected=True)
        SalonCustomer.objects.create(
            tenant=tenant_fixture,
            name="Nao aniversariante",
            email="b@test.com",
            birthday=not_today,
        )

        with patch("vouchers.tasks.send_voucher_email_task.delay") as mock_delay:
            result = send_birthday_vouchers()

        assert result["vouchers_sent"] == 0
        mock_delay.assert_not_called()

    def test_ignores_clients_without_birthday(self, tenant_fixture):
        BirthdayVoucherConfig.objects.create(tenant=tenant_fixture, is_selected=True)
        SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Sem data", email="c@test.com"
        )

        with patch("vouchers.tasks.send_voucher_email_task.delay") as mock_delay:
            result = send_birthday_vouchers()

        assert result["vouchers_sent"] == 0
        mock_delay.assert_not_called()

    def test_running_twice_same_day_is_idempotent(self, tenant_fixture):
        today = timezone.localdate()
        BirthdayVoucherConfig.objects.create(tenant=tenant_fixture, is_selected=True)
        SalonCustomer.objects.create(
            tenant=tenant_fixture,
            name="Aniversariante",
            email="dup@test.com",
            birthday=_birthday_on(today.month, today.day),
        )

        with patch("vouchers.tasks.send_voucher_email_task.delay") as mock_delay:
            first = send_birthday_vouchers()
            second = send_birthday_vouchers()

        assert first["vouchers_sent"] == 1
        assert second["vouchers_sent"] == 0
        assert mock_delay.call_count == 1
        assert ClientVoucher.objects.count() == 1
        assert BirthdayVoucherLog.objects.count() == 1

    def test_tenant_isolation(self, tenant_fixture, other_tenant):
        today = timezone.localdate()
        BirthdayVoucherConfig.objects.create(
            tenant=tenant_fixture, voucher_type=Voucher.VoucherType.PERCENT, voucher_value=10, is_selected=True
        )
        BirthdayVoucherConfig.objects.create(
            tenant=other_tenant, voucher_type=Voucher.VoucherType.FIXED, voucher_value=5, is_selected=True
        )
        client_a = SalonCustomer.objects.create(
            tenant=tenant_fixture,
            name="Cliente A",
            email="a@test.com",
            birthday=_birthday_on(today.month, today.day),
        )
        client_b = SalonCustomer.objects.create(
            tenant=other_tenant,
            name="Cliente B",
            email="b@test.com",
            birthday=_birthday_on(today.month, today.day),
        )

        with patch("vouchers.tasks.send_voucher_email_task.delay"):
            result = send_birthday_vouchers()

        assert result["vouchers_sent"] == 2

        cv_a = ClientVoucher.objects.get(client=client_a)
        cv_b = ClientVoucher.objects.get(client=client_b)
        assert cv_a.tenant == tenant_fixture
        assert cv_a.voucher.tenant == tenant_fixture
        assert cv_a.voucher.type == Voucher.VoucherType.PERCENT
        assert cv_b.tenant == other_tenant
        assert cv_b.voucher.tenant == other_tenant
        assert cv_b.voucher.type == Voucher.VoucherType.FIXED

    def test_inactive_client_is_skipped(self, tenant_fixture):
        today = timezone.localdate()
        BirthdayVoucherConfig.objects.create(tenant=tenant_fixture, is_selected=True)
        SalonCustomer.objects.create(
            tenant=tenant_fixture,
            name="Inativo",
            email="inactive@test.com",
            birthday=_birthday_on(today.month, today.day),
            is_active=False,
        )

        with patch("vouchers.tasks.send_voucher_email_task.delay") as mock_delay:
            result = send_birthday_vouchers()

        assert result["vouchers_sent"] == 0
        mock_delay.assert_not_called()
