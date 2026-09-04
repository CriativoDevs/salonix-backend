"""
BE-MARKETING-04 (#522): task assíncrona que efetivamente envia os emails de
uma campanha já aprovada/contabilizada pela view.
"""

from unittest.mock import patch

import pytest
from django.utils import timezone

from core.models import SalonCustomer
from notifications.models import EmailMarketingCampaign
from notifications.tasks import send_marketing_campaign_task


def _capture_send():
    calls = []

    def fake(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return True

    return calls, fake


@pytest.mark.django_db
class TestSendMarketingCampaignTask:
    def _campaign(self, tenant_fixture, **kwargs):
        return EmailMarketingCampaign.objects.create(
            tenant=tenant_fixture,
            subject=kwargs.pop("subject", "Promoção"),
            body=kwargs.pop("body", "Descontos especiais"),
            reply_to=kwargs.pop("reply_to", None),
            status=EmailMarketingCampaign.Status.QUEUED,
            eligible_count=kwargs.pop("eligible_count", 1),
            free_sent_count=kwargs.pop("free_sent_count", 1),
            **kwargs,
        )

    def test_sends_email_to_each_customer_and_marks_completed(self, tenant_fixture):
        c1 = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Cliente 1", email="c1@example.com"
        )
        c2 = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Cliente 2", email="c2@example.com"
        )
        campaign = self._campaign(tenant_fixture, free_sent_count=2, eligible_count=2)

        calls, fake = _capture_send()
        with patch("core.email_utils.send_marketing_email", side_effect=fake):
            result = send_marketing_campaign_task(campaign.id, [c1.id, c2.id])

        assert result == 2
        assert len(calls) == 2
        sent_emails = {c["kwargs"]["to_email"] for c in calls}
        assert sent_emails == {"c1@example.com", "c2@example.com"}

        campaign.refresh_from_db()
        assert campaign.status == EmailMarketingCampaign.Status.COMPLETED
        assert campaign.completed_at is not None

    def test_passes_reply_to_and_salon_name(self, tenant_fixture):
        customer = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Cliente", email="c@example.com"
        )
        campaign = self._campaign(
            tenant_fixture, reply_to="owner@example.com", free_sent_count=1
        )

        calls, fake = _capture_send()
        with patch("core.email_utils.send_marketing_email", side_effect=fake):
            send_marketing_campaign_task(campaign.id, [customer.id])

        kwargs = calls[0]["kwargs"]
        assert kwargs["reply_to"] == "owner@example.com"
        assert kwargs["salon_name"] == tenant_fixture.name
        assert kwargs["tenant_id"] == tenant_fixture.id
        assert kwargs["customer_id"] == customer.id

    def test_skips_customer_without_email(self, tenant_fixture):
        # Sem email — não deveria acontecer (elegibilidade já filtra), mas a
        # task não deve quebrar se acontecer.
        customer = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Sem Email", email=""
        )
        campaign = self._campaign(tenant_fixture, free_sent_count=1)

        calls, fake = _capture_send()
        with patch("core.email_utils.send_marketing_email", side_effect=fake):
            result = send_marketing_campaign_task(campaign.id, [customer.id])

        assert result == 0
        assert len(calls) == 0
        campaign.refresh_from_db()
        assert campaign.status == EmailMarketingCampaign.Status.COMPLETED

    def test_unknown_campaign_id_does_not_raise(self, tenant_fixture):
        # Não deve lançar exceção — apenas loga e retorna.
        send_marketing_campaign_task(999999, [1, 2, 3])
