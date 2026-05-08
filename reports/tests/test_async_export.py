import os
import uuid
import pytest
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone
from django.test import override_settings
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from users.models import Tenant, UserFeatureFlags
from core.models import Appointment, Professional, SalonCustomer, ScheduleSlot, Service
from reports.models import ExportJob

User = get_user_model()


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_tenant(suffix=None, plan=Tenant.PLAN_PRO):
    s = suffix or uuid.uuid4().hex[:8]
    return Tenant.objects.create(
        slug=f"t-{s}",
        name=f"Tenant {s}",
        plan_tier=plan,
        reports_enabled=True,
    )


def _make_user(tenant, *, is_pro=True):
    u = User.objects.create_user(
        username=f"u-{uuid.uuid4().hex[:8]}",
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        password="x",
        tenant=tenant,
    )
    UserFeatureFlags.objects.update_or_create(
        user=u, defaults={"is_pro": is_pro, "reports_enabled": True}
    )
    return u


def _make_appointment(tenant, user):
    now = timezone.now()
    svc = Service.objects.create(tenant=tenant, user=user, name="Svc", duration_minutes=30, price_eur=Decimal("50"))
    prof = Professional.objects.create(tenant=tenant, user=user, name="Prof")
    cust = SalonCustomer.objects.create(tenant=tenant, name="Cust", email=f"c-{uuid.uuid4().hex[:6]}@t.com")
    slot = ScheduleSlot.objects.create(tenant=tenant, professional=prof, start_time=now, end_time=now + timedelta(minutes=30), is_available=False, status="booked")
    return Appointment.objects.create(tenant=tenant, client=user, customer=cust, service=svc, professional=prof, slot=slot, status="completed")


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


# ── Create job ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_job_returns_202():
    tenant = _make_tenant()
    user = _make_user(tenant)
    with patch("reports.views_export.generate_csv_export.delay"):
        r = _client(user).post("/api/reports/exports/", {"report_type": "basic"}, format="json")
    assert r.status_code == 202
    assert "job_id" in r.data
    assert r.data["status"] == "pending"
    assert ExportJob.objects.filter(id=r.data["job_id"], tenant=tenant).exists()


@pytest.mark.django_db
def test_create_job_invalid_type_returns_400():
    tenant = _make_tenant()
    user = _make_user(tenant)
    with patch("reports.views_export.generate_csv_export.delay"):
        r = _client(user).post("/api/reports/exports/", {"report_type": "invalid"}, format="json")
    assert r.status_code == 400


@pytest.mark.django_db
def test_create_job_pro_only_type_denied_for_basic_tenant():
    tenant = _make_tenant(plan=Tenant.PLAN_BASIC)
    user = _make_user(tenant, is_pro=False)
    with patch("reports.views_export.generate_csv_export.delay"):
        r = _client(user).post("/api/reports/exports/", {"report_type": "advanced"}, format="json")
    assert r.status_code == 403


@pytest.mark.django_db
def test_create_job_dispatches_celery_task():
    tenant = _make_tenant()
    user = _make_user(tenant)
    with patch("reports.views_export.generate_csv_export.delay") as mock_delay:
        r = _client(user).post("/api/reports/exports/", {"report_type": "basic"}, format="json")
    assert r.status_code == 202
    mock_delay.assert_called_once_with(r.data["job_id"])


# ── Status endpoint ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_status_pending_job():
    tenant = _make_tenant()
    user = _make_user(tenant)
    job = ExportJob.objects.create(tenant=tenant, requested_by=user, report_type="basic")
    r = _client(user).get(f"/api/reports/exports/{job.id}/")
    assert r.status_code == 200
    assert r.data["status"] == "pending"
    assert r.data["download_url"] is None


@pytest.mark.django_db
def test_status_done_job_has_download_url(tmp_path):
    tenant = _make_tenant()
    user = _make_user(tenant)
    rel = f"exports/{tenant.slug}/basic_{uuid.uuid4()}.csv"
    abs_path = tmp_path / rel
    abs_path.parent.mkdir(parents=True)
    abs_path.write_text("data")
    job = ExportJob.objects.create(
        tenant=tenant, requested_by=user, report_type="basic",
        status=ExportJob.Status.DONE, file_path=rel,
    )
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        r = _client(user).get(f"/api/reports/exports/{job.id}/")
    assert r.status_code == 200
    assert r.data["download_url"] is not None
    assert str(job.id) in r.data["download_url"]


@pytest.mark.django_db
def test_status_failed_job_has_error_message():
    tenant = _make_tenant()
    user = _make_user(tenant)
    job = ExportJob.objects.create(
        tenant=tenant, requested_by=user, report_type="basic",
        status=ExportJob.Status.FAILED, error_message="boom",
    )
    r = _client(user).get(f"/api/reports/exports/{job.id}/")
    assert r.status_code == 200
    assert r.data["error_message"] == "boom"


# ── Download endpoint ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_download_done_job_returns_csv(tmp_path):
    tenant = _make_tenant()
    user = _make_user(tenant)
    rel = f"exports/{tenant.slug}/basic_{uuid.uuid4()}.csv"
    abs_path = tmp_path / rel
    abs_path.parent.mkdir(parents=True)
    abs_path.write_text("col1,col2\nval1,val2")
    job = ExportJob.objects.create(
        tenant=tenant, requested_by=user, report_type="basic",
        status=ExportJob.Status.DONE, file_path=rel,
    )
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        r = _client(user).get(f"/api/reports/exports/{job.id}/download/")
    assert r.status_code == 200
    assert r["Content-Type"] == "text/csv"


