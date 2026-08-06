import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from core.models import SalonCustomer, Service
from users.models import Tenant
from vouchers.models import BirthdayVoucherConfig, BirthdayVoucherLog, ClientVoucher, Voucher


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(
        slug="tenant-b",
        name="Tenant B",
        plan_tier=Tenant.PLAN_BASIC,
    )


def make_voucher(tenant, **overrides):
    defaults = dict(
        tenant=tenant,
        type=Voucher.VoucherType.PERCENT,
        value=10,
    )
    defaults.update(overrides)
    return Voucher.objects.create(**defaults)


@pytest.mark.django_db
class TestVoucherModel:
    def test_create_percent_voucher(self, tenant_fixture):
        voucher = make_voucher(tenant_fixture, code="ABC12345")
        assert voucher.pk is not None
        assert voucher.tenant == tenant_fixture
        assert voucher.type == Voucher.VoucherType.PERCENT
        assert voucher.value == 10
        assert voucher.code == "ABC12345"
        assert voucher.max_uses == 1
        assert voucher.created_at is not None

    def test_str_representation(self, tenant_fixture):
        voucher = make_voucher(tenant_fixture, code="ABC12345")
        assert "ABC12345" in str(voucher)

    def test_code_generated_automatically_when_blank(self, tenant_fixture):
        voucher = make_voucher(tenant_fixture)
        assert voucher.code
        assert len(voucher.code) == 8
        assert voucher.code.isupper() or voucher.code.isdigit()

    def test_generated_codes_are_unique_per_tenant(self, tenant_fixture):
        codes = {make_voucher(tenant_fixture).code for _ in range(20)}
        assert len(codes) == 20

    def test_code_is_normalized_to_uppercase(self, tenant_fixture):
        voucher = make_voucher(tenant_fixture, code="abc123de")
        assert voucher.code == "ABC123DE"

    def test_unique_code_per_tenant(self, tenant_fixture):
        make_voucher(tenant_fixture, code="DUPLICAT")
        with pytest.raises(IntegrityError):
            make_voucher(tenant_fixture, code="DUPLICAT")

    def test_same_code_allowed_across_tenants(self, tenant_fixture, other_tenant):
        voucher_a = make_voucher(tenant_fixture, code="SAMECODE")
        voucher_b = make_voucher(other_tenant, code="SAMECODE")
        assert voucher_a.pk != voucher_b.pk
        assert voucher_a.tenant != voucher_b.tenant

    def test_isolation_between_tenants(self, tenant_fixture, other_tenant):
        make_voucher(tenant_fixture, code="TENANTA1")
        make_voucher(other_tenant, code="TENANTB1")

        tenant_vouchers = Voucher.objects.filter(tenant=tenant_fixture)
        other_vouchers = Voucher.objects.filter(tenant=other_tenant)

        assert list(tenant_vouchers.values_list("code", flat=True)) == ["TENANTA1"]
        assert list(other_vouchers.values_list("code", flat=True)) == ["TENANTB1"]

    def test_deleting_tenant_cascades_vouchers(self, tenant_fixture):
        voucher = make_voucher(tenant_fixture, code="TOCASCAD")
        voucher_id = voucher.pk
        tenant_fixture.delete()
        assert not Voucher.objects.filter(pk=voucher_id).exists()

    def test_free_service_voucher_requires_service(self, tenant_fixture):
        voucher = Voucher(
            tenant=tenant_fixture,
            type=Voucher.VoucherType.FREE_SERVICE,
            value=None,
        )
        with pytest.raises(ValidationError):
            voucher.full_clean()

    def test_free_service_voucher_allows_null_value(
        self, tenant_fixture, service_fixture
    ):
        voucher = make_voucher(
            tenant_fixture,
            code="FREESERV",
            type=Voucher.VoucherType.FREE_SERVICE,
            value=None,
            service=service_fixture,
        )
        assert voucher.value is None
        assert voucher.service == service_fixture

    def test_percent_voucher_requires_value(self, tenant_fixture):
        voucher = Voucher(
            tenant=tenant_fixture,
            type=Voucher.VoucherType.PERCENT,
            value=None,
        )
        with pytest.raises(ValidationError):
            voucher.full_clean()

    def test_fixed_voucher_requires_value(self, tenant_fixture):
        voucher = Voucher(
            tenant=tenant_fixture,
            type=Voucher.VoucherType.FIXED,
            value=None,
        )
        with pytest.raises(ValidationError):
            voucher.full_clean()

    def test_ordering_defaults_to_most_recent_first(self, tenant_fixture):
        first = make_voucher(tenant_fixture, code="FIRSTONE")
        second = make_voucher(tenant_fixture, code="SECONDON")
        codes = list(
            Voucher.objects.filter(tenant=tenant_fixture).values_list(
                "code", flat=True
            )
        )
        assert codes == [second.code, first.code]

    def test_max_uses_defaults_to_one(self, tenant_fixture):
        voucher = make_voucher(tenant_fixture)
        assert voucher.max_uses == 1

    def test_valid_until_and_notes_optional(self, tenant_fixture):
        voucher = make_voucher(tenant_fixture)
        assert voucher.valid_until is None
        assert voucher.notes == ""


