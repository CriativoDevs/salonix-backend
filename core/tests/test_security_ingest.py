"""
Security tests for BE-SEC-INGEST-01.

Covers:
- Sanitization of malicious payloads in free-text import fields (notes)
- CSV upload size and row limits
- MIME / encoding validation
- PublicSlotListView filter input validation
"""
import io
import csv
import uuid
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant, TenantStaffMember
from core.models import (
    Appointment, Professional, SalonCustomer, ScheduleSlot, Service,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _slug():
    return uuid.uuid4().hex[:10]


def _make_tenant():
    return Tenant.objects.create(name=f"T-{_slug()}", slug=f"t-{_slug()}")


def _make_owner(tenant):
    user = CustomUser.objects.create_user(
        username=f"u-{_slug()}", email=f"u-{_slug()}@x.com",
        password="x", tenant=tenant,
    )
    TenantStaffMember.objects.create(
        tenant=tenant, user=user, role=TenantStaffMember.Role.OWNER,
    )
    return user


def _auth(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _csv_bytes(rows, encoding="utf-8"):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode(encoding)


def _upload(data, name="import.csv", content_type="text/csv"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def _make_appointment_fixture(tenant, user):
    """Creates a minimal appointment fixture for import tests."""
    start = timezone.make_aware(timezone.datetime(2030, 1, 10, 10, 0))
    svc = Service.objects.create(
        tenant=tenant, user=user, name="Svc", duration_minutes=30, price_eur=10,
    )
    prof = Professional.objects.create(tenant=tenant, user=user, name="Prof")
    cust = SalonCustomer.objects.create(
        tenant=tenant, name="Cust", email=f"c-{_slug()}@x.com",
    )
    slot = ScheduleSlot.objects.create(
        tenant=tenant, professional=prof,
        start_time=start, end_time=start + timezone.timedelta(minutes=30),
        is_available=True, status="available",
    )
    return svc, prof, cust, slot


# ── 1. Sanitization: malicious notes field ────────────────────────────────────


@pytest.mark.django_db
def test_import_appointments_notes_sqli_payload_sanitized():
    """SQL injection strings in notes must be stored sanitized (control chars stripped)."""
    tenant = _make_tenant()
    user = _make_owner(tenant)
    svc, prof, cust, slot = _make_appointment_fixture(tenant, user)
    start_str = "2030-01-10 10:00"

    sqli_notes = "'; DROP TABLE appointments; --\x00\x1f"
    rows = [
        ["customer_email", "service_name", "professional_name", "start_datetime", "notes"],
        [cust.email, svc.name, prof.name, start_str, sqli_notes],
    ]
    f = _upload(_csv_bytes(rows))
    r = _auth(user).post("/api/import/appointments/", {"file": f}, format="multipart")
    assert r.status_code == 200

    appt = Appointment.objects.filter(tenant=tenant).order_by("-id").first()
    assert appt is not None
    # Control chars \x00 and \x1f must be stripped
    assert "\x00" not in appt.notes
    assert "\x1f" not in appt.notes
    # The rest of the payload is stored as text (no execution risk via ORM)
    assert "DROP TABLE" in appt.notes


@pytest.mark.django_db
def test_import_appointments_notes_control_chars_removed():
    """Control characters in notes are removed by sanitize_text_input."""
    tenant = _make_tenant()
    user = _make_owner(tenant)
    svc, prof, cust, slot = _make_appointment_fixture(tenant, user)

    notes_with_ctrl = "normal text\x01\x08\x1b\x7fmore text"
    rows = [
        ["customer_email", "service_name", "professional_name", "start_datetime", "notes"],
        [cust.email, svc.name, prof.name, "2030-01-10 10:00", notes_with_ctrl],
    ]
    f = _upload(_csv_bytes(rows))
    r = _auth(user).post("/api/import/appointments/", {"file": f}, format="multipart")
    assert r.status_code == 200

    appt = Appointment.objects.filter(tenant=tenant).order_by("-id").first()
    for bad_char in ["\x01", "\x08", "\x1b", "\x7f"]:
        assert bad_char not in appt.notes


@pytest.mark.django_db
def test_import_appointments_notes_oversized_truncated():
    """Notes longer than 1000 chars are truncated."""
    tenant = _make_tenant()
    user = _make_owner(tenant)
    svc, prof, cust, slot = _make_appointment_fixture(tenant, user)

    long_notes = "A" * 2000
    rows = [
        ["customer_email", "service_name", "professional_name", "start_datetime", "notes"],
        [cust.email, svc.name, prof.name, "2030-01-10 10:00", long_notes],
    ]
    f = _upload(_csv_bytes(rows))
    r = _auth(user).post("/api/import/appointments/", {"file": f}, format="multipart")
    assert r.status_code == 200

    appt = Appointment.objects.filter(tenant=tenant).order_by("-id").first()
    assert len(appt.notes) <= 1000


# ── 2. Upload size limits ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_import_csv_rejects_oversized_file():
    """Files exceeding 5 MB are rejected with 400."""
    tenant = _make_tenant()
    user = _make_owner(tenant)

    header = "name,email,phone\n"
    # Each data row ~50 bytes; 5 MB / 50 ≈ 100k rows → just exceed the byte limit
    big_data = (header + ("A" * 49 + "\n") * 110_000).encode("utf-8")
    assert len(big_data) > 5 * 1024 * 1024

    f = _upload(big_data)
    r = _auth(user).post("/api/import/customers/", {"file": f}, format="multipart")
    assert r.status_code == 400
    assert "MB" in str(r.data)


@pytest.mark.django_db
def test_import_csv_rejects_too_many_rows():
    """CSVs with more than 5000 data rows are rejected with 400."""
    tenant = _make_tenant()
    user = _make_owner(tenant)

    rows = [["name", "email", "phone"]] + [
        [f"Name{i}", f"u{i}@x.com", ""] for i in range(5001)
    ]
    f = _upload(_csv_bytes(rows))
    r = _auth(user).post("/api/import/customers/", {"file": f}, format="multipart")
    assert r.status_code == 400
    assert "5000" in str(r.data) or "linhas" in str(r.data).lower()


@pytest.mark.django_db
def test_import_csv_accepts_exactly_max_rows():
    """CSVs with exactly 5000 data rows are accepted."""
    tenant = _make_tenant()
    user = _make_owner(tenant)

    rows = [["name", "email", "phone"]] + [
        [f"Name{i}", f"u{i}@x.com", ""] for i in range(5000)
    ]
    f = _upload(_csv_bytes(rows))
    r = _auth(user).post("/api/import/customers/?dry_run=true", {"file": f}, format="multipart")
    assert r.status_code == 200


# ── 3. MIME / encoding validation ─────────────────────────────────────────────


@pytest.mark.django_db
def test_import_csv_rejects_disallowed_mime_type():
    """Files with a disallowed MIME type (e.g. application/pdf) are rejected."""
    tenant = _make_tenant()
    user = _make_owner(tenant)

    data = _csv_bytes([["name", "email", "phone"], ["Ana", "a@x.com", ""]])
    f = SimpleUploadedFile("import.csv", data, content_type="application/pdf")
    r = _auth(user).post("/api/import/customers/", {"file": f}, format="multipart")
    assert r.status_code == 400
    assert "permitido" in str(r.data).lower() or "tipo" in str(r.data).lower()


@pytest.mark.django_db
def test_import_csv_rejects_wrong_extension():
    """Files with a disallowed extension (e.g. .exe) are rejected."""
    tenant = _make_tenant()
    user = _make_owner(tenant)

    data = _csv_bytes([["name", "email", "phone"], ["Ana", "a@x.com", ""]])
    f = SimpleUploadedFile("malware.exe", data, content_type="text/csv")
    r = _auth(user).post("/api/import/customers/", {"file": f}, format="multipart")
    assert r.status_code == 400
    assert "csv" in str(r.data).lower()


@pytest.mark.django_db
def test_import_csv_rejects_binary_magic_bytes():
    """Files starting with ZIP magic bytes are rejected even if named .csv."""
    tenant = _make_tenant()
    user = _make_owner(tenant)

    zip_magic = b"\x50\x4b\x03\x04" + b"\x00" * 100
    f = SimpleUploadedFile("import.csv", zip_magic, content_type="text/csv")
    r = _auth(user).post("/api/import/customers/", {"file": f}, format="multipart")
    assert r.status_code == 400
    assert "formato" in str(r.data).lower() or "inválido" in str(r.data).lower()


@pytest.mark.django_db
def test_import_csv_rejects_non_utf8_encoding():
    """Files encoded in latin-1 (non-UTF-8) are rejected."""
    tenant = _make_tenant()
    user = _make_owner(tenant)

    data = "name,email\nJoão,j@x.com\n".encode("latin-1")
    f = SimpleUploadedFile("import.csv", data, content_type="text/csv")
    r = _auth(user).post("/api/import/customers/", {"file": f}, format="multipart")
    assert r.status_code == 400
    assert "utf" in str(r.data).lower() or "encoding" in str(r.data).lower() or "utf-8" in str(r.data).lower()


@pytest.mark.django_db
def test_import_csv_accepts_utf8_bom():
    """Files with UTF-8 BOM (Excel export) are accepted."""
    tenant = _make_tenant()
    user = _make_owner(tenant)

    bom = b"\xef\xbb\xbf"
    data = bom + "name,email,phone\nAna,a@x.com,\n".encode("utf-8")
    f = SimpleUploadedFile("import.csv", data, content_type="text/csv")
    r = _auth(user).post("/api/import/customers/?dry_run=true", {"file": f}, format="multipart")
    assert r.status_code == 200


# ── 4. PublicSlotListView filter validation ───────────────────────────────────


@pytest.mark.django_db
def test_public_slots_rejects_non_integer_professional_id():
    """professional_id must be a digit; non-integer values return 400."""
    r = APIClient().get("/api/public/slots/", {"professional_id": "'; DROP TABLE--"})
    assert r.status_code == 400


@pytest.mark.django_db
def test_public_slots_rejects_invalid_date_from():
    """date_from with an invalid format returns 400."""
    r = APIClient().get("/api/public/slots/", {"professional_id": "1", "date_from": "not-a-date"})
    assert r.status_code == 400


@pytest.mark.django_db
def test_public_slots_rejects_invalid_date_to():
    """date_to with an invalid format returns 400."""
    r = APIClient().get("/api/public/slots/", {"professional_id": "1", "date_to": "<script>alert(1)</script>"})
    assert r.status_code == 400


# ── 5. Rejection logs and metrics ─────────────────────────────────────────────


@pytest.mark.django_db
def test_rejection_emits_structured_log_on_invalid_mime():
    """A rejected upload calls _import_logger.warning with reason and no sensitive data."""
    from unittest.mock import patch
    tenant = _make_tenant()
    user = _make_owner(tenant)

    data = _csv_bytes([["name", "email"], ["Ana", "a@x.com"]])
    f = SimpleUploadedFile("import.csv", data, content_type="application/pdf")

    with patch("core.views._import_logger") as mock_logger:
        r = _auth(user).post("/api/import/customers/", {"file": f}, format="multipart")

    assert r.status_code == 400
    mock_logger.warning.assert_called_once()
    call_args = mock_logger.warning.call_args
    assert call_args[0][0] == "csv_import_rejected"
    extra = call_args[1]["extra"]
    assert extra["reason"] == "invalid_mime_type"
    # Must not leak file content or user PII
    assert "Ana" not in str(extra)
    assert "a@x.com" not in str(extra)


@pytest.mark.django_db
def test_rejection_emits_structured_log_on_binary_content():
    """Binary file rejection emits log with magic_prefix hex, not raw bytes."""
    from unittest.mock import patch
    tenant = _make_tenant()
    user = _make_owner(tenant)

    zip_magic = b"\x50\x4b\x03\x04" + b"\x00" * 50
    f = SimpleUploadedFile("import.csv", zip_magic, content_type="text/csv")

    with patch("core.views._import_logger") as mock_logger:
        r = _auth(user).post("/api/import/customers/", {"file": f}, format="multipart")

    assert r.status_code == 400
    mock_logger.warning.assert_called_once()
    extra = mock_logger.warning.call_args[1]["extra"]
    assert extra["reason"] == "binary_content"
    assert extra["magic_prefix"] == "504b0304"


@pytest.mark.django_db
def test_rejection_emits_structured_log_on_too_many_rows():
    """Row-limit rejection emits log with row_count, not row content."""
    from unittest.mock import patch
    tenant = _make_tenant()
    user = _make_owner(tenant)

    rows = [["name", "email", "phone"]] + [
        [f"Name{i}", f"u{i}@x.com", ""] for i in range(5001)
    ]
    f = _upload(_csv_bytes(rows))

    with patch("core.views._import_logger") as mock_logger:
        r = _auth(user).post("/api/import/customers/", {"file": f}, format="multipart")

    assert r.status_code == 400
    mock_logger.warning.assert_called_once()
    extra = mock_logger.warning.call_args[1]["extra"]
    assert extra["reason"] == "too_many_rows"
    assert extra["row_count"] == 5001


@pytest.mark.django_db
def test_rejection_prometheus_counter_increments():
    """Each rejection increments the CSV_IMPORT_REJECTIONS_TOTAL counter."""
    from unittest.mock import patch, MagicMock
    tenant = _make_tenant()
    user = _make_owner(tenant)

    mock_counter = MagicMock()
    with patch("core.views.CSV_IMPORT_REJECTIONS_TOTAL", mock_counter):
        data = _csv_bytes([["name"], ["Ana"]])
        f = SimpleUploadedFile("bad.exe", data, content_type="text/csv")
        _auth(user).post("/api/import/customers/", {"file": f}, format="multipart")

    mock_counter.labels.assert_called_once_with(reason="invalid_extension")
    mock_counter.labels.return_value.inc.assert_called_once()
