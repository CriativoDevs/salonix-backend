import io
import csv
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant, TenantStaffMember


def _auth(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _csv_file(rows):
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow(row)
    data = output.getvalue().encode("utf-8")
    return SimpleUploadedFile("import.csv", data, content_type="text/csv")


@pytest.mark.django_db
def test_import_customers_dry_run_counts():
    tenant = Tenant.objects.create(name="Salon A", slug="salon-a")
    owner = CustomUser.objects.create_user(username="owner", email="o@e.com", password="x", tenant=tenant)
    TenantStaffMember.objects.create(tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER)
    c = _auth(owner)

    file = _csv_file([
        ["name", "email", "phone"],
        ["Ana", "ana@example.com", "+351911000000"],
        ["Bruno", "bruno@example.com", ""],
    ])
    r = c.post("/api/import/customers/?dry_run=true", {"file": file}, format="multipart")
    assert r.status_code == 200
    summary = r.data.get("summary", {})
    assert summary.get("created") == 2
    assert summary.get("processed") == 2


@pytest.mark.django_db
def test_import_services_dry_run_counts():
    tenant = Tenant.objects.create(name="Salon B", slug="salon-b")
    owner = CustomUser.objects.create_user(username="owner2", email="o2@e.com", password="x", tenant=tenant)
    TenantStaffMember.objects.create(tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER)
    c = _auth(owner)

    file = _csv_file([
        ["name", "duration_minutes", "price_eur"],
        ["Corte", "30", "15.00"],
        ["Coloração", "60", "40.00"],
    ])
    r = c.post("/api/import/services/?dry_run=true", {"file": file}, format="multipart")
    assert r.status_code == 200
    summary = r.data.get("summary", {})
    assert summary.get("created") == 2


@pytest.mark.django_db
def test_import_staff_invalid_role_error():
    tenant = Tenant.objects.create(name="Salon C", slug="salon-c")
    owner = CustomUser.objects.create_user(username="owner3", email="o3@e.com", password="x", tenant=tenant)
    TenantStaffMember.objects.create(tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER)
    c = _auth(owner)

    file = _csv_file([
        ["name", "email", "role"],
        ["Maria", "maria@example.com", "invalid"],
    ])
    r = c.post("/api/import/staff/?dry_run=true", {"file": file}, format="multipart")
    assert r.status_code == 200
    summary = r.data.get("summary", {})
    assert summary.get("errors")
    assert summary.get("skipped") == 1


@pytest.mark.django_db
def test_import_requires_owner_permission():
    tenant = Tenant.objects.create(name="Salon D", slug="salon-d")
    collab = CustomUser.objects.create_user(username="c1", email="c1@e.com", password="x", tenant=tenant)
    TenantStaffMember.objects.create(tenant=tenant, user=collab, role=TenantStaffMember.Role.COLLABORATOR)
    c = _auth(collab)

    file = _csv_file([["name", "email", "phone"], ["Ana", "ana@example.com", ""]])
    r = c.post("/api/import/customers/?dry_run=true", {"file": file}, format="multipart")
    assert r.status_code == 403


@pytest.mark.django_db
def test_import_template_download():
    c = APIClient()
    r = c.get("/api/import/templates/customers.csv")
    assert r.status_code == 200
    assert r["Content-Type"].startswith("text/csv")
