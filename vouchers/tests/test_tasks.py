from unittest.mock import patch

import pytest

from core.models import SalonCustomer
from vouchers.models import ClientVoucher, Voucher
from vouchers.tasks import send_voucher_email_task


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
