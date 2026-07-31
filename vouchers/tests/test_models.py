import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from users.models import Tenant
from vouchers.models import Voucher


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