@pytest.fixture
def customer_fixture(db, tenant_fixture):
    return SalonCustomer.objects.create(tenant=tenant_fixture, name="Cliente Teste")


@pytest.mark.django_db
class TestClientVoucherModel:
    def test_assign_voucher_to_client(self, tenant_fixture, customer_fixture):
        voucher = make_voucher(tenant_fixture, code="ASSIGNED1")
        client_voucher = ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=customer_fixture
        )
        assert client_voucher.pk is not None
        assert client_voucher.assigned_at is not None
        assert client_voucher.used_at is None
        assert client_voucher.used_in_booking is None

    def test_str_representation(self, tenant_fixture, customer_fixture):
        voucher = make_voucher(tenant_fixture, code="ASSIGNED1")
        client_voucher = ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=customer_fixture
        )
        assert voucher.code in str(client_voucher)

    def test_cannot_assign_same_voucher_twice_to_same_client(
        self, tenant_fixture, customer_fixture
    ):
        voucher = make_voucher(tenant_fixture, code="ASSIGNED1")
        ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=customer_fixture
        )
        with pytest.raises(IntegrityError):
            ClientVoucher.objects.create(
                tenant=tenant_fixture, voucher=voucher, client=customer_fixture
            )

    def test_same_voucher_can_be_assigned_to_different_clients(
        self, tenant_fixture, customer_fixture
    ):
        voucher = make_voucher(tenant_fixture, code="ASSIGNED1", max_uses=2)
        other_customer = SalonCustomer.objects.create(
            tenant=tenant_fixture, name="Outro Cliente"
        )
        ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=customer_fixture
        )
        second = ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=other_customer
        )
        assert second.pk is not None

    def test_status_active_by_default(self, tenant_fixture, customer_fixture):
        voucher = make_voucher(tenant_fixture, code="ASSIGNED1")
        client_voucher = ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=customer_fixture
        )
        assert client_voucher.status == ClientVoucher.Status.ACTIVE

    def test_status_used_when_used_at_set(self, tenant_fixture, customer_fixture):
        voucher = make_voucher(tenant_fixture, code="ASSIGNED1")
        client_voucher = ClientVoucher.objects.create(
            tenant=tenant_fixture,
            voucher=voucher,
            client=customer_fixture,
            used_at=timezone.now(),
        )
        assert client_voucher.status == ClientVoucher.Status.USED

    def test_status_expired_when_voucher_valid_until_in_past(
        self, tenant_fixture, customer_fixture
    ):
        voucher = make_voucher(
            tenant_fixture,
            code="ASSIGNED1",
            valid_until=timezone.localdate() - datetime.timedelta(days=1),
        )
        client_voucher = ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=customer_fixture
        )
        assert client_voucher.status == ClientVoucher.Status.EXPIRED

    def test_status_used_takes_precedence_over_expired(
        self, tenant_fixture, customer_fixture
    ):
        voucher = make_voucher(
            tenant_fixture,
            code="ASSIGNED1",
            valid_until=timezone.localdate() - datetime.timedelta(days=1),
        )
        client_voucher = ClientVoucher.objects.create(
            tenant=tenant_fixture,
            voucher=voucher,
            client=customer_fixture,
            used_at=timezone.now(),
        )
        assert client_voucher.status == ClientVoucher.Status.USED

    def test_deleting_voucher_cascades_client_voucher(
        self, tenant_fixture, customer_fixture
    ):
        voucher = make_voucher(tenant_fixture, code="ASSIGNED1")
        client_voucher = ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=customer_fixture
        )
        voucher_id = client_voucher.pk
        voucher.delete()
        assert not ClientVoucher.objects.filter(pk=voucher_id).exists()

    def test_deleting_client_cascades_client_voucher(
        self, tenant_fixture, customer_fixture
    ):
        voucher = make_voucher(tenant_fixture, code="ASSIGNED1")
        client_voucher = ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=customer_fixture
        )
        client_voucher_id = client_voucher.pk
        customer_fixture.delete()
        assert not ClientVoucher.objects.filter(pk=client_voucher_id).exists()


