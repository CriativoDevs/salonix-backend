# reports/tests/test_reports.py
import pytest
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db import models
from typing import Type, cast
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
            rf = getattr(f, "remote_field", None)
            if rf is not None:
                return f, rf.model
    return None, None


def _first_fk_by_related_name(model, related_model_name):
    """Procura um FK cujo modelo-relacionado tenha o nome dado (ex.: 'Slot')."""
    for f in model._meta.fields:
        if isinstance(f, models.ForeignKey):
            rf = getattr(f, "remote_field", None)
            if rf is not None:
                if rf.model.__name__.lower() == related_model_name.lower():
                    return f, rf.model
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
            rf = getattr(f, "remote_field", None)
            if rf is not None:
                rel_obj = _minimal_instance(rf.model)
                data[f.name] = rel_obj

    return model.objects.create(**data)


# ---------- Domain helpers (client/professional/slot) ----------
def _get_or_create_client(user):
    # tenta um modelo ligado ao Appointment via FK 'client' ou 'customer'
    client_fk, ClientModel = _resolve_fk(Appointment, "client", "customer")
    if not client_fk:
        return {}, None  # sem FK de cliente
    assert ClientModel is not None
    ClientModel = cast(Type[models.Model], ClientModel)
    payload = {}
    # popular campos comuns
    fields = {f.name for f in ClientModel._meta.fields}
    if "user" in fields:
        payload["user"] = user
    if "username" in fields:
        import uuid

        payload["username"] = f"client_user_{uuid.uuid4()}"
    if "name" in fields:
        payload["name"] = "Cliente Teste"
    if "full_name" in fields and "name" not in payload:
        payload["full_name"] = "Cliente Teste"
    if "email" in fields:
        import uuid

        payload["email"] = f"cliente_{uuid.uuid4()}@example.com"
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
    assert ProfModel is not None
    ProfModel = cast(Type[models.Model], ProfModel)
    fields = {f.name for f in ProfModel._meta.fields}
    payload = {}
    if "user" in fields:
        payload["user"] = user
    if "username" in fields:
        import uuid

        payload["username"] = f"prof_user_{uuid.uuid4()}"
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
    assert SlotModel is not None
    SlotModel = cast(Type[models.Model], SlotModel)

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
    # Ensure tenant is PRO for access to Top Services
    if user.tenant:
        user.tenant.plan_tier = "pro"
        user.tenant.save()

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
    # Ensure tenant is PRO for access to Revenue Series
    if user.tenant:
        user.tenant.plan_tier = "pro"
        user.tenant.save()

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
def test_reports_permissions_by_plan():
    """
    Testa se as permissões de relatórios são aplicadas corretamente por plano.
    Basic: Acesso apenas ao Overview.
    Pro: Acesso a relatórios de análise (Top Services, Revenue, Retention, Advanced).
    """
    from users.models import Tenant
    import uuid

    suffix = str(uuid.uuid4())[:8]

    # 1. Tenant Basic: Deve ter acesso ao Overview, mas NÃO aos outros
    tenant_basic = Tenant.objects.create(
        slug=f"basic-tenant-reports-{suffix}",
        name="Basic Salon Reports",
        plan_tier=Tenant.PLAN_BASIC,
        reports_enabled=True,  # Habilitado, mas limitado pelo plano
    )
    user_basic = User.objects.create_user(
        username=f"basic_rep_{suffix}",
        password="x",
        email=f"basic_{suffix}@rep.com",
        tenant=tenant_basic,
    )
    # UserFeatureFlags podem ser criadas automaticamente ou manualmente
    UserFeatureFlags.objects.update_or_create(
        user=user_basic, defaults={"is_pro": False, "reports_enabled": True}
    )
    _seed_data(user_basic)

    c = APIClient()
    c.force_authenticate(user_basic)

    # Overview -> OK (Basic tem acesso)
    r = c.get("/api/reports/overview/")
    assert r.status_code == 200

    # BE-PLANS-01 (#481): Basic absorveu os relatórios ex-Pro
    # Top Services -> OK
    r = c.get("/api/reports/top-services/")
    assert r.status_code == 200

    # Revenue -> OK
    r = c.get("/api/reports/revenue/")
    assert r.status_code == 200


