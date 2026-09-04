"""
BE-MARKETING-04 (#522): endpoint para o tenant compor/disparar campanhas de
email marketing e consultar o histórico.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import CustomerCommunicationConsent, SalonCustomer
from notifications.models import EmailMarketingCampaign
from users.models import Tenant, TenantStaffMember

User = get_user_model()

URL = "/api/notifications/marketing-campaigns/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def owner_user(db, tenant_fixture):
    user = User.objects.create_user(
        username="campaign-owner", email="campaign-owner@test.com", password="x"
    )
    TenantStaffMember.objects.create(
        tenant=tenant_fixture,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def manager_user(db, tenant_fixture):
    user = User.objects.create_user(
        username="campaign-manager", email="campaign-manager@test.com", password="x"
    )
    TenantStaffMember.objects.create(
        tenant=tenant_fixture,
        user=user,
        role=TenantStaffMember.Role.MANAGER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def staff_user(db, tenant_fixture):
    user = User.objects.create_user(
        username="campaign-staff", email="campaign-staff@test.com", password="x"
    )
    TenantStaffMember.objects.create(
        tenant=tenant_fixture,
        user=user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


def _consented_customer(tenant, email, name="Cliente"):
    customer = SalonCustomer.objects.create(tenant=tenant, name=name, email=email)
    CustomerCommunicationConsent.objects.create(
        tenant=tenant,
        customer=customer,
        channel="email",
        purpose="marketing",
        status="consented",
    )
    return customer


@pytest.mark.django_db
class TestMarketingCampaignCreate:
    def test_staff_without_owner_or_manager_role_is_forbidden(
        self, api_client, staff_user
    ):
        api_client.force_authenticate(user=staff_user)
        resp = api_client.post(
            URL, {"subject": "Promo", "body": "Corpo"}, format="json"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_dispatches_async_task_never_sync(
        self, api_client, owner_user, tenant_fixture
    ):
        _consented_customer(tenant_fixture, "a@example.com")
        api_client.force_authenticate(user=owner_user)

        with patch(
            "notifications.views.send_marketing_campaign_task.delay"
        ) as mock_delay, patch("core.email_utils.send_marketing_email") as mock_send:
            resp = api_client.post(
                URL, {"subject": "Promo", "body": "Corpo"}, format="json"
            )

        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        mock_delay.assert_called_once()
        # Envio síncrono nunca deve acontecer diretamente na view.
        mock_send.assert_not_called()

    def test_respects_consent_and_unsubscribe(
        self, api_client, owner_user, tenant_fixture
    ):
        eligible = _consented_customer(tenant_fixture, "eligible@example.com")
        no_consent = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Sem Consentimento", email="no-consent@example.com"
        )
        unsub_customer = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Unsubscribed", email="unsub@example.com"
        )
        CustomerCommunicationConsent.objects.create(
            tenant=tenant_fixture,
            customer=unsub_customer,
            channel="email",
            purpose="marketing",
            status="withdrawn",
        )

        api_client.force_authenticate(user=owner_user)
        with patch(
            "notifications.views.send_marketing_campaign_task.delay"
        ) as mock_delay:
            resp = api_client.post(
                URL, {"subject": "Promo", "body": "Corpo"}, format="json"
            )

        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        data = resp.json()
        assert data["eligible_count"] == 1
        assert data["skipped_no_consent_count"] == 2
        assert data["free_sent_count"] == 1

        sent_ids = mock_delay.call_args[0][1]
        assert sent_ids == [eligible.id]

    def test_free_monthly_limit_respected(
        self, api_client, owner_user, tenant_fixture
    ):
        # 3 campanhas anteriores neste mês já consumiram 48 do free de 50.
        EmailMarketingCampaign.objects.create(
            tenant=tenant_fixture,
            subject="Anterior",
            body="x",
            free_sent_count=48,
            eligible_count=48,
            status=EmailMarketingCampaign.Status.COMPLETED,
        )
        for i in range(5):
            _consented_customer(tenant_fixture, f"c{i}@example.com", name=f"C{i}")

        api_client.force_authenticate(user=owner_user)
        with patch("notifications.views.send_marketing_campaign_task.delay"):
            resp = api_client.post(
                URL, {"subject": "Promo", "body": "Corpo"}, format="json"
            )

        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        data = resp.json()
        # Só restam 2 grátis (50 - 48); os outros 3 vão para crédito
        # (tenant_fixture tem saldo de sobra por default).
        assert data["eligible_count"] == 5
        assert data["free_sent_count"] == 2
        assert data["credit_sent_count"] == 3

    def test_overage_consumes_communication_credit_pool(
        self, api_client, owner_user, tenant_fixture
    ):
        tenant_fixture.comm_credit_eur = Decimal("100.00")
        tenant_fixture.save(update_fields=["comm_credit_eur"])
        EmailMarketingCampaign.objects.create(
            tenant=tenant_fixture,
            subject="Anterior",
            body="x",
            free_sent_count=50,
            eligible_count=50,
            status=EmailMarketingCampaign.Status.COMPLETED,
        )
        _consented_customer(tenant_fixture, "over1@example.com", name="Over1")
        _consented_customer(tenant_fixture, "over2@example.com", name="Over2")

        api_client.force_authenticate(user=owner_user)
        with patch("notifications.views.send_marketing_campaign_task.delay"):
            resp = api_client.post(
                URL, {"subject": "Promo", "body": "Corpo"}, format="json"
            )

        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        data = resp.json()
        assert data["free_sent_count"] == 0
        assert data["credit_sent_count"] == 2
        assert Decimal(data["credit_charged_eur"]) == Decimal("0.02")
        assert data["blocked_credit_count"] == 0

        tenant_fixture.refresh_from_db()
        assert tenant_fixture.comm_credit_eur == Decimal("99.98")

    def test_insufficient_credit_blocks_only_the_overage(
        self, api_client, owner_user, tenant_fixture
    ):
        # Sem crédito nenhum e sem renovação automática configurada.
        tenant_fixture.comm_credit_eur = Decimal("0.00")
        tenant_fixture.comm_auto_renew = False
        tenant_fixture.save(update_fields=["comm_credit_eur", "comm_auto_renew"])
        EmailMarketingCampaign.objects.create(
            tenant=tenant_fixture,
            subject="Anterior",
            body="x",
            free_sent_count=50,
            eligible_count=50,
            status=EmailMarketingCampaign.Status.COMPLETED,
        )
        c1 = _consented_customer(tenant_fixture, "blocked1@example.com", name="B1")
        c2 = _consented_customer(tenant_fixture, "blocked2@example.com", name="B2")

        api_client.force_authenticate(user=owner_user)
        with patch(
            "notifications.views.send_marketing_campaign_task.delay"
        ) as mock_delay:
            resp = api_client.post(
                URL, {"subject": "Promo", "body": "Corpo"}, format="json"
            )

        # A campanha inteira não é bloqueada — só o excedente sem crédito.
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        data = resp.json()
        assert data["eligible_count"] == 2
        assert data["free_sent_count"] == 0
        assert data["credit_sent_count"] == 0
        assert data["blocked_credit_count"] == 2
        assert data["status"] == "completed"  # nada para enviar
        mock_delay.assert_not_called()

    def test_reply_to_persisted_on_campaign(
        self, api_client, owner_user, tenant_fixture
    ):
        _consented_customer(tenant_fixture, "a@example.com")
        api_client.force_authenticate(user=owner_user)
        with patch("notifications.views.send_marketing_campaign_task.delay"):
            resp = api_client.post(
                URL,
                {
                    "subject": "Promo",
                    "body": "Corpo",
                    "reply_to": "dono@salao.example.com",
                },
                format="json",
            )
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        assert resp.json()["reply_to"] == "dono@salao.example.com"

    def test_manager_can_create_campaign(
        self, api_client, manager_user, tenant_fixture
    ):
        _consented_customer(tenant_fixture, "a@example.com")
        api_client.force_authenticate(user=manager_user)
        with patch("notifications.views.send_marketing_campaign_task.delay"):
            resp = api_client.post(
                URL, {"subject": "Promo", "body": "Corpo"}, format="json"
            )
        assert resp.status_code == status.HTTP_201_CREATED, resp.content


@pytest.mark.django_db
class TestMarketingCampaignHistory:
    def test_lists_only_own_tenant_campaigns(self, api_client, owner_user, tenant_fixture):
        other_tenant = Tenant.objects.create(slug="other-mkt", name="Other Mkt Tenant")
        EmailMarketingCampaign.objects.create(
            tenant=tenant_fixture, subject="Minha campanha", body="x"
        )
        EmailMarketingCampaign.objects.create(
            tenant=other_tenant, subject="Campanha de outro tenant", body="x"
        )

        api_client.force_authenticate(user=owner_user)
        resp = api_client.get(URL)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        results = data["results"] if isinstance(data, dict) and "results" in data else data
        subjects = [c["subject"] for c in results]
        assert "Minha campanha" in subjects
        assert "Campanha de outro tenant" not in subjects

    def test_history_reports_counts_correctly(
        self, api_client, owner_user, tenant_fixture
    ):
        EmailMarketingCampaign.objects.create(
            tenant=tenant_fixture,
            subject="Campanha X",
            body="x",
            eligible_count=10,
            skipped_no_consent_count=4,
            free_sent_count=6,
            credit_sent_count=2,
            credit_charged_eur=Decimal("0.02"),
            blocked_credit_count=2,
            status=EmailMarketingCampaign.Status.COMPLETED,
        )
        api_client.force_authenticate(user=owner_user)
        resp = api_client.get(URL)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        results = data["results"] if isinstance(data, dict) and "results" in data else data
        campaign = results[0]
        assert campaign["eligible_count"] == 10
        assert campaign["skipped_no_consent_count"] == 4
        assert campaign["free_sent_count"] == 6
        assert campaign["credit_sent_count"] == 2
        assert campaign["blocked_credit_count"] == 2
        assert campaign["total_sent_count"] == 8
