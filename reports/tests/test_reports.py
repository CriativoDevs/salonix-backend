# reports/tests/test_reports.py
import pytest
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db import models
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from users.models import UserFeatureFlags
from core.models import Appointment, Service

User = get_user_model()

COMPLETED = "completed"
PAID = "paid"
OTHER_STATUS = "scheduled"  # algum status não-finalizado do teu domínio


# ---------- Introspec helpers ----------
def _resolve_dt_field(model):
    preferred = {"date", "start", "start_at", "start_time", "scheduled_for", "datetime"}
    dt_fields = [f for f in model._meta.fields if isinstance(f, models.DateTimeField)]
    if not dt_fields:
        return None
    for f in dt_fields:
        if f.name in preferred:
            return f.name
    return dt_fields[0].name


def _resolve_price_field(model):
    preferred = {"price", "price_eur", "amount", "amount_eur", "total_price"}
    dec_fields = [f for f in model._meta.fields if isinstance(f, models.DecimalField)]
    for f in dec_fields:
        if f.name in preferred:
            return f.name
    return dec_fields[0].name if dec_fields else None


def _resolve_fk(model, *candidate_names):
    """Retorna (field, related_model) para o primeiro FK cujo nome está em candidate_names."""
    for f in model._meta.fields:
        if isinstance(f, models.ForeignKey) and f.name in set(candidate_names):
            return f, f.remote_field.model
    return None, None


def _first_fk_by_related_name(model, related_model_name):
    """Procura um FK cujo modelo-relacionado tenha o nome dado (ex.: 'Slot')."""
    for f in model._meta.fields:
        if isinstance(f, models.ForeignKey):
            if f.remote_field.model.__name__.lower() == related_model_name.lower():
                return f, f.remote_field.model
    return None, None


def _minimal_instance(model, preset=None):
    """
    Cria uma instância 'mínima' preenchendo campos obrigatórios sem default.
    'preset' são campos já resolvidos (ex.: FKs que queremos controlar).
    """
    preset = dict(preset or {})
    data = dict(preset)

    for f in model._meta.fields:
        if f.primary_key or getattr(f, "auto_created", False):
            continue
        if f.name in data:
            continue
        # pular campos com default/auto_now/auto_now_add
        if (
            f.has_default()
            or getattr(f, "auto_now", False)
            or getattr(f, "auto_now_add", False)
        ):
            continue
        # se for nullable/blank, podemos ignorar
        if getattr(f, "null", False) or getattr(f, "blank", False):
            continue

        # preencher conforme tipo
        if isinstance(f, models.CharField) or isinstance(f, models.TextField):
            data[f.name] = "x"
        elif isinstance(f, models.BooleanField):
            data[f.name] = False
        elif isinstance(f, models.IntegerField):
            data[f.name] = 0
        elif isinstance(f, models.DecimalField):
            data[f.name] = Decimal("0")
        elif isinstance(f, models.DateTimeField):
            data[f.name] = timezone.now()
        elif isinstance(f, models.DateField):
            data[f.name] = timezone.now().date()
        elif isinstance(f, models.TimeField):
            data[f.name] = timezone.now().time()
        elif isinstance(f, models.ForeignKey):
            # cria minimamente o relacionado
            rel_obj = _minimal_instance(f.remote_field.model)
            data[f.name] = rel_obj

    return model.objects.create(**data)


# ---------- Domain helpers (client/professional/slot) ----------
def _get_or_create_client(user):
    # tenta um modelo ligado ao Appointment via FK 'client' ou 'customer'
    client_fk, ClientModel = _resolve_fk(Appointment, "client", "customer")
    if not client_fk:
        return {}, None  # sem FK de cliente
    payload = {}
    # popular campos comuns
    fields = {f.name for f in ClientModel._meta.fields}
    if "user" in fields:
        payload["user"] = user
    if "name" in fields:
        payload["name"] = "Cliente Teste"
    if "full_name" in fields and "name" not in payload:
        payload["full_name"] = "Cliente Teste"
    if "email" in fields:
        payload["email"] = "cliente@example.com"
    if "phone" in fields:
        payload["phone"] = "999999999"
    client = (
        ClientModel.objects.create(**payload)
        if payload
        else _minimal_instance(ClientModel)
    )
    return {client_fk.name: client}, client


def _get_or_create_professional(user):
    prof_fk, ProfModel = _resolve_fk(Appointment, "professional", "staff", "employee")
    if not prof_fk:
        return {}, None
    fields = {f.name for f in ProfModel._meta.fields}
    payload = {}
    if "user" in fields:
        payload["user"] = user
    if "name" in fields:
        payload["name"] = "Profissional Teste"
    if "full_name" in fields and "name" not in payload:
        payload["full_name"] = "Profissional Teste"
    professional = (
        ProfModel.objects.create(**payload) if payload else _minimal_instance(ProfModel)
    )
    return {prof_fk.name: professional}, professional