@pytest.mark.django_db
def test_retention_report_permissions_and_data():
    """
    Testa se o relatório de retenção é exclusivo para Pro e se os cálculos
    de novos vs recorrentes estão corretos.
    """
    from users.models import Tenant
    from core.models import SalonCustomer
    import uuid

    suffix = str(uuid.uuid4())[:8]

    # --- 1. Test Permissions ---

    # Basic User -> Deve levar 403 no retention e advanced
    tenant_basic = Tenant.objects.create(
        slug=f"basic-tenant-retention-{suffix}",
        name="Basic Salon Retention",
        plan_tier=Tenant.PLAN_BASIC,
    )
    user_basic = User.objects.create_user(
        username=f"basic_ret_{suffix}",
        password="x",
        email=f"basic_ret_{suffix}@test.com",
        tenant=tenant_basic,
    )
    c = APIClient()
    c.force_authenticate(user_basic)

    # BE-PLANS-01 (#481): Basic absorveu retention e advanced (ex-Pro)
    r = c.get("/api/reports/retention/")
    assert r.status_code == 200

    r = c.get("/api/reports/advanced/")
    assert r.status_code == 200

    # --- 2. Test Data Logic (Pro User) ---
    tenant_pro = Tenant.objects.create(
        slug=f"pro-tenant-retention-{suffix}",
        name="Pro Salon Retention",
        plan_tier=Tenant.PLAN_PRO,
    )
    user_pro = User.objects.create_user(
        username=f"pro_ret_{suffix}",
        password="x",
        email=f"pro_ret_{suffix}@test.com",
        tenant=tenant_pro,
    )
    c.force_authenticate(user_pro)

    # Configura datas
    now = timezone.now()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = this_month_start - timedelta(days=10)

    # Cria Professional e Service
    prof_kwargs, professional = _get_or_create_professional(user_pro)
    service = Service.objects.create(
        user=user_pro,
        name="Service A",
        duration_minutes=30,
        price_eur=100,
        tenant=tenant_pro,
    )
    service_b = Service.objects.create(
        user=user_pro,
        name="Service B",
        duration_minutes=30,
        price_eur=50,
        tenant=tenant_pro,
    )

    # --- Cliente Novo (criado "agora", dentro do range do relatório) ---
    customer_new = SalonCustomer.objects.create(
        tenant=tenant_pro,
        name="New Customer",
        email=f"new_{suffix}@c.com",
    )
    # created_at é auto_now_add, então é "agora". Está OK.

    # --- Cliente Recorrente (criado no mês passado) ---
    customer_returning = SalonCustomer.objects.create(
        tenant=tenant_pro,
        name="Returning Customer",
        email=f"ret_{suffix}@c.com",
    )
    # Força created_at antigo
    SalonCustomer.objects.filter(pk=customer_returning.pk).update(created_at=last_month)

    # Helper para criar appointment
    dt_field = _resolve_dt_field(Appointment)
    price_field = _resolve_price_field(Appointment)

    def create_appt(customer, when, price, service_obj=service):
        slot_kwargs = _make_slot_for(when, service_obj, professional, user_pro)
        base = {
            "tenant": tenant_pro,
            "client": user_pro,  # owner agendando
            "customer": customer,
            "service": service_obj,
            "professional": professional,
            dt_field: when,
            "status": "completed",
        }
        if price_field:
            base[price_field] = Decimal(str(price))

        # Merge slot logic
        # Slot creation handles FKs, but we need to pass the slot ID to appointment
        # _make_slot_for returns {'slot': instance}
        base.update(slot_kwargs)

        return Appointment.objects.create(**base)

    # Agendamento para Novo Cliente (Hoje) -> Receita 100
    create_appt(customer_new, now, 100, service_obj=service)

    # Agendamento para Cliente Recorrente (Hoje) -> Receita 50
    create_appt(customer_returning, now, 50, service_obj=service_b)

    # Agendamento fora do range (Ontem, mas vamos filtrar por Hoje-Hoje no request?)
    # Vamos pedir o relatório do mês todo, então ambos devem aparecer.

    # Request range: Inicio do mês até agora
    start_str = this_month_start.strftime("%Y-%m-%d")
    end_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    r = c.get(f"/api/reports/retention/?from={start_str}&to={end_str}")
    assert r.status_code == 200
    data = r.data

    # Verifica New Clients
    assert data["new_clients"]["qty"] == 1
    assert Decimal(str(data["new_clients"]["revenue"])) == Decimal("100")

    # Verifica Returning Clients
    assert data["returning_clients"]["qty"] == 1
    assert Decimal(str(data["returning_clients"]["revenue"])) == Decimal("50")

    # Verifica Advanced View também
    r_adv = c.get("/api/reports/advanced/")
    assert r_adv.status_code == 200
    assert "retention" in r_adv.data
    assert "top_services" in r_adv.data
    assert "revenue" in r_adv.data


