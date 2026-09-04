from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from core.models import SalonCustomer, Service
from raffles.models import Raffle
from users.models import Tenant, TenantStaffMember
from vouchers.models import ClientVoucher, Voucher

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        slug="raffle-tenant-b",
        name="Tenant B",
        plan_tier=Tenant.PLAN_BASIC,
    )


@pytest.fixture
def owner_user(db, tenant_fixture):
    user = User.objects.create_user(
        username="raffle-owner1", email="raffle-owner1@test.com", password="testpass123"
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
        username="raffle-manager1", email="raffle-manager1@test.com", password="testpass123"
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
        username="raffle-staff1", email="raffle-staff1@test.com", password="testpass123"
    )
    TenantStaffMember.objects.create(
        tenant=tenant_fixture,
        user=user,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def other_owner_user(db, other_tenant):
    user = User.objects.create_user(
        username="raffle-owner2",
        email="raffle-owner2@test.com",
        password="testpass123",
        tenant=other_tenant,
    )
    TenantStaffMember.objects.create(
        tenant=other_tenant,
        user=user,
        role=TenantStaffMember.Role.OWNER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    return user


@pytest.fixture
def customer1(db, tenant_fixture):
    return SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente 1")


@pytest.fixture
def customer2(db, tenant_fixture):
    return SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente 2")


@pytest.fixture
def customer3(db, tenant_fixture):
    return SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente 3")


@pytest.fixture
def other_customer(db, other_tenant):
    return SalonCustomer.objects.create(tenant=other_tenant, name="Cliente de outro tenant")


@pytest.fixture
def raffle_fixture(db, tenant_fixture):
    return Raffle.objects.create(
        tenant=tenant_fixture,
        name="Sorteio de teste",
        prize_description="Um corte grátis",
        prize_voucher_type=Voucher.VoucherType.PERCENT,
        prize_value=Decimal("15.00"),
    )


@pytest.fixture
def other_raffle_fixture(db, other_tenant):
    return Raffle.objects.create(
        tenant=other_tenant,
        name="Sorteio de outro tenant",
        prize_voucher_type=Voucher.VoucherType.FIXED,
        prize_value=Decimal("5.00"),
    )


@pytest.mark.django_db
class TestRaffleListCreate:
    url = "/api/raffles/"

    def test_owner_can_list_raffles(self, api_client, owner_user, raffle_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        names = [r["name"] for r in results]
        assert "Sorteio de teste" in names

    def test_staff_can_list_raffles(self, api_client, staff_user, raffle_fixture):
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK

    def test_list_does_not_include_other_tenant_raffles(
        self, api_client, owner_user, raffle_fixture, other_raffle_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        names = [r["name"] for r in results]
        assert "Sorteio de outro tenant" not in names

    def test_owner_can_create_raffle(self, api_client, owner_user, tenant_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url,
            {
                "name": "Sorteio de verão",
                "prize_description": "Massagem grátis",
                "prize_voucher_type": "percent",
                "prize_value": "20.00",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        raffle = Raffle.objects.get(id=response.json()["id"])
        assert raffle.tenant == tenant_fixture
        assert raffle.status == Raffle.Status.DRAFT

    def test_manager_can_create_raffle(self, api_client, manager_user):
        api_client.force_authenticate(user=manager_user)
        response = api_client.post(
            self.url,
            {"name": "Sorteio", "prize_voucher_type": "fixed", "prize_value": "5.00"},
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_staff_cannot_create_raffle(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        response = api_client.post(
            self.url,
            {"name": "Sorteio", "prize_voucher_type": "fixed", "prize_value": "5.00"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Raffle.objects.filter(name="Sorteio").exists()

    def test_unauthenticated_cannot_list(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_free_service_requires_prize_service(self, api_client, owner_user):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url, {"name": "Sorteio", "prize_voucher_type": "free_service"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_percent_requires_prize_value(self, api_client, owner_user):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url, {"name": "Sorteio", "prize_voucher_type": "percent"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_use_prize_service_from_other_tenant(
        self, api_client, owner_user, other_tenant
    ):
        other_service = Service.objects.create(
            tenant=other_tenant,
            user=User.objects.create_user(
                username="raffle-svc-owner", email="raffle-svc-owner@test.com", password="x"
            ),
            name="Serviço de outro tenant",
            duration_minutes=30,
            price_eur=10,
        )
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url,
            {
                "name": "Sorteio",
                "prize_voucher_type": "free_service",
                "prize_service": other_service.id,
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_other_tenant_cannot_retrieve_raffle(
        self, api_client, owner_user, other_raffle_fixture
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.get(f"{self.url}{other_raffle_fixture.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestRaffleAddParticipants:
    def url(self, raffle_id):
        return f"/api/raffles/{raffle_id}/add-participants/"

    def test_owner_can_add_participants_by_id(
        self, api_client, owner_user, raffle_fixture, customer1, customer2
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url(raffle_fixture.id),
            {"client_ids": [customer1.id, customer2.id]},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        raffle_fixture.refresh_from_db()
        assert raffle_fixture.participants.count() == 2

    def test_manager_can_add_participants(
        self, api_client, manager_user, raffle_fixture, customer1
    ):
        api_client.force_authenticate(user=manager_user)
        response = api_client.post(
            self.url(raffle_fixture.id), {"client_ids": [customer1.id]}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK

    def test_staff_cannot_add_participants(
        self, api_client, staff_user, raffle_fixture, customer1
    ):
        api_client.force_authenticate(user=staff_user)
        response = api_client.post(
            self.url(raffle_fixture.id), {"client_ids": [customer1.id]}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_add_all_clients_of_tenant(
        self, api_client, owner_user, raffle_fixture, customer1, customer2, customer3, other_customer
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url(raffle_fixture.id), {"all": True}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        raffle_fixture.refresh_from_db()
        assert raffle_fixture.participants.count() == 3
        assert other_customer not in raffle_fixture.participants.all()

    def test_rejects_client_of_other_tenant(
        self, api_client, owner_user, raffle_fixture, other_customer
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url(raffle_fixture.id),
            {"client_ids": [other_customer.id]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        raffle_fixture.refresh_from_db()
        assert raffle_fixture.participants.count() == 0

    def test_other_tenant_cannot_add_participants_to_foreign_raffle(
        self, api_client, owner_user, other_raffle_fixture, customer1
    ):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(
            self.url(other_raffle_fixture.id),
            {"client_ids": [customer1.id]},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_requires_client_ids_or_all(self, api_client, owner_user, raffle_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(self.url(raffle_fixture.id), {}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_add_participants_after_draw(
        self, api_client, owner_user, raffle_fixture, customer1, customer2
    ):
        raffle_fixture.participants.add(customer1)
        api_client.force_authenticate(user=owner_user)
        draw_response = api_client.post(f"/api/raffles/{raffle_fixture.id}/draw/")
        assert draw_response.status_code == status.HTTP_200_OK

        response = api_client.post(
            self.url(raffle_fixture.id), {"client_ids": [customer2.id]}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        raffle_fixture.refresh_from_db()
        assert raffle_fixture.participants.count() == 1


@pytest.mark.django_db
class TestRaffleDraw:
    def url(self, raffle_id):
        return f"/api/raffles/{raffle_id}/draw/"

    def test_draw_picks_one_of_the_participants(
        self, api_client, owner_user, raffle_fixture, customer1, customer2, customer3
    ):
        raffle_fixture.participants.add(customer1, customer2, customer3)
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(self.url(raffle_fixture.id))
        assert response.status_code == status.HTTP_200_OK

        raffle_fixture.refresh_from_db()
        assert raffle_fixture.status == Raffle.Status.DRAWN
        assert raffle_fixture.drawn_at is not None
        assert raffle_fixture.winner_id in {customer1.id, customer2.id, customer3.id}

    def test_draw_generates_voucher_assigned_to_winner(
        self, api_client, owner_user, raffle_fixture, customer1
    ):
        raffle_fixture.participants.add(customer1)
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(self.url(raffle_fixture.id))
        assert response.status_code == status.HTTP_200_OK

        raffle_fixture.refresh_from_db()
        assert raffle_fixture.winner_id == customer1.id
        assert raffle_fixture.winner_voucher is not None

        voucher = raffle_fixture.winner_voucher.voucher
        assert voucher.tenant_id == raffle_fixture.tenant_id
        assert voucher.type == raffle_fixture.prize_voucher_type
        assert voucher.value == raffle_fixture.prize_value

        client_voucher = ClientVoucher.objects.get(id=raffle_fixture.winner_voucher_id)
        assert client_voucher.client_id == customer1.id
        assert client_voucher.voucher_id == voucher.id

    def test_draw_with_free_service_prize_uses_prize_service(
        self, api_client, owner_user, tenant_fixture, customer1
    ):
        service = Service.objects.create(
            tenant=tenant_fixture,
            user=owner_user,
            name="Corte de sorteio",
            duration_minutes=30,
            price_eur=Decimal("25.00"),
        )
        raffle = Raffle.objects.create(
            tenant=tenant_fixture,
            name="Sorteio de serviço",
            prize_voucher_type=Voucher.VoucherType.FREE_SERVICE,
            prize_service=service,
        )
        raffle.participants.add(customer1)
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(self.url(raffle.id))
        assert response.status_code == status.HTTP_200_OK

        raffle.refresh_from_db()
        voucher = raffle.winner_voucher.voucher
        assert voucher.type == Voucher.VoucherType.FREE_SERVICE
        assert voucher.service_id == service.id

    def test_cannot_draw_without_participants(self, api_client, owner_user, raffle_fixture):
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(self.url(raffle_fixture.id))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        raffle_fixture.refresh_from_db()
        assert raffle_fixture.status == Raffle.Status.DRAFT
        assert raffle_fixture.winner is None

    def test_cannot_draw_twice(self, api_client, owner_user, raffle_fixture, customer1, customer2):
        raffle_fixture.participants.add(customer1, customer2)
        api_client.force_authenticate(user=owner_user)

        first_response = api_client.post(self.url(raffle_fixture.id))
        assert first_response.status_code == status.HTTP_200_OK
        raffle_fixture.refresh_from_db()
        winner_id_after_first = raffle_fixture.winner_id
        voucher_id_after_first = raffle_fixture.winner_voucher_id

        second_response = api_client.post(self.url(raffle_fixture.id))
        assert second_response.status_code == status.HTTP_400_BAD_REQUEST

        raffle_fixture.refresh_from_db()
        assert raffle_fixture.winner_id == winner_id_after_first
        assert raffle_fixture.winner_voucher_id == voucher_id_after_first
        assert Voucher.objects.filter(tenant=raffle_fixture.tenant).count() == 1
        assert ClientVoucher.objects.filter(tenant=raffle_fixture.tenant).count() == 1

    def test_manager_can_draw(self, api_client, manager_user, raffle_fixture, customer1):
        raffle_fixture.participants.add(customer1)
        api_client.force_authenticate(user=manager_user)
        response = api_client.post(self.url(raffle_fixture.id))
        assert response.status_code == status.HTTP_200_OK

    def test_staff_cannot_draw(self, api_client, staff_user, raffle_fixture, customer1):
        raffle_fixture.participants.add(customer1)
        api_client.force_authenticate(user=staff_user)
        response = api_client.post(self.url(raffle_fixture.id))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        raffle_fixture.refresh_from_db()
        assert raffle_fixture.status == Raffle.Status.DRAFT

    def test_other_tenant_cannot_draw_foreign_raffle(
        self, api_client, owner_user, other_raffle_fixture, other_customer
    ):
        other_raffle_fixture.participants.add(other_customer)
        api_client.force_authenticate(user=owner_user)
        response = api_client.post(self.url(other_raffle_fixture.id))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        other_raffle_fixture.refresh_from_db()
        assert other_raffle_fixture.status == Raffle.Status.DRAFT