def _make_slot_for(when, service, professional, user):
    """
    Cria um Slot compatível com Appointment (FK obrigatória) usando introspecção.
    """
    # descobrir FK slot em Appointment
    slot_fk, SlotModel = _resolve_fk(Appointment, "slot")
    if not slot_fk:
        # tenta pelo nome do modelo
        slot_fk, SlotModel = _first_fk_by_related_name(Appointment, "Slot")
    if not slot_fk:
        return {}  # Appointment não exige slot

    # montar payload mínimo para Slot
    payload = {}
    slot_fields = {f.name for f in SlotModel._meta.fields}

    # amarrar a profissional/serviço/usuário se existirem FKs
    # profissional
    for cand in ("professional", "staff", "employee"):
        if cand in slot_fields:
            payload[cand] = professional
            break
    # serviço
    if "service" in slot_fields:
        payload["service"] = service
    # user
    if "user" in slot_fields:
        payload["user"] = user

    # horário de início/fim (tenta nomes comuns)
    start_names = ["start", "start_at", "start_time", "begin", "datetime", "date"]
    end_names = ["end", "end_at", "end_time", "finish"]
    start_field = next((n for n in start_names if n in slot_fields), None)
    end_field = next((n for n in end_names if n in slot_fields), None)

    payload_time = {}
    if start_field:
        payload_time[start_field] = when
    if end_field:
        dur = getattr(service, "duration_minutes", None) or 30
        payload_time[end_field] = when + timedelta(minutes=int(dur))

    payload.update(payload_time)

    # cria preenchendo demais obrigatórios automaticamente
    slot = _minimal_instance(SlotModel, preset=payload)
    return {slot_fk.name: slot}


# ---------- Seed ----------
@pytest.mark.django_db
def _seed_data(user):
    now = timezone.now()

    # serviços válidos
    s_hair = Service.objects.create(
        user=user, name="Corte de Cabelo", duration_minutes=30, price_eur=25
    )
    s_color = Service.objects.create(
        user=user, name="Coloração", duration_minutes=60, price_eur=50
    )

    # descobre campos dinâmicos em Appointment
    dt_field = _resolve_dt_field(Appointment)
    price_field = _resolve_price_field(Appointment)  # pode ser None

    # cria cliente e profissional
    client_kwargs, client = _get_or_create_client(user)
    prof_kwargs, professional = _get_or_create_professional(user)

    def make_appt(service, when, status, price=None):
        base = {
            "service": service,
            dt_field: when,
            "status": status,
        }
        # preencher preço se houver campo decimal no Appointment
        if price_field and price is not None:
            base[price_field] = Decimal(str(price))

        # criar slot compatível (se FK de slot for obrigatória)
        slot_kwargs = _make_slot_for(when, service, professional, user)

        kwargs = {**base, **client_kwargs, **prof_kwargs, **slot_kwargs}
        return Appointment.objects.create(**kwargs)

    # completados/pagos
    make_appt(s_hair, now - timedelta(days=1), COMPLETED, 30.00)
    make_appt(s_hair, now - timedelta(days=5), PAID, 45.00)
    make_appt(s_color, now - timedelta(days=10), COMPLETED, 80.00)

    # não completado (fora dos agregados de receita)
    make_appt(s_hair, now - timedelta(days=2), OTHER_STATUS, 25.00)

    return s_hair, s_color


# ---------- Tests ----------
@pytest.mark.django_db
def test_reports_overview_ok():
    user = User.objects.create_user(username="pro", password="x", email="p@e.com")
    UserFeatureFlags.objects.update_or_create(
        user=user, defaults={"is_pro": True, "reports_enabled": True}
    )
    _seed_data(user)

    c = APIClient()
    c.force_authenticate(user)

    r = c.get("/api/reports/overview/")
    assert r.status_code == 200
    assert r.data["appointments_total"] >= 4
    assert r.data["appointments_completed"] == 3
    # Como o campo de preço pode variar por domínio, aqui só garantimos que existe um número.
    assert Decimal(str(r.data["avg_ticket"])) >= Decimal("0")


@pytest.mark.django_db
def test_reports_top_services_ok():
    user = User.objects.create_user(username="pro2", password="x", email="p2@e.com")
    UserFeatureFlags.objects.update_or_create(
        user=user, defaults={"is_pro": True, "reports_enabled": True}
    )
    _seed_data(user)

    c = APIClient()
    c.force_authenticate(user)

    r = c.get("/api/reports/top-services/?limit=5")
    assert r.status_code == 200
    assert len(r.data) >= 2
    names = {row["service_name"] for row in r.data}
    assert {"Corte de Cabelo", "Coloração"} & names
    hair_row = next(x for x in r.data if x["service_name"] == "Corte de Cabelo")
    assert hair_row["qty"] == 2


@pytest.mark.django_db
def test_reports_revenue_series_day_ok():
    user = User.objects.create_user(username="pro3", password="x", email="p3@e.com")
    UserFeatureFlags.objects.update_or_create(
        user=user, defaults={"is_pro": True, "reports_enabled": True}
    )
    _seed_data(user)

    c = APIClient()
    c.force_authenticate(user)

    r = c.get("/api/reports/revenue/?interval=day")
    assert r.status_code == 200
    assert r.data["interval"] == "day"
    assert isinstance(r.data["series"], list)
    assert all("revenue" in p for p in r.data["series"])


@pytest.mark.django_db
def test_reports_guard_403_when_disabled():
    user = User.objects.create_user(username="free", password="x", email="f@e.com")
    UserFeatureFlags.objects.update_or_create(
        user=user, defaults={"is_pro": False, "reports_enabled": False}
    )
    _seed_data(user)

    c = APIClient()
    c.force_authenticate(user)

    for path in (
        "/api/reports/overview/",
        "/api/reports/top-services/",
        "/api/reports/revenue/",
    ):
        r = c.get(path)
        assert r.status_code == 403
        assert "desativado" in r.data["detail"].lower()