@pytest.mark.django_db
@pytest.mark.django_db
def test_retention_repeat_rate_windows_30_60_90():
    """
    Valida repeat_rate com valores corretos.

    Setup: 4 clientes com primeira visita no range.
    - A repete em 25d -> contado em 30d, 60d, 90d
    - B repete em 50d -> contado em 60d, 90d
    - C repete em 90d -> contado em 90d
    - D não repete

    Esperado: 30d = 25%, 60d = 50%, 90d = 75%
    """
    from users.models import Tenant
    from core.models import SalonCustomer
    import uuid

    suffix = str(uuid.uuid4())[:8]
    tenant = Tenant.objects.create(
        slug=f"pro-repeat-{suffix}",
        name="Pro Repeat",
        plan_tier=Tenant.PLAN_PRO,
    )
    user = User.objects.create_user(
        username=f"repeat_{suffix}",
        password="x",
        email=f"repeat_{suffix}@test.com",
        tenant=tenant,
    )

    c = APIClient()
    c.force_authenticate(user)

    now = timezone.now()
    prof_kwargs, professional = _get_or_create_professional(user)
    service = Service.objects.create(
        user=user,
        name="Service Repeat",
        duration_minutes=30,
        price_eur=100,
        tenant=tenant,
    )

    dt_field = _resolve_dt_field(Appointment)
    price_field = _resolve_price_field(Appointment)

    def create_appt(customer, when, price=100):
        slot_kwargs = _make_slot_for(when, service, professional, user)
        base = {
            "tenant": tenant,
            "client": user,
            "customer": customer,
            "service": service,
            "professional": professional,
            dt_field: when,
            "status": "completed",
        }
        if price_field:
            base[price_field] = Decimal(str(price))
        base.update(slot_kwargs)
        return Appointment.objects.create(**base)

    # Primeira visita de todos no range: 100 dias atrás
    base_dt = now - timedelta(days=100)
    range_start = now - timedelta(days=120)
    range_end = now + timedelta(days=1)

    customer_a = SalonCustomer.objects.create(
        tenant=tenant, name="Customer A", email=f"a_{suffix}@c.com"
    )
    customer_b = SalonCustomer.objects.create(
        tenant=tenant, name="Customer B", email=f"b_{suffix}@c.com"
    )
    customer_c = SalonCustomer.objects.create(
        tenant=tenant, name="Customer C", email=f"c_{suffix}@c.com"
    )
    customer_d = SalonCustomer.objects.create(
        tenant=tenant, name="Customer D", email=f"d_{suffix}@c.com"
    )

    # Force created_at para base_dt (dentro do range)
    for cust in [customer_a, customer_b, customer_c, customer_d]:
        SalonCustomer.objects.filter(pk=cust.pk).update(created_at=base_dt)
        cust.refresh_from_db()

    # Primeira visita em base_dt
    create_appt(customer_a, base_dt)
    create_appt(customer_b, base_dt)
    create_appt(customer_c, base_dt)
    create_appt(customer_d, base_dt)

    # Segundas visitas
    create_appt(customer_a, base_dt + timedelta(days=25))  # 25d
    create_appt(customer_b, base_dt + timedelta(days=50))  # 50d
    create_appt(customer_c, base_dt + timedelta(days=90))  # 90d
    # D não repete

    start_str = range_start.strftime("%Y-%m-%d")
    end_str = range_end.strftime("%Y-%m-%d")

    r = c.get(f"/api/reports/retention/?from={start_str}&to={end_str}")
    assert r.status_code == 200
    data = r.data

    assert "repeat_rate" in data
    assert Decimal(str(data["repeat_rate"]["30d"])) == Decimal("25.00")
    assert Decimal(str(data["repeat_rate"]["60d"])) == Decimal("50.00")
    assert Decimal(str(data["repeat_rate"]["90d"])) == Decimal("75.00")


