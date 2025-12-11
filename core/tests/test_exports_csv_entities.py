import csv
import io
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from django.urls import reverse
from django.conf import settings

from users.models import CustomUser, Tenant, TenantStaffMember
from core.models import SalonCustomer


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_customers_export_filters_and_header_enforcement(user_fixture):
    owner = user_fixture
    tenant = owner.tenant

    a = SalonCustomer.objects.create(
        tenant=tenant, name="A", email="a@e.com", phone_number="111"
    )
    b = SalonCustomer.objects.create(
        tenant=tenant, name="B", email="b@e.com", phone_number="222", is_active=False
    )

    # Manipular updated_at via update() para testar filtro
    past = timezone.now() - timezone.timedelta(days=2)
    SalonCustomer.objects.filter(id=a.id).update(updated_at=past)

    c = _client(owner)
    # active=true deve excluir B
    url = "/api/export/customers.csv?active=true"
    r = c.get(url)
    assert r.status_code == 200
    content = b"".join(r.streaming_content).decode("utf-8")
    rows = list(csv.reader(io.StringIO(content)))
    assert rows[0] == ["name", "email", "phone"]
    # header + pelo menos 1 linha (A ativo)
    assert len(rows) >= 2
    assert rows[1][0] == "A"

    # updated_since posterior ao 'past' deve retornar apenas B
    since_date = timezone.now().date().isoformat()
    r2 = c.get(f"/api/export/customers.csv?updated_since={since_date}")
    assert r2.status_code == 200
    content2 = b"".join(r2.streaming_content).decode("utf-8")
    rows2 = list(csv.reader(io.StringIO(content2)))
    names = [r[0] for r in rows2[1:]]
    assert "B" in names
    assert "A" not in names

    # Header X-Tenant-Slug diferente deve bloquear (403)
    other = Tenant.objects.create(slug="other-tenant", name="Other")
    r3 = c.get("/api/export/customers.csv", HTTP_X_TENANT_SLUG=other.slug)
    assert r3.status_code == 403


@pytest.mark.django_db
def test_staff_export_active_and_updated_since(user_fixture):
    owner = user_fixture
    tenant = owner.tenant

    u_active = CustomUser.objects.create_user(
        username="active1", email="a1@e.com", password="x"
    )
    u_disabled = CustomUser.objects.create_user(
        username="disabled1", email="d1@e.com", password="x"
    )

    s_active = TenantStaffMember.objects.create(
        tenant=tenant,
        user=u_active,
        role=TenantStaffMember.Role.MANAGER,
        status=TenantStaffMember.Status.ACTIVE,
    )
    s_disabled = TenantStaffMember.objects.create(
        tenant=tenant,
        user=u_disabled,
        role=TenantStaffMember.Role.COLLABORATOR,
        status=TenantStaffMember.Status.DISABLED,
    )

    past = timezone.now() - timezone.timedelta(days=1)
    TenantStaffMember.objects.filter(id=s_active.id).update(updated_at=past)

    c = _client(owner)
    # active=true retorna apenas s_active
    r = c.get("/api/export/staff.csv?active=true")
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(b"".join(r.streaming_content).decode("utf-8"))))
    assert rows[0] == ["name", "email", "role"]
    emails = [r[1] for r in rows[1:]]
    assert "a1@e.com" in emails
    assert "d1@e.com" not in emails

    # updated_since (data de hoje) deve incluir registros do dia
    since = timezone.now().date().isoformat()
    r2 = c.get(f"/api/export/staff.csv?updated_since={since}")
    assert r2.status_code == 200
    rows2 = list(
        csv.reader(io.StringIO(b"".join(r2.streaming_content).decode("utf-8")))
    )
    emails = [r[1] for r in rows2[1:]]
    assert "d1@e.com" in emails


@pytest.mark.django_db
def test_services_export_basic(user_fixture):
    owner = user_fixture
    tenant = owner.tenant
    c = _client(owner)
    # Criar um serviço no tenant
    from core.models import Service

    Service.objects.create(
        tenant=tenant,
        user=owner,
        name="Corte",
        duration_minutes=30,
        price_eur="20.00",
    )
    r = c.get("/api/export/services.csv")
    assert r.status_code == 200
    content = b"".join(r.streaming_content).decode("utf-8")
    rows = list(csv.reader(io.StringIO(content)))
    assert rows[0] == ["name", "duration_minutes", "price_eur"]
    assert rows[1][0] == "Corte"


@pytest.fixture(autouse=True)
def relax_export_throttle(settings):
    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["export_csv"] = "100/min"
    yield
