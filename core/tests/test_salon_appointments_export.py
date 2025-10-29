import csv
import io
import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from django.http import HttpResponse
from typing import cast
from users.models import CustomUser
from core.models import Service, Professional, ScheduleSlot, Appointment


def _auth_client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.mark.django_db
def test_export_csv_basic(user_fixture):
    owner = user_fixture
    client = _auth_client(owner)

    # Dados do salão do owner
    service = Service.objects.create(
        user=owner, name="Corte", duration_minutes=30, price_eur="20.00"
    )
    prof = Professional.objects.create(
        user=owner, name="João", bio="Top", is_active=True
    )
    start = timezone.now() + timedelta(days=1)
    end = start + timedelta(minutes=30)

    slot = ScheduleSlot.objects.create(
        professional=prof,
        start_time=start,
        end_time=end,
        is_available=True,
        status="available",
    )
    # ocupa e cria agendamento
    slot.mark_booked()
    Appointment.objects.create(
        client=owner, service=service, professional=prof, slot=slot, notes="Primeiro"
    )

    resp = client.get("/api/salon/appointments/export/")
    resp = cast(HttpResponse, resp)
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert "attachment; filename=" in resp["Content-Disposition"]

    # Lê CSV em memória
    content = b"".join(resp.streaming_content).decode("utf-8")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    # Encontra a linha do cabeçalho das colunas (após o cabeçalho TimelyOne)
    header_row_index = None
    for i, row in enumerate(rows):
        if row and row[0] == "ID":  # Procura pela coluna traduzida
            header_row_index = i
            break
    
    assert header_row_index is not None, "Cabeçalho das colunas não encontrado"
    
    # cabeçalho + 1 linha de dados
    data_rows = rows[header_row_index:]
    assert len(data_rows) == 2
    header = data_rows[0]
    assert header == [
        "ID",
        "Nome do Cliente",
        "Email do Cliente",
        "Serviço",
        "Profissional",
        "Início",
        "Fim",
        "Status",
        "Observações",
        "Criado em",
    ]
    data_row = data_rows[1]
    # service/prof/note presentes
    assert data_row[3] == "Corte"
    assert data_row[4] == "João"
    assert (
        data_row[7] in ("scheduled", "booked", "scheduled")
        or data_row[7] == "scheduled"
        or data_row[7] == "booked"
    )
    # notes
    assert data_row[8] == "Primeiro"


@pytest.mark.django_db
def test_export_respects_filters_and_isolation(user_fixture):
    owner = user_fixture
    other = CustomUser.objects.create_user(
        username="other", email="other@example.com", password="pass1234"
    )

    # Cria dados do owner
    service = Service.objects.create(
        user=owner, name="Coloração", duration_minutes=45, price_eur="35.00"
    )
    prof = Professional.objects.create(
        user=owner, name="Maria", bio="Colorista", is_active=True
    )

    now = timezone.now()
    # slot A (amanhã)
    start_a = now + timedelta(days=1)
    end_a = start_a + timedelta(minutes=45)
    slot_a = ScheduleSlot.objects.create(
        professional=prof,
        start_time=start_a,
        end_time=end_a,
        is_available=True,
        status="available",
    )
    slot_a.mark_booked()
    appt_a = Appointment.objects.create(
        client=owner,
        service=service,
        professional=prof,
        slot=slot_a,
        notes="A",
        status="scheduled",
    )

    # slot B (daqui 3 dias) + cancelado
    start_b = now + timedelta(days=3)
    end_b = start_b + timedelta(minutes=45)
    slot_b = ScheduleSlot.objects.create(
        professional=prof,
        start_time=start_b,
        end_time=end_b,
        is_available=True,
        status="available",
    )
    slot_b.mark_booked()
    appt_b = Appointment.objects.create(
        client=owner,
        service=service,
        professional=prof,
        slot=slot_b,
        notes="B",
        status="cancelled",
    )

    # Export do owner filtrando por status=scheduled e date_to = amanhã
    c_owner = _auth_client(owner)
    resp = c_owner.get(
        "/api/salon/appointments/export/?status=scheduled&date_to="
        + start_a.date().isoformat()
    )
    resp = cast(HttpResponse, resp)
    assert resp.status_code == 200

    content = b"".join(resp.streaming_content).decode("utf-8")
    rows = list(csv.reader(io.StringIO(content)))
    
    # Encontra a linha do cabeçalho das colunas (após o cabeçalho TimelyOne)
    header_row_index = None
    for i, row in enumerate(rows):
        if row and row[0] == "ID":  # Procura pela coluna traduzida
            header_row_index = i
            break
    
    assert header_row_index is not None, "Cabeçalho das colunas não encontrado"
    
    # cabeçalho + 1 linha de dados (somente appt_a deve entrar)
    data_rows = rows[header_row_index:]
    assert len(data_rows) == 2
    assert data_rows[1][0] == str(appt_a.id)

    # O 'other' não deve ver nada do owner
    c_other = _auth_client(other)
    resp_other = c_other.get("/api/salon/appointments/export/")
    resp_other = cast(HttpResponse, resp_other)
    assert resp_other.status_code == 200
    content_other = b"".join(resp_other.streaming_content).decode("utf-8")
    rows_other = list(csv.reader(io.StringIO(content_other)))
    
    # Encontra a linha do cabeçalho das colunas para o usuário 'other'
    header_row_index_other = None
    for i, row in enumerate(rows_other):
        if row and row[0] == "ID":
            header_row_index_other = i
            break
    
    assert header_row_index_other is not None, "Cabeçalho das colunas não encontrado para 'other'"
    
    # Deve ter apenas o cabeçalho, sem dados
    data_rows_other = rows_other[header_row_index_other:]
    assert len(data_rows_other) == 1  # apenas header, sem dados