@pytest.mark.django_db
def test_download_expired_job_returns_410(tmp_path):
    tenant = _make_tenant()
    user = _make_user(tenant)
    rel = f"exports/{tenant.slug}/basic_{uuid.uuid4()}.csv"
    abs_path = tmp_path / rel
    abs_path.parent.mkdir(parents=True)
    abs_path.write_text("data")
    job = ExportJob.objects.create(
        tenant=tenant, requested_by=user, report_type="basic",
        status=ExportJob.Status.DONE, file_path=rel,
        expires_at=timezone.now() - timedelta(hours=1),
    )
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        r = _client(user).get(f"/api/reports/exports/{job.id}/download/")
    assert r.status_code == 410


@pytest.mark.django_db
def test_download_pending_job_returns_404():
    tenant = _make_tenant()
    user = _make_user(tenant)
    job = ExportJob.objects.create(tenant=tenant, requested_by=user, report_type="basic")
    r = _client(user).get(f"/api/reports/exports/{job.id}/download/")
    assert r.status_code == 404


# ── Tenant isolation ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_other_tenant_cannot_see_job():
    t1 = _make_tenant()
    t2 = _make_tenant()
    u1 = _make_user(t1)
    u2 = _make_user(t2)
    job = ExportJob.objects.create(tenant=t1, requested_by=u1, report_type="basic")
    r = _client(u2).get(f"/api/reports/exports/{job.id}/")
    assert r.status_code == 404


@pytest.mark.django_db
def test_other_tenant_cannot_download_job(tmp_path):
    t1 = _make_tenant()
    t2 = _make_tenant()
    u1 = _make_user(t1)
    u2 = _make_user(t2)
    rel = f"exports/{t1.slug}/basic_{uuid.uuid4()}.csv"
    abs_path = tmp_path / rel
    abs_path.parent.mkdir(parents=True)
    abs_path.write_text("secret data")
    job = ExportJob.objects.create(
        tenant=t1, requested_by=u1, report_type="basic",
        status=ExportJob.Status.DONE, file_path=rel,
    )
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        r = _client(u2).get(f"/api/reports/exports/{job.id}/download/")
    assert r.status_code == 404


# ── Cleanup task ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_cleanup_deletes_expired_jobs_and_files(tmp_path):
    from reports.tasks import cleanup_expired_export_jobs

    tenant = _make_tenant()
    user = _make_user(tenant)

    rel = f"exports/{tenant.slug}/basic_{uuid.uuid4()}.csv"
    abs_path = tmp_path / rel
    abs_path.parent.mkdir(parents=True)
    abs_path.write_text("data")

    expired_job = ExportJob.objects.create(
        tenant=tenant, requested_by=user, report_type="basic",
        status=ExportJob.Status.DONE, file_path=rel,
        expires_at=timezone.now() - timedelta(hours=1),
    )
    active_job = ExportJob.objects.create(
        tenant=tenant, requested_by=user, report_type="basic",
    )

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        result = cleanup_expired_export_jobs()

    assert result["deleted_jobs"] == 1
    assert result["deleted_files"] == 1
    assert not ExportJob.objects.filter(id=expired_job.id).exists()
    assert ExportJob.objects.filter(id=active_job.id).exists()
    assert not abs_path.exists()


@pytest.mark.django_db
def test_cleanup_handles_missing_file_gracefully(tmp_path):
    from reports.tasks import cleanup_expired_export_jobs

    tenant = _make_tenant()
    user = _make_user(tenant)
    job = ExportJob.objects.create(
        tenant=tenant, requested_by=user, report_type="basic",
        status=ExportJob.Status.DONE, file_path="exports/nonexistent/file.csv",
        expires_at=timezone.now() - timedelta(hours=1),
    )
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        result = cleanup_expired_export_jobs()

    assert result["deleted_jobs"] == 1
    assert result["deleted_files"] == 0
    assert not ExportJob.objects.filter(id=job.id).exists()


# ── Celery task (sync execution) ──────────────────────────────────────────────

@pytest.mark.django_db
def test_generate_csv_export_task_basic(tmp_path):
    from reports.tasks import generate_csv_export

    tenant = _make_tenant()
    user = _make_user(tenant)
    _make_appointment(tenant, user)
    job = ExportJob.objects.create(tenant=tenant, requested_by=user, report_type="basic")

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        generate_csv_export(str(job.id))

    job.refresh_from_db()
    assert job.status == ExportJob.Status.DONE
    assert job.file_path
    abs_path = tmp_path / job.file_path
    assert abs_path.exists()
    assert "TimelyOne" in abs_path.read_text()


@pytest.mark.django_db
def test_generate_csv_export_task_top_services(tmp_path):
    from reports.tasks import generate_csv_export

    tenant = _make_tenant()
    user = _make_user(tenant)
    _make_appointment(tenant, user)
    job = ExportJob.objects.create(tenant=tenant, requested_by=user, report_type="top_services")

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        generate_csv_export(str(job.id))

    job.refresh_from_db()
    assert job.status == ExportJob.Status.DONE
    assert "TOP SERVIÇOS" in (tmp_path / job.file_path).read_text()


@pytest.mark.django_db
def test_generate_csv_export_task_marks_failed_on_error(tmp_path):
    from reports.tasks import generate_csv_export

    tenant = _make_tenant()
    user = _make_user(tenant)
    job = ExportJob.objects.create(
        tenant=tenant, requested_by=user, report_type="basic",
        parameters={"from": "invalid-date"},
    )

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        with pytest.raises(Exception):
            generate_csv_export(str(job.id))

    job.refresh_from_db()
    assert job.status == ExportJob.Status.FAILED
    assert job.error_message
