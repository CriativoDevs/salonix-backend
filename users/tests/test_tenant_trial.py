"""
BE-PLANS-02: helper Tenant.is_in_trial().

A subscrição do owner é a fonte da verdade do período de teste. O estado vem do
Stripe e é guardado em UserFeatureFlags.pro_status (== "trialing" durante o trial).
"""

import pytest

from users.models import UserFeatureFlags


@pytest.mark.django_db
def test_is_in_trial_true_when_owner_trialing(tenant_fixture, user_fixture):
    ff = user_fixture.featureflags
    ff.pro_status = UserFeatureFlags.STATUS_TRIALING
    ff.save(update_fields=["pro_status"])

    assert tenant_fixture.is_in_trial() is True


@pytest.mark.django_db
def test_is_in_trial_false_when_owner_active(tenant_fixture, user_fixture):
    ff = user_fixture.featureflags
    ff.pro_status = UserFeatureFlags.STATUS_ACTIVE
    ff.save(update_fields=["pro_status"])

    assert tenant_fixture.is_in_trial() is False


@pytest.mark.django_db
def test_is_in_trial_false_without_featureflags(tenant_fixture, user_fixture):
    UserFeatureFlags.objects.filter(user=user_fixture).delete()

    assert tenant_fixture.is_in_trial() is False