@pytest.mark.django_db
class TestBirthdayVoucherConfigModel:
    def test_create_defaults_to_unselected(self, tenant_fixture):
        config = BirthdayVoucherConfig.objects.create(tenant=tenant_fixture)
        assert config.pk is not None
        assert config.is_selected is False
        assert config.voucher_type == Voucher.VoucherType.PERCENT
        assert config.voucher_value == 10
        assert config.validity_days == 30

    def test_up_to_three_configs_per_tenant_allowed(self, tenant_fixture):
        for _ in range(3):
            BirthdayVoucherConfig.objects.create(tenant=tenant_fixture)
        assert (
            BirthdayVoucherConfig.objects.filter(tenant=tenant_fixture).count() == 3
        )

    def test_fourth_config_per_tenant_is_rejected(self, tenant_fixture):
        for _ in range(3):
            BirthdayVoucherConfig.objects.create(tenant=tenant_fixture)

        fourth = BirthdayVoucherConfig(tenant=tenant_fixture)
        with pytest.raises(ValidationError):
            fourth.full_clean()

    def test_different_tenants_each_get_their_own_limit(
        self, tenant_fixture, other_tenant
    ):
        for _ in range(3):
            BirthdayVoucherConfig.objects.create(tenant=tenant_fixture)
        # Não deve levantar - é o primeiro template do outro tenant.
        other_config = BirthdayVoucherConfig(tenant=other_tenant)
        other_config.full_clean()

    def test_updating_existing_config_does_not_count_against_limit(
        self, tenant_fixture
    ):
        configs = [
            BirthdayVoucherConfig.objects.create(tenant=tenant_fixture)
            for _ in range(3)
        ]
        configs[0].validity_days = 60
        configs[0].full_clean()  # não deve levantar mesmo já havendo 3

    def test_selecting_one_config_unselects_others_of_same_tenant(
        self, tenant_fixture
    ):
        first = BirthdayVoucherConfig.objects.create(
            tenant=tenant_fixture, is_selected=True
        )
        second = BirthdayVoucherConfig.objects.create(tenant=tenant_fixture)

        second.is_selected = True
        second.save()

        first.refresh_from_db()
        assert first.is_selected is False
        assert second.is_selected is True

    def test_selecting_does_not_affect_other_tenants(
        self, tenant_fixture, other_tenant
    ):
        own = BirthdayVoucherConfig.objects.create(
            tenant=tenant_fixture, is_selected=True
        )
        other = BirthdayVoucherConfig.objects.create(
            tenant=other_tenant, is_selected=True
        )

        own.refresh_from_db()
        other.refresh_from_db()
        assert own.is_selected is True
        assert other.is_selected is True

    def test_free_service_requires_service(self, tenant_fixture):
        config = BirthdayVoucherConfig(
            tenant=tenant_fixture,
            voucher_type=Voucher.VoucherType.FREE_SERVICE,
            voucher_value=None,
        )
        with pytest.raises(ValidationError):
            config.full_clean()

    def test_free_service_with_service_is_valid(self, tenant_fixture, user_fixture):
        service = Service.objects.create(
            tenant=tenant_fixture,
            user=user_fixture,
            name="Corte",
            duration_minutes=30,
            price_eur=50,
        )
        config = BirthdayVoucherConfig(
            tenant=tenant_fixture,
            voucher_type=Voucher.VoucherType.FREE_SERVICE,
            voucher_value=None,
            service=service,
        )
        config.full_clean()  # não deve levantar

    def test_percent_without_value_is_invalid(self, tenant_fixture):
        config = BirthdayVoucherConfig(
            tenant=tenant_fixture,
            voucher_type=Voucher.VoucherType.PERCENT,
            voucher_value=None,
        )
        with pytest.raises(ValidationError):
            config.full_clean()

    def test_deleting_tenant_cascades_config(self, tenant_fixture):
        config = BirthdayVoucherConfig.objects.create(tenant=tenant_fixture)
        config_id = config.pk
        tenant_fixture.delete()
        assert not BirthdayVoucherConfig.objects.filter(pk=config_id).exists()


@pytest.mark.django_db
class TestBirthdayVoucherLogModel:
    def test_create_log_entry(self, tenant_fixture, customer_fixture):
        log = BirthdayVoucherLog.objects.create(
            tenant=tenant_fixture,
            client=customer_fixture,
            sent_date=timezone.localdate(),
        )
        assert log.pk is not None
        assert log.client_voucher is None

    def test_unique_per_tenant_client_date(self, tenant_fixture, customer_fixture):
        today = timezone.localdate()
        BirthdayVoucherLog.objects.create(
            tenant=tenant_fixture, client=customer_fixture, sent_date=today
        )
        with pytest.raises(IntegrityError):
            BirthdayVoucherLog.objects.create(
                tenant=tenant_fixture, client=customer_fixture, sent_date=today
            )

    def test_same_client_different_date_allowed(self, tenant_fixture, customer_fixture):
        today = timezone.localdate()
        yesterday = today - datetime.timedelta(days=1)
        BirthdayVoucherLog.objects.create(
            tenant=tenant_fixture, client=customer_fixture, sent_date=yesterday
        )
        BirthdayVoucherLog.objects.create(
            tenant=tenant_fixture, client=customer_fixture, sent_date=today
        )
        assert (
            BirthdayVoucherLog.objects.filter(client=customer_fixture).count() == 2
        )

    def test_deleting_client_voucher_keeps_log(self, tenant_fixture, customer_fixture):
        voucher = make_voucher(tenant_fixture, code="BIRTHDAY1")
        client_voucher = ClientVoucher.objects.create(
            tenant=tenant_fixture, voucher=voucher, client=customer_fixture
        )
        log = BirthdayVoucherLog.objects.create(
            tenant=tenant_fixture,
            client=customer_fixture,
            sent_date=timezone.localdate(),
            client_voucher=client_voucher,
        )
        client_voucher.delete()
        log.refresh_from_db()
        assert log.client_voucher is None