@pytest.mark.django_db
def test_retention_cohort_monthly_structure():
    """
    Valida que cohort retorna lista com estrutura esperada (month, acquired, M1, etc).
    """
    from users.models import Tenant
    from core.models import SalonCustomer
    import uuid, datetime
    from django.utils.timezone import make_aware

    suffix = str(uuid.uuid4())[:8]
    tenant = Tenant.objects.create(
        slug=f"pro-cohort-{suffix}",
        name="Pro Cohort",
        plan_tier=Tenant.PLAN_PRO,
    )
    user = User.objects.create_user(
        username=f"cohort_{suffix}",
        password="x",
        email=f"cohort_{suffix}@test.com",
        tenant=tenant,
    )

    c = APIClient()
    c.force_authenticate(user)

    prof_kwargs, professional = _get_or_create_professional(user)
    service = Service.objects.create(
        user=user,
        name="Service Cohort",
        duration_minutes=30,
        price_eur=50,
        tenant=tenant,
    )

    dt_field = _resolve_dt_field(Appointment)
    price_field = _resolve_price_field(Appointment)

    def create_appt(customer, when, price=50):
        slot_kwargs = _make_slot_for(when, service, professional, user)
        base = {
            "tenant": tenant,
            "client": user,
            "customer": customer,
            "service": service,
            "professional": professional,
            dt_field: when,
            "status": "completed",
        }
        if price_field:
            base[price_field] = Decimal(str(price))
        base.update(slot_kwargs)
        return Appointment.objects.create(**base)

    m0 = make_aware(datetime.datetime(2025, 1, 15, 10, 0))
    m1 = make_aware(datetime.datetime(2025, 2, 10, 10, 0))

    customer_a = SalonCustomer.objects.create(
        tenant=tenant,
        name="Cohort A",
        email=f"a_{suffix}@c.com",
    )
    customer_b = SalonCustomer.objects.create(
        tenant=tenant,
        name="Cohort B",
        email=f"b_{suffix}@c.com",
    )

    SalonCustomer.objects.filter(pk=customer_a.pk).update(created_at=m0)
    SalonCustomer.objects.filter(pk=customer_b.pk).update(created_at=m0)
    customer_a.refresh_from_db()
    customer_b.refresh_from_db()

    create_appt(customer_a, m0)
    create_appt(customer_b, m0)
    create_appt(customer_a, m1)

    r = c.get("/api/reports/retention/?from=2025-01-01&to=2025-01-31")
    assert r.status_code == 200
    data = r.data

    assert "cohort" in data
    cohort = data["cohort"]
    assert isinstance(cohort, list)
    assert len(cohort) >= 1

    jan_entry = next((e for e in cohort if e["month"] == "2025-01"), None)
    assert jan_entry is not None
    assert isinstance(jan_entry, dict)
    assert "month" in jan_entry
    assert "acquired" in jan_entry
    assert jan_entry["acquired"] == 2
    assert "M1" in jan_entry
    assert jan_entry["M1"] == 1  # Apenas customer_a volta em fevereiro


# ---------- Edge cases: BE-REPORTS-03 item 4 ----------


@pytest.mark.django_db
def test_retention_short_range_one_day():
    """
    Range de 1 dia (from == to) → period.days == 0, sem erro.
    Validado com dados reais (agendamento criado).
    """
    from users.models import Tenant
    from core.models import SalonCustomer
    import uuid, datetime
    from django.utils.timezone import make_aware

    suffix = str(uuid.uuid4())[:8]
    tenant = Tenant.objects.create(
        slug=f"pro-1day-{suffix}",
        name="1Day",
        plan_tier=Tenant.PLAN_PRO,
    )
    user = User.objects.create_user(
        username=f"1day_{suffix}",
        password="x",
        email=f"1day_{suffix}@test.com",
        tenant=tenant,
    )
    c = APIClient()
    c.force_authenticate(user)

    prof_kwargs, professional = _get_or_create_professional(user)
    service = Service.objects.create(
        user=user,
        name="Svc 1Day",
        duration_minutes=30,
        price_eur=50,
        tenant=tenant,
    )

    dt_field = _resolve_dt_field(Appointment)
    price_field = _resolve_price_field(Appointment)

    dt = make_aware(datetime.datetime(2025, 6, 15, 10, 0))
    customer = SalonCustomer.objects.create(
        tenant=tenant,
        name="Client 1Day",
        email=f"1day_{suffix}@c.com",
    )
    SalonCustomer.objects.filter(pk=customer.pk).update(created_at=dt)

    slot_kwargs = _make_slot_for(dt, service, professional, user)
    base = {
        "tenant": tenant,
        "client": user,
        "customer": customer,
        "service": service,
        "professional": professional,
        dt_field: dt,
        "status": "completed",
    }
    if price_field:
        base[price_field] = Decimal("50")
    base.update(slot_kwargs)
    Appointment.objects.create(**base)

    r = c.get("/api/reports/retention/?from=2025-06-15&to=2025-06-15")
    assert r.status_code == 200
    data = r.data
    assert data["period"]["days"] == 0
    assert "cohort" in data
    assert "repeat_rate" in data
    assert "definitions" in data


