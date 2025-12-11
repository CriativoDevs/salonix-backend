import io
import csv
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant, TenantStaffMember
from core.models import Service, Professional, SalonCustomer, ScheduleSlot, Appointment


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
    return SimpleUploadedFile("appointments.csv", data, content_type="text/csv")


@pytest.mark.django_db
def test_import_appointments_dry_run_created():
    tenant = Tenant.objects.create(name="Salon A", slug="salon-a")
    owner = CustomUser.objects.create_user(
        username="owner",
        email="o@e.com",
        password="x",
        tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    customer = SalonCustomer.objects.create(
        tenant=tenant, name="Ana", email="ana@example.com"
    )
    service = Service.objects.create(
        tenant=tenant, user=owner, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    professional = Professional.objects.create(
        tenant=tenant, user=owner, name="João", is_active=True
    )
    start = timezone.now().replace(microsecond=0) + timezone.timedelta(days=1)
    end = start + timezone.timedelta(minutes=30)
    ScheduleSlot.objects.create(
        tenant=tenant,
        professional=professional,
        start_time=start,
        end_time=end,
        is_available=True,
        status="available",
    )

    c = _auth(owner)
    file = _csv_file(
        [
            [
                "customer_email",
                "customer_phone",
                "service_name",
                "professional_name",
                "start_datetime",
                "duration_minutes",
                "notes",
            ],
            [
                "ana@example.com",
                "",
                "Corte",
                "João",
                start.isoformat(),
                "30",
                "",
            ],
        ]
    )
    r = c.post(
        "/api/import/appointments/?dry_run=true", {"file": file}, format="multipart"
    )
    assert r.status_code == 200
    summary = r.data.get("summary", {})
    assert summary.get("created") == 1
    assert summary.get("processed") == 1


@pytest.mark.django_db
def test_import_appointments_invalid_date_error():
    tenant = Tenant.objects.create(name="Salon B", slug="salon-b")
    owner = CustomUser.objects.create_user(
        username="owner2", email="o2@e.com", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    SalonCustomer.objects.create(tenant=tenant, name="Ana", email="ana@example.com")
    Service.objects.create(
        tenant=tenant, user=owner, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    Professional.objects.create(tenant=tenant, user=owner, name="João", is_active=True)

    c = _auth(owner)
    file = _csv_file(
        [
            [
                "customer_email",
                "customer_phone",
                "service_name",
                "professional_name",
                "start_datetime",
                "duration_minutes",
                "notes",
            ],
            ["ana@example.com", "", "Corte", "João", "invalid", "30", ""],
        ]
    )
    r = c.post(
        "/api/import/appointments/?dry_run=true", {"file": file}, format="multipart"
    )
    assert r.status_code == 200
    summary = r.data.get("summary", {})
    assert summary.get("errors")
    assert summary.get("skipped") == 1


@pytest.mark.django_db
def test_import_appointments_slot_unavailable():
    tenant = Tenant.objects.create(name="Salon C", slug="salon-c")
    owner = CustomUser.objects.create_user(
        username="owner3", email="o3@e.com", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    SalonCustomer.objects.create(tenant=tenant, name="Ana", email="ana@example.com")
    service = Service.objects.create(
        tenant=tenant, user=owner, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    professional = Professional.objects.create(
        tenant=tenant, user=owner, name="João", is_active=True
    )
    start = timezone.now().replace(microsecond=0) + timezone.timedelta(days=1)
    end = start + timezone.timedelta(minutes=30)
    ScheduleSlot.objects.create(
        tenant=tenant,
        professional=professional,
        start_time=start,
        end_time=end,
        is_available=False,
        status="booked",
    )

    c = _auth(owner)
    file = _csv_file(
        [
            [
                "customer_email",
                "customer_phone",
                "service_name",
                "professional_name",
                "start_datetime",
                "duration_minutes",
                "notes",
            ],
            ["ana@example.com", "", "Corte", "João", start.isoformat(), "30", ""],
        ]
    )
    r = c.post(
        "/api/import/appointments/?dry_run=true", {"file": file}, format="multipart"
    )
    assert r.status_code == 200
    summary = r.data.get("summary", {})
    assert summary.get("errors")
    assert summary.get("skipped") == 1


@pytest.mark.django_db
def test_import_appointments_real_and_dedupe():
    tenant = Tenant.objects.create(name="Salon D", slug="salon-d")
    owner = CustomUser.objects.create_user(
        username="owner4", email="o4@e.com", password="x", tenant=tenant
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=owner, role=TenantStaffMember.Role.OWNER
    )
    customer = SalonCustomer.objects.create(
        tenant=tenant, name="Ana", email="ana@example.com"
    )
    service = Service.objects.create(
        tenant=tenant, user=owner, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    professional = Professional.objects.create(
        tenant=tenant, user=owner, name="João", is_active=True
    )
    start = timezone.now().replace(microsecond=0) + timezone.timedelta(days=1)
    end = start + timezone.timedelta(minutes=30)
    ScheduleSlot.objects.create(
        tenant=tenant,
        professional=professional,
        start_time=start,
        end_time=end,
        is_available=True,
        status="available",
    )

    c = _auth(owner)
    file = _csv_file(
        [
            [
                "customer_email",
                "customer_phone",
                "service_name",
                "professional_name",
                "start_datetime",
                "duration_minutes",
                "notes",
            ],
            ["ana@example.com", "", "Corte", "João", start.isoformat(), "30", ""],
        ]
    )

    r1 = c.post(
        "/api/import/appointments/?dry_run=false", {"file": file}, format="multipart"
    )
    assert r1.status_code == 200
    summary1 = r1.data.get("summary", {})
    assert summary1.get("created") == 1
    assert Appointment.objects.filter(tenant=tenant).count() == 1

    file2 = _csv_file(
        [
            [
                "customer_email",
                "customer_phone",
                "service_name",
                "professional_name",
                "start_datetime",
                "duration_minutes",
                "notes",
            ],
            ["ana@example.com", "", "Corte", "João", start.isoformat(), "30", ""],
        ]
    )
    r2 = c.post(
        "/api/import/appointments/?dry_run=false", {"file": file2}, format="multipart"
    )
    assert r2.status_code == 200
    summary2 = r2.data.get("summary", {})
    assert summary2.get("skipped") == 1


@pytest.mark.django_db
def test_import_appointments_template_download():
    c = APIClient()
    r = c.get("/api/import/templates/appointments.csv")
    assert r.status_code == 200
    assert r["Content-Type"].startswith("text/csv")