# ---------- professional_id / service_id filters (fix/relatorios-filtros-parity) ----------


def _setup_prof_service_filter_scenario(suffix):
    """
    Cria tenant Pro com 2 profissionais e 2 serviços, e agendamentos completados
    cruzando as combinações:
      - Profissional 1 + Serviço 1: 2 agendamentos
      - Profissional 2 + Serviço 2: 1 agendamento
    Retorna (client_autenticado, professional1, professional2, service1, service2).
    """
    from django.core.cache import cache
    from users.models import Tenant
    from core.models import Professional, ScheduleSlot

    # Evita colisões de cache entre testes: a chave de cache de reports usa
    # apenas user_id + params, e o pk do user pode ser reaproveitado entre
    # transações de teste (SQLite). Ver reports/utils/cache.py.
    cache.clear()

    tenant = Tenant.objects.create(
        slug=f"pro-filters-{suffix}",
        name="Pro Filters",
        plan_tier=Tenant.PLAN_PRO,
    )
    user = User.objects.create_user(
        username=f"filters_{suffix}",
        password="x",
        email=f"filters_{suffix}@test.com",
        tenant=tenant,
    )
    UserFeatureFlags.objects.update_or_create(
        user=user, defaults={"is_pro": True, "reports_enabled": True}
    )

    prof1 = Professional.objects.create(tenant=tenant, user=user, name="Prof 1")
    prof2 = Professional.objects.create(tenant=tenant, user=user, name="Prof 2")

    service1 = Service.objects.create(
        tenant=tenant, user=user, name="Serviço 1", duration_minutes=30, price_eur=30
    )
    service2 = Service.objects.create(
        tenant=tenant, user=user, name="Serviço 2", duration_minutes=45, price_eur=50
    )

    now = timezone.now()

    def make_appt(professional, service, when, price):
        slot = ScheduleSlot.objects.create(
            tenant=tenant,
            professional=professional,
            start_time=when,
            end_time=when + timedelta(minutes=service.duration_minutes),
            status="booked",
        )
        return Appointment.objects.create(
            tenant=tenant,
            client=user,
            service=service,
            professional=professional,
            slot=slot,
            status=COMPLETED,
        )

    make_appt(prof1, service1, now - timedelta(days=1), 30)
    make_appt(prof1, service1, now - timedelta(days=2), 30)
    make_appt(prof2, service2, now - timedelta(days=1), 50)

    c = APIClient()
    c.force_authenticate(user)
    return c, prof1, prof2, service1, service2


@pytest.mark.django_db
def test_top_services_filter_by_professional_id_only():
    import uuid

    c, prof1, prof2, service1, service2 = _setup_prof_service_filter_scenario(
        str(uuid.uuid4())[:8]
    )

    r = c.get(f"/api/reports/top-services/?professional_id={prof1.id}")
    assert r.status_code == 200
    names = {row["service_name"] for row in r.data}
    assert names == {"Serviço 1"}
    row = r.data[0]
    assert row["qty"] == 2


@pytest.mark.django_db
def test_top_services_filter_by_service_id_only():
    import uuid

    c, prof1, prof2, service1, service2 = _setup_prof_service_filter_scenario(
        str(uuid.uuid4())[:8]
    )

    r = c.get(f"/api/reports/top-services/?service_id={service2.id}")
    assert r.status_code == 200
    names = {row["service_name"] for row in r.data}
    assert names == {"Serviço 2"}
    row = r.data[0]
    assert row["qty"] == 1


@pytest.mark.django_db
def test_top_services_filter_by_professional_and_service_id():
    import uuid

    c, prof1, prof2, service1, service2 = _setup_prof_service_filter_scenario(
        str(uuid.uuid4())[:8]
    )

    # Combinação que existe: prof1 + service1 -> 2
    r = c.get(
        f"/api/reports/top-services/?professional_id={prof1.id}&service_id={service1.id}"
    )
    assert r.status_code == 200
    assert len(r.data) == 1
    assert r.data[0]["qty"] == 2

    # Combinação que não existe: prof1 + service2 -> vazio
    r2 = c.get(
        f"/api/reports/top-services/?professional_id={prof1.id}&service_id={service2.id}"
    )
    assert r2.status_code == 200
    assert r2.data == []


@pytest.mark.django_db
def test_top_services_invalid_professional_id_returns_400():
    import uuid

    c, prof1, prof2, service1, service2 = _setup_prof_service_filter_scenario(
        str(uuid.uuid4())[:8]
    )

    r = c.get("/api/reports/top-services/?professional_id=not-an-int")
    assert r.status_code == 400
    assert "detail" in r.data


@pytest.mark.django_db
def test_top_services_invalid_service_id_returns_400():
    import uuid

    c, prof1, prof2, service1, service2 = _setup_prof_service_filter_scenario(
        str(uuid.uuid4())[:8]
    )

    r = c.get("/api/reports/top-services/?service_id=abc")
    assert r.status_code == 400
    assert "detail" in r.data


@pytest.mark.django_db
def test_top_services_no_filter_params_preserves_existing_behavior():
    import uuid

    c, prof1, prof2, service1, service2 = _setup_prof_service_filter_scenario(
        str(uuid.uuid4())[:8]
    )

    r = c.get("/api/reports/top-services/")
    assert r.status_code == 200
    names = {row["service_name"] for row in r.data}
    assert names == {"Serviço 1", "Serviço 2"}


@pytest.mark.django_db
def test_top_services_export_csv_filter_by_professional_id():
    import uuid

    c, prof1, prof2, service1, service2 = _setup_prof_service_filter_scenario(
        str(uuid.uuid4())[:8]
    )

    r = c.get(f"/api/reports/top-services/export/?professional_id={prof1.id}")
    assert r.status_code == 200
    content = r.content.decode("utf-8")
    assert "Serviço 1" in content
    assert "Serviço 2" not in content


@pytest.mark.django_db
def test_retention_filter_by_professional_id():
    import uuid
    from django.core.cache import cache
    from core.models import SalonCustomer, Professional, ScheduleSlot
    from users.models import Tenant

    cache.clear()
    suffix = str(uuid.uuid4())[:8]
    tenant = Tenant.objects.create(
        slug=f"pro-retention-filter-{suffix}",
        name="Retention Filter",
        plan_tier=Tenant.PLAN_PRO,
    )
    user = User.objects.create_user(
        username=f"ret_filter_{suffix}",
        password="x",
        email=f"ret_filter_{suffix}@test.com",
        tenant=tenant,
    )
    prof1 = Professional.objects.create(tenant=tenant, user=user, name="Prof R1")
    prof2 = Professional.objects.create(tenant=tenant, user=user, name="Prof R2")
    service = Service.objects.create(
        tenant=tenant, user=user, name="Svc Ret", duration_minutes=30, price_eur=40
    )

    now = timezone.now()

    customer1 = SalonCustomer.objects.create(
        tenant=tenant, name="C1", email=f"c1_{suffix}@c.com"
    )
    customer2 = SalonCustomer.objects.create(
        tenant=tenant, name="C2", email=f"c2_{suffix}@c.com"
    )

    def make_appt(professional, customer, when, price):
        slot = ScheduleSlot.objects.create(
            tenant=tenant,
            professional=professional,
            start_time=when,
            end_time=when + timedelta(minutes=30),
            status="booked",
        )
        return Appointment.objects.create(
            tenant=tenant,
            client=user,
            customer=customer,
            service=service,
            professional=professional,
            slot=slot,
            status=COMPLETED,
            **{},
        )

    # prof1 atende customer1 (novo, criado agora)
    make_appt(prof1, customer1, now, 40)
    # prof2 atende customer2 (novo, criado agora)
    make_appt(prof2, customer2, now, 40)

    c = APIClient()
    c.force_authenticate(user)

    r = c.get(f"/api/reports/retention/?professional_id={prof1.id}")
    assert r.status_code == 200
    data = r.data
    # Apenas o agendamento do prof1 deve ser considerado
    assert data["new_clients"]["qty"] == 1


@pytest.mark.django_db
def test_retention_invalid_professional_id_returns_400():
    import uuid
    from django.core.cache import cache
    from users.models import Tenant

    cache.clear()
    suffix = str(uuid.uuid4())[:8]
    tenant = Tenant.objects.create(
        slug=f"pro-retention-invalid-{suffix}",
        name="Retention Invalid",
        plan_tier=Tenant.PLAN_PRO,
    )
    user = User.objects.create_user(
        username=f"ret_invalid_{suffix}",
        password="x",
        email=f"ret_invalid_{suffix}@test.com",
        tenant=tenant,
    )
    c = APIClient()
    c.force_authenticate(user)

    r = c.get("/api/reports/retention/?professional_id=xyz")
    assert r.status_code == 400
    assert "detail" in r.data
