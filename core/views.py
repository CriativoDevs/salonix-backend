import logging

from rest_framework import status as drf_status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.filters import OrderingFilter
from rest_framework.generics import ListAPIView, CreateAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework_simplejwt.tokens import RefreshToken

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    OpenApiParameter,
    OpenApiExample,
)

from core.email_utils import (
    send_appointment_confirmation_email,
    send_appointment_cancellation_email,
)
from core.models import (
    Appointment,
    AppointmentSeries,
    Professional,
    SalonCustomer,
    Service,
    ScheduleSlot,
    ProfessionalService,
    AppointmentReservedSlot,
    Feedback,
)
from users.models import Tenant, TenantStaffMember, TenantBusinessHours
from core.utils.client_access import create_client_access_data
from notifications.services import (
    send_customer_pwa_invite,
    trigger_feedback_notifications,
)
from core.serializers import (
    AppointmentDetailSerializer,
    AppointmentSerializer,
    AppointmentSeriesCreateResponseSerializer,
    AppointmentSeriesSerializer,
    AppointmentSeriesUpdateResponseSerializer,
    AppointmentSeriesUpdateSerializer,
    AppointmentSeriesOccurrenceCancelResponseSerializer,
    BulkAppointmentResponseSerializer,
    BulkAppointmentSerializer,
    MixedBulkAppointmentRequestSerializer,
    MixedBulkAppointmentResponseSerializer,
    ProfessionalSerializer,
    SalonCustomerSerializer,
    ServiceSerializer,
    ScheduleSlotSerializer,
    ClientAccessLinkRequestSerializer,
    ClientAccessAcceptSerializer,
    PublicClientAccessLinkRequestSerializer,
    PublicClientRegistrationSerializer,
    FeedbackSerializer,
    ClientLoginSerializer,
    ClientSetPasswordSerializer,
)
from core.mixins import TenantIsolatedMixin
from core.utils.pagination import get_limit_offset, set_pagination_headers

from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Q
from django.http import StreamingHttpResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.core.cache import cache
import uuid
from django.utils.dateparse import parse_datetime, parse_date
from django.core import signing
from django.conf import settings
from prometheus_client import Counter, REGISTRY

from users.permissions import IsSalonOwnerOfAppointment
from core.utils.ics import ICSGenerator, verify_public_ics_token

import csv
import io
from typing import Any, Dict, List, Optional, cast

from users.throttling import (
    UsersClientAccessLinkThrottle,
    UsersClientRegistrationThrottle,
    FeedbackCreateThrottle,
)
from users.security import enforce_captcha_or_raise
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from reports.throttling import PerUserScopedRateThrottle
from rest_framework import status as drf_status
from users.models import TenantStaffMember, CustomUser
from salonix_backend.validators import validate_phone_number, sanitize_text_input
import secrets


def _get_or_create_counter(name: str, documentation: str, labelnames: tuple[str, ...]):
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        if isinstance(existing, Counter):
            return existing
        # If it exists but isn't a Counter, unregister and recreate
        REGISTRY.unregister(existing)  # type: ignore[attr-defined]
    return Counter(name, documentation, labelnames)


# Métricas Prometheus
ICS_DOWNLOADS_TOTAL = _get_or_create_counter(
    "ics_downloads_total",
    "Total number of .ics calendar downloads",
    ("tenant_id", "status"),
)

BULK_APPOINTMENTS_TOTAL = _get_or_create_counter(
    "bulk_appointments_created_total",
    "Total number of bulk appointments created",
    ("tenant_id", "status"),
)

BULK_APPOINTMENTS_SIZE = _get_or_create_counter(
    "bulk_appointments_average_size",
    "Average size of bulk appointments",
    ("tenant_id",),
)

# Errors counter (separate from total with status)
BULK_APPOINTMENTS_ERRORS = _get_or_create_counter(
    "bulk_appointments_errors_total",
    "Total number of bulk appointment errors",
    ("tenant_id", "status"),
)

CSV_IMPORT_REJECTIONS_TOTAL = _get_or_create_counter(
    "csv_import_rejections_total",
    "Total number of rejected CSV import attempts by reason",
    ("reason",),
)

APPOINTMENT_SERIES_UPDATED_TOTAL = _get_or_create_counter(
    "appointment_series_updated_total",
    "Total number of series update operations",
    ("tenant_id", "action", "status"),
)

# Métricas de acesso do cliente (PWA)
CLIENT_ACCESS_EVENTS_TOTAL = _get_or_create_counter(
    "client_access_events_total",
    "Eventos de acesso do cliente (emitir/aceitar/refresh)",
    ("event", "result", "tenant_id"),
)

FEEDBACK_EVENTS_TOTAL = _get_or_create_counter(
    "feedback_events_total",
    "Eventos de feedback",
    ("tenant_id", "action", "result", "category"),
)
FEEDBACK_RATINGS_SUM = _get_or_create_counter(
    "feedback_ratings_sum_total",
    "Soma de ratings de feedback",
    ("tenant_id",),
)
FEEDBACK_RATINGS_COUNT = _get_or_create_counter(
    "feedback_ratings_count_total",
    "Contagem de feedbacks (para média)",
    ("tenant_id",),
)
FEEDBACK_CATEGORY_TOTAL = _get_or_create_counter(
    "feedback_category_total",
    "Distribuição por categoria de feedback",
    ("tenant_id", "category"),
)


def _create_client_jwt_tokens(tenant, customer):
    """
    Cria tokens JWT para autenticação de cliente (similar ao sistema de User/Staff).

    Args:
        tenant: Instância de Tenant
        customer: Instância de SalonCustomer

    Returns:
        dict com 'access', 'refresh', 'tenant_id', 'customer_id'
    """

    # Criar um token "fake" usando o customer_id como identificador único
    # JWT tokens normalmente são para Users, mas podemos adaptá-los
    # Usamos uma classe wrapper temporária que simula um User
    class CustomerTokenWrapper:
        def __init__(self, customer_id):
            self.id = customer_id
            self.is_active = True

    wrapper = CustomerTokenWrapper(customer.id)
    refresh = RefreshToken.for_user(wrapper)

    # Adicionar informações customizadas ao token
    refresh["scope"] = "client"
    refresh["tenant_id"] = str(tenant.id)
    refresh["tenant_slug"] = tenant.slug
    refresh["customer_id"] = customer.id

    access_token = refresh.access_token
    access_token["scope"] = "client"
    access_token["tenant_id"] = str(tenant.id)
    access_token["tenant_slug"] = tenant.slug
    access_token["customer_id"] = customer.id

    return {
        "access": str(access_token),
        "refresh": str(refresh),
        "tenant_id": tenant.id,
        "customer_id": customer.id,
    }


def _get_client_from_jwt(request):
    """
    Extrai tenant e customer do JWT token no header Authorization.

    Args:
        request: Request do DRF

    Returns:
        tuple (tenant, customer)

    Raises:
        ValidationError se token inválido ou dados não encontrados
    """
    from rest_framework_simplejwt.authentication import JWTAuthentication

    jwt_auth = JWTAuthentication()

    try:
        validated_token = jwt_auth.get_validated_token(
            jwt_auth.get_raw_token(jwt_auth.get_header(request))
        )
    except Exception:
        raise ValidationError("Token de autenticação inválido ou ausente")

    # Verificar se é token de cliente
    scope = validated_token.get("scope")
    if scope != "client":
        raise ValidationError("Token não é de cliente")

    tenant_id = validated_token.get("tenant_id")
    customer_id = validated_token.get("customer_id")

    if not tenant_id or not customer_id:
        raise ValidationError("Token inválido: dados ausentes")

    try:
        tenant = Tenant.objects.get(id=int(tenant_id), is_active=True)
    except Tenant.DoesNotExist:
        raise ValidationError("Tenant inválido")

    if not tenant.can_use_pwa_client():
        raise ValidationError("Funcionalidade indisponível para este tenant")

    try:
        customer = SalonCustomer.objects.get(id=customer_id, tenant=tenant)
    except SalonCustomer.DoesNotExist:
        raise ValidationError("Cliente inválido")

    return tenant, customer


APPOINTMENT_SERIES_ERRORS_TOTAL = _get_or_create_counter(
    "appointment_series_errors_total",
    "Total number of series update errors",
    ("tenant_id", "action", "error_type"),
)

APPOINTMENT_SERIES_OCCURRENCE_CANCEL_TOTAL = _get_or_create_counter(
    "appointment_series_occurrence_cancel_total",
    "Total number of single occurrence cancellations in series",
    ("tenant_id", "status"),
)

APPOINTMENT_SERIES_CREATED_TOTAL = _get_or_create_counter(
    "appointment_series_created_total",
    "Total number of series created",
    ("tenant_id", "status"),
)

APPOINTMENT_SERIES_SIZE_TOTAL = _get_or_create_counter(
    "appointment_series_size_total",
    "Total number of appointments created per series",
    ("tenant_id",),
)

logger = logging.getLogger(__name__)


def _release_reserved_slots(appointment: Appointment) -> None:
    """Libera todos os slots extras vinculados a um agendamento longo.

    - Marca cada slot extra como disponível
    - Remove o vínculo AppointmentReservedSlot
    """
    # Evita N+1 ao carregar slot
    for link in appointment.reserved_slots.select_related("slot").all():
        try:
            # mark_available já persiste alterações de disponibilidade/estado
            link.slot.mark_available()
        finally:
            link.delete()


def _find_contiguous_block_for(
    *,
    tenant: Tenant,
    professional: Professional,
    start_slot: ScheduleSlot,
    required_minutes: int,
) -> List[ScheduleSlot]:
    """Encontra um bloco contíguo de slots disponíveis suficiente para a duração requerida.

    - Considera apenas slots do mesmo `tenant` e `professional`
    - Exige contiguidade: o próximo slot deve iniciar exatamente no `end_time` do anterior
    - Retorna lista vazia se não houver slots suficientes
    """
    block: List[ScheduleSlot] = []
    if start_slot.professional_id != professional.id:
        return []
    if not start_slot.is_available or start_slot.status != "available":
        return []

    block.append(start_slot)
    accumulated = int(
        (start_slot.end_time - start_slot.start_time).total_seconds() // 60
    )
    if accumulated >= required_minutes:
        return block

    cursor_end = start_slot.end_time
    while accumulated < required_minutes:
        next_slot = (
            ScheduleSlot.objects.filter(
                tenant=tenant,
                professional=professional,
                is_available=True,
                status="available",
                start_time=cursor_end,
            )
            .order_by("start_time")
            .first()
        )
        if not next_slot:
            break
        block.append(next_slot)
        accumulated += int(
            (next_slot.end_time - next_slot.start_time).total_seconds() // 60
        )
        cursor_end = next_slot.end_time

    return block if accumulated >= required_minutes else []


def _user_has_staff_role(user, *roles: str) -> bool:
    checker = getattr(user, "has_staff_role", None)
    if callable(checker):
        return checker(*roles)
    return False


def _is_owner_or_manager(user) -> bool:
    return _user_has_staff_role(
        user,
        TenantStaffMember.Role.OWNER,
        TenantStaffMember.Role.MANAGER,
    )


def _is_collaborator(user) -> bool:
    return _user_has_staff_role(user, TenantStaffMember.Role.COLLABORATOR)


def _get_staff_member(user):
    return getattr(user, "staff_member", None)


class PublicServiceListView(TenantIsolatedMixin, ListAPIView):
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    permission_classes = []

    def get_queryset(self):
        # Para view pública, usar tenant do header ou parâmetro
        tenant_slug = self.request.headers.get("X-Tenant-Slug") or self.request.GET.get(
            "tenant"
        )
        if tenant_slug:
            try:
                from users.models import Tenant

                tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
                qs = Service.objects.filter(tenant=tenant)

                # Filtro por professional_id (mapeamento sugerido)
                professional_id = self.request.GET.get("professional_id")
                if professional_id and professional_id.isdigit():
                    links = ProfessionalService.objects.filter(
                        tenant=tenant,
                        professional_id=int(professional_id),
                        is_active=True,
                    ).values_list("service_id", flat=True)
                    qs = qs.filter(id__in=list(links))

                # Suporte a ordenação explícita via querystring
                ordering = self.request.GET.get("ordering")
                if ordering in {"name", "-name", "price_eur", "-price_eur"}:
                    qs = qs.order_by(ordering)
                elif ordering in {"created_at", "-created_at"}:
                    # Service não possui created_at; usar id como proxy de criação
                    qs = qs.order_by("id" if ordering == "created_at" else "-id")

                return qs
            except Tenant.DoesNotExist:
                pass
        return Service.objects.none()


class PublicProfessionalListView(TenantIsolatedMixin, ListAPIView):
    queryset = Professional.objects.filter(is_active=True)
    serializer_class = ProfessionalSerializer
    permission_classes = []

    def get_queryset(self):
        # Para view pública, usar tenant do header ou parâmetro
        tenant_slug = self.request.headers.get("X-Tenant-Slug") or self.request.GET.get(
            "tenant"
        )
        if tenant_slug:
            try:
                from users.models import Tenant

                tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
                qs = Professional.objects.filter(tenant=tenant, is_active=True)
                # Filtro por service_id (mapeamento sugerido)
                service_id = self.request.GET.get("service_id")
                if service_id and service_id.isdigit():
                    links = ProfessionalService.objects.filter(
                        tenant=tenant, service_id=int(service_id), is_active=True
                    ).values_list("professional_id", flat=True)
                    qs = qs.filter(id__in=list(links))
                return qs
            except Tenant.DoesNotExist:
                pass
        return Professional.objects.none()


class PublicSlotListView(ListAPIView):
    serializer_class = ScheduleSlotSerializer
    permission_classes = []

    def get_queryset(self):
        professional_id = self.request.query_params.get("professional_id")
        if not professional_id:
            raise ValidationError({"professional_id": "Este parâmetro é obrigatório."})
        if not str(professional_id).isdigit():
            raise ValidationError({"professional_id": "Valor inválido."})

        # Respeitar o tenant informado (header X-Tenant-Slug ou query param tenant)
        tenant_slug = self.request.headers.get("X-Tenant-Slug") or self.request.GET.get(
            "tenant"
        )

        qs = ScheduleSlot.objects.filter(
            professional_id=int(professional_id), is_available=True
        )

        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            parsed_from = parse_date(date_from) or parse_datetime(date_from)
            if not parsed_from:
                raise ValidationError({"date_from": "Formato de data inválido."})
            qs = qs.filter(start_time__gte=parsed_from)
        if date_to:
            parsed_to = parse_date(date_to) or parse_datetime(date_to)
            if not parsed_to:
                raise ValidationError({"date_to": "Formato de data inválido."})
            qs = qs.filter(start_time__lte=parsed_to)

        if tenant_slug:
            try:
                from users.models import Tenant

                tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
                qs = qs.filter(tenant=tenant)
            except Tenant.DoesNotExist:
                # Se o tenant não existir, não retornar slots
                return ScheduleSlot.objects.none()

        return qs.order_by("start_time")


class PublicTenantDetailView(APIView):
    """
    GET /api/public/tenants/<slug>/

    Endpoint PÚBLICO para obter informações básicas do tenant.
    NÃO requer autenticação.

    Retorna apenas dados públicos: nome, endereço, contato, branding.
    NÃO expõe: feature flags, plan_tier, dados sensíveis.

    Usado por clientes PWA para carregar informações do salão sem autenticação.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: "users.serializers.TenantPublicSerializer"},
        description="Retorna informações públicas do tenant (nome, endereço, logo, contato).",
    )
    def get(self, request, slug):
        from users.models import Tenant
        from users.serializers import TenantPublicSerializer

        try:
            tenant = Tenant.objects.get(slug=slug, is_active=True)
        except Tenant.DoesNotExist:
            return Response(
                {"detail": "Tenant não encontrado."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        serializer = TenantPublicSerializer(tenant)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)


class PublicClientRegistrationView(APIView):
    """
    POST /api/public/<tenant_slug>/clients/register/

    Endpoint PÚBLICO (sem autenticação) para auto-cadastro de clientes via
    link partilhado pelo tenant (BE-MARKETING-03).

    Reaproveita a criação de SalonCustomer + o mesmo magic link de acesso
    (send_customer_pwa_invite) já usado quando staff adiciona um cliente
    manualmente. Não coleta senha no formulário — o cliente define a senha
    depois, ao seguir o link recebido por email.
    """

    permission_classes = [AllowAny]
    throttle_classes = [UsersClientRegistrationThrottle]
    throttle_scope = "clients_registration"

    @extend_schema(
        request=PublicClientRegistrationSerializer,
        responses={
            201: OpenApiResponse(response=OpenApiTypes.OBJECT),
            400: OpenApiResponse(response=OpenApiTypes.OBJECT),
            404: OpenApiResponse(response=OpenApiTypes.OBJECT),
        },
        description="Auto-cadastro público de cliente via link do tenant.",
    )
    def post(self, request, tenant_slug):
        try:
            enforce_captcha_or_raise(request)
        except ValidationError:
            return Response(
                {"detail": "Captcha inválido."}, status=drf_status.HTTP_400_BAD_REQUEST
            )

        try:
            tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
        except Tenant.DoesNotExist:
            return Response(
                {"detail": "Tenant não encontrado."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        if not tenant.pwa_client_enabled:
            return Response(
                {"detail": "Tenant não encontrado."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        serializer = PublicClientRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data.get("email")
        if email and SalonCustomer.objects.filter(
            tenant=tenant, email__iexact=email
        ).exists():
            return Response(
                {"detail": "Este email já está registado."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        customer = SalonCustomer.objects.create(
            tenant=tenant,
            name=data["name"],
            email=email or None,
            phone_number=data.get("phone_number") or None,
            marketing_opt_in=data.get("marketing_opt_in", False),
        )

        try:
            send_customer_pwa_invite(tenant=tenant, customer=customer, invited_by=None)
        except Exception:  # pragma: no cover
            logger.error(
                "Public client registration invite dispatch failed",
                exc_info=True,
                extra={"tenant_id": tenant.id, "customer_id": customer.id},
            )

        return Response(
            {
                "customer_id": customer.id,
                "message": "Cadastro realizado. Verifique o seu email para aceder.",
            },
            status=drf_status.HTTP_201_CREATED,
        )


class AppointmentCreateView(TenantIsolatedMixin, CreateAPIView):
    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["allow_auto_customer"] = True
        context.setdefault("enforce_client_slot_uniqueness", False)
        return context

    def _ensure_customer(
        self, tenant: Optional[Tenant], customer: Optional[SalonCustomer]
    ):
        if customer or tenant is None:
            return customer

        user = self.request.user
        email = (user.email or "").strip() or None
        base_name = user.get_full_name() or user.username or "Cliente"

        query = SalonCustomer.objects.filter(tenant=tenant)
        if email:
            existing = query.filter(email__iexact=email).first()
            if existing:
                return existing
        existing = query.filter(name=base_name).first()
        if existing:
            return existing

        return SalonCustomer.objects.create(
            tenant=tenant,
            name=base_name,
            email=email,
            phone_number=getattr(user, "phone_number", "") or "",
            marketing_opt_in=True,
            is_active=True,
            notes="Gerado automaticamente via autoagendamento.",
        )

    def perform_create(self, serializer):
        data = cast(Dict[str, Any], serializer.validated_data)
        slot = data.get("slot")
        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )

        if slot is None:
            # Auto-criação de slot a partir de start_time / end_time / professional
            professional = data["professional"]
            start_time = data.pop("start_time")
            end_time = data.pop("end_time")
            slot, created = ScheduleSlot.objects.get_or_create(
                professional=professional,
                start_time=start_time,
                defaults={"end_time": end_time, "tenant": tenant, "is_available": True, "status": "available"},
            )
            if not created and (not slot.is_available or slot.status != "available"):
                raise ValidationError("Este horário já foi agendado ou não está disponível.")
            data["slot"] = slot
        else:
            data.pop("start_time", None)
            data.pop("end_time", None)
            if (not slot.is_available) or (slot.status != "available"):
                raise ValidationError(
                    "Este horário já foi agendado ou não está disponível."
                )

        # marca como reservado via helper do model
        slot.mark_booked()

        customer = self._ensure_customer(tenant, data.get("customer"))

        save_kwargs: Dict[str, Any] = {"client": self.request.user}
        if tenant:
            save_kwargs["tenant"] = tenant
        if customer:
            save_kwargs["customer"] = customer

        appointment = serializer.save(**save_kwargs)

        if customer and appointment.customer_id != customer.id:
            appointment.customer = customer
            appointment.save(update_fields=["customer"])

        logger.info(
            "Appointment created successfully",
            extra={
                "appointment_id": appointment.id,
                "tenant_id": getattr(tenant, "id", None),
                "customer_id": getattr(customer, "id", None),
                "professional_id": appointment.professional_id,
                "service_id": appointment.service_id,
            },
        )

        # Envia e-mail de confirmação
        try:
            customer = appointment.customer
            recipient_email = (
                customer.email
                if customer and customer.email
                else (self.request.user.email or "")
            )
            if recipient_email:
                client_display_name = (
                    customer.name
                    if customer and customer.name
                    else (
                        self.request.user.get_full_name()
                        or self.request.user.username
                        or (self.request.user.email or "").split("@")[0]
                    )
                )
                salon_name = (
                    appointment.tenant.name if appointment.tenant else "TimelyOne"
                )
                send_appointment_confirmation_email(
                    to_email=recipient_email,
                    client_name=client_display_name,
                    service_name=appointment.service.name,
                    date_time=appointment.slot.start_time,
                    salon_name=salon_name,
                    appointment_id=appointment.id,
                )
        except Exception:  # pragma: no cover - apenas logging
            logger.error("Falha ao enviar e-mail de confirmação", exc_info=True)


class BulkAppointmentCreateView(TenantIsolatedMixin, APIView):
    """
    POST /api/appointments/bulk/

    Criar múltiplos agendamentos em uma única transação atômica.
    Todos os agendamentos são criados ou nenhum é criado.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=BulkAppointmentSerializer,
        responses={201: BulkAppointmentResponseSerializer},
    )
    def post(self, request):
        # fonte única da verdade para tenant
        tenant = getattr(request.user, "tenant", None) or getattr(
            request, "tenant", None
        )

        serializer = BulkAppointmentSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            tenant_id = tenant.id if tenant else "unknown"
            BULK_APPOINTMENTS_TOTAL.labels(
                tenant_id=tenant_id, status="validation_error"
            ).inc()
            BULK_APPOINTMENTS_ERRORS.labels(
                tenant_id=tenant_id, status="validation_error"
            ).inc()
            return Response(serializer.errors, status=drf_status.HTTP_400_BAD_REQUEST)

        data = cast(Dict[str, Any], serializer.validated_data)
        user = request.user

        try:
            # IDs de serviço/profissional podem vir no nível do payload ou por item
            top_service_id = cast(Optional[int], data.get("service_id"))
            top_professional_id = cast(Optional[int], data.get("professional_id"))

            appointments_list = cast(List[Dict[str, Any]], data["appointments"])
            service_ids: List[int] = []
            professional_ids: List[int] = []
            for appt in appointments_list:
                sid = cast(Optional[int], appt.get("service_id")) or top_service_id
                pid = (
                    cast(Optional[int], appt.get("professional_id"))
                    or top_professional_id
                )
                if sid is None or pid is None:
                    # segurança extra: o serializer já valida isso
                    raise ValidationError(
                        "Cada agendamento deve informar service_id e professional_id."
                    )
                service_ids.append(cast(int, sid))
                professional_ids.append(cast(int, pid))

            # garantir consistência com o tenant resolvido e carregar de uma vez
            services = list(
                Service.objects.filter(id__in=set(service_ids), tenant=tenant)
            )
            professionals = list(
                Professional.objects.filter(id__in=set(professional_ids), tenant=tenant)
            )
            services_by_id = {s.id: s for s in services}
            professionals_by_id = {p.id: p for p in professionals}

            if len(services_by_id) != len(set(service_ids)):
                raise ValidationError(
                    "Um ou mais serviços não existem para este tenant."
                )
            if len(professionals_by_id) != len(set(professional_ids)):
                raise ValidationError(
                    "Um ou mais profissionais não existem para este tenant."
                )

            staff_member = _get_staff_member(user)
            if _is_collaborator(user):
                # colaboradores só podem criar para si: validar todos os profissionais
                for pid in set(professional_ids):
                    prof = professionals_by_id.get(pid)
                    allowed = prof and (
                        prof.user_id == getattr(user, "id", None)
                        or (staff_member and prof.staff_member_id == staff_member.id)
                    )
                    if not allowed:
                        raise PermissionDenied(
                            "Colaboradores só podem criar agendamentos para si mesmos."
                        )

            # resolver/crear cliente
            customer = None
            customer_id = data.get("customer_id")
            if customer_id is not None:
                customer = SalonCustomer.objects.get(
                    id=cast(int, customer_id), tenant=tenant
                )
            elif tenant is not None:
                customer_email = data.get("client_email") or getattr(
                    user, "email", None
                )
                customer_name = data.get("client_name") or "Cliente do salão"
                if customer_email:
                    customer = (
                        SalonCustomer.objects.filter(
                            tenant=tenant, email__iexact=customer_email
                        )
                        .order_by("id")
                        .first()
                    )
                if not customer:
                    customer = (
                        SalonCustomer.objects.filter(tenant=tenant)
                        .order_by("id")
                        .first()
                    )
                if not customer:
                    customer = SalonCustomer.objects.create(
                        tenant=tenant,
                        name=customer_name,
                        email=customer_email or "",
                        phone_number=data.get("client_phone") or "",
                        marketing_opt_in=True,
                        is_active=True,
                        notes="Gerado via seed/bulk de agendamentos.",
                    )

            # pré-carregar slots (apenas itens que informam slot_id)
            slot_ids = [cast(int, a["slot_id"]) for a in appointments_list if a.get("slot_id")]
            slots = list(ScheduleSlot.objects.filter(id__in=slot_ids, tenant=tenant))
            slots_by_id = {s.id: s for s in slots}

            suggest_only = bool(data.get("suggest_only", False))

            from decimal import Decimal

            total_value_dec = Decimal("0")

            # Helper para sugerir próximo slot (mesmo dia; se não, dia seguinte)
            from django.utils import timezone
            from datetime import timedelta

            def suggest_next_slot(prof: Professional, ref_slot: ScheduleSlot):
                try:
                    # Mesmo dia, após o horário do slot de referência
                    same_day_qs = (
                        ScheduleSlot.objects.filter(
                            tenant=tenant,
                            professional=prof,
                            is_available=True,
                            status="available",
                        )
                        .filter(start_time__date=ref_slot.start_time.date())
                        .filter(start_time__gt=ref_slot.start_time)
                        .order_by("start_time")
                    )
                    next_same = same_day_qs.first()
                    if next_same:
                        return {
                            "slot_id": next_same.id,
                            "start_time": next_same.start_time,
                            "end_time": next_same.end_time,
                            "professional_id": prof.id,
                        }

                    # Dia seguinte (qualquer horário disponível)
                    next_day = ref_slot.start_time.date() + timedelta(days=1)
                    next_day_qs = (
                        ScheduleSlot.objects.filter(
                            tenant=tenant,
                            professional=prof,
                            is_available=True,
                            status="available",
                        )
                        .filter(start_time__date=next_day)
                        .order_by("start_time")
                    )
                    next_any = next_day_qs.first()
                    if next_any:
                        return {
                            "slot_id": next_any.id,
                            "start_time": next_any.start_time,
                            "end_time": next_any.end_time,
                            "professional_id": prof.id,
                        }
                except Exception:
                    pass
                return None

            # Processamento item a item — toda a criação dentro de um único atomic
            appointments: list[Appointment] = []
            results: list[dict] = []

            with transaction.atomic():
                for appt_data in appointments_list:
                    sid = cast(int, appt_data.get("service_id") or top_service_id)
                    pid = cast(int, appt_data.get("professional_id") or top_professional_id)
                    service = services_by_id.get(sid)
                    professional = professionals_by_id.get(pid)
                    raw_slot_id = appt_data.get("slot_id")
                    slot = slots_by_id.get(cast(int, raw_slot_id)) if raw_slot_id else None

                    error_code = None
                    message = None
                    suggested = None

                    if raw_slot_id and slot is None:
                        error_code = "slot_not_found"
                        message = "Slot não encontrado para este tenant."
                    elif raw_slot_id and slot is not None:
                        # Compatibilidade com profissional
                        if slot.professional_id != professional.id:
                            error_code = "slot_wrong_professional"
                            message = "Slot não pertence ao profissional informado."

                        # Passado
                        if error_code is None and slot.start_time <= timezone.now():
                            error_code = "slot_in_past"
                            message = "Slot no passado."

                        # Disponibilidade
                        if error_code is None and (
                            not slot.is_available
                            or getattr(slot, "status", "available") != "available"
                        ):
                            error_code = "slot_unavailable"
                            message = "Slot indisponível."

                    if error_code is None:
                        if suggest_only and slot is not None:
                            # Apenas sugerir (não criar/agendar); válido só para itens com slot_id
                            suggested = {
                                "slot_id": slot.id,
                                "start_time": slot.start_time,
                                "end_time": slot.end_time,
                                "professional_id": professional.id,
                            }
                            results.append(
                                {
                                    "slot_id": slot.id,
                                    "status": "ok",
                                    "message": "Slot disponível.",
                                    "suggested_slot": suggested,
                                }
                            )
                        else:
                            if not raw_slot_id:
                                # Auto-criação de slot a partir de start_time/end_time
                                slot, _ = ScheduleSlot.objects.get_or_create(
                                    professional=professional,
                                    start_time=appt_data["start_time"],
                                    end_time=appt_data["end_time"],
                                    tenant=tenant,
                                    defaults={"is_available": True, "status": "available"},
                                )
                                if not slot.is_available or slot.status != "available":
                                    error_code = "slot_occupied"
                                    message = "O horário informado já está ocupado."
                            if error_code is None:
                                slot.mark_booked()
                                appointment = Appointment.objects.create(
                                    client=user,
                                    service=service,
                                    professional=professional,
                                    slot=slot,
                                    notes=str(
                                        appt_data.get("notes") or data.get("notes") or ""
                                    ),
                                    status="scheduled",
                                    tenant=tenant,
                                    customer=customer,
                                )
                                appointments.append(appointment)

                                raw_unit = getattr(service, "price_eur", None) or getattr(
                                    service, "price", 0
                                )
                                try:
                                    unit_price = Decimal(str(raw_unit))
                                except Exception:
                                    unit_price = Decimal("0")
                                total_value_dec += unit_price

                                results.append(
                                    {
                                        "slot_id": slot.id,
                                        "status": "created",
                                        "appointment_id": appointment.id,
                                        "message": "Agendamento criado.",
                                    }
                                )

                    if error_code is not None:
                        # Item inválido — sugerir próximo slot (apenas quando há slot de referência)
                        if slot is not None and professional is not None:
                            suggested = suggest_next_slot(professional, slot)
                        results.append(
                            {
                                "slot_id": cast(int, raw_slot_id) if raw_slot_id else None,
                                "status": "error",
                                "error_code": error_code or "invalid",
                                "message": message or "Item inválido.",
                                "suggested_slot": suggested,
                            }
                        )

                # Qualquer item inválido cancela a transação inteira (tudo ou nada)
                if not suggest_only and any(r.get("status") == "error" for r in results):
                    raise ValidationError(
                        {
                            "detail": "Transação cancelada: um ou mais itens inválidos.",
                            "errors": [r for r in results if r.get("status") == "error"],
                        }
                    )

            count = len(appointments)
            total_value = float(total_value_dec)

            tenant_label = tenant.id if tenant is not None else "unknown"
            BULK_APPOINTMENTS_TOTAL.labels(
                tenant_id=tenant_label, status="success"
            ).inc()
            BULK_APPOINTMENTS_SIZE.labels(tenant_id=tenant_label).inc(len(appointments))

            # log estruturado de sucesso
            first_service_id = service_ids[0] if service_ids else None
            first_professional_id = professional_ids[0] if professional_ids else None
            logger.info(
                "Bulk appointments created successfully",
                extra={
                    "tenant_id": getattr(tenant, "id", None),
                    "user_id": user.id,
                    # manter compatibilidade mínima com chaves esperadas
                    "service_id": first_service_id,
                    "professional_id": first_professional_id,
                    # novas chaves informativas
                    "service_ids": list(service_ids),
                    "professional_ids": list(professional_ids),
                    "appointments_count": count,
                    "appointment_ids": [a.id for a in appointments],
                    "total_value": total_value,
                },
            )

            # payload
            serialized = AppointmentSerializer(
                appointments, many=True, context={"request": request}
            ).data
            message = (
                f"{count} agendamentos criados com sucesso"
                if count != 1
                else "1 agendamento criado com sucesso"
            )

            # nomes agregados (primeiro item para compatibilidade)
            service_names = [services_by_id[sid].name for sid in service_ids]
            professional_names = [
                professionals_by_id[pid].name for pid in professional_ids
            ]

            # Envio de e-mail consolidado apenas quando não for sugestão
            if not suggest_only:
                try:
                    if count > 0:
                        from core.email_utils import (
                            send_bulk_appointment_confirmation_email,
                        )

                        consolidated_items = [
                            {
                                "service_name": a.service.name,
                                "start_time": a.slot.start_time,
                                "professional_name": a.professional.name,
                                "appointment_id": a.id,
                            }
                            for a in appointments
                        ]
                        # Priorizar dados do cliente resolvido
                        recipient_email = (
                            (customer.email if customer and customer.email else None)
                            or data.get("client_email")
                            or getattr(user, "email", "")
                        )
                        client_display_name = (
                            (customer.name if customer and customer.name else None)
                            or data.get("client_name")
                            or (getattr(user, "get_full_name", lambda: None)() or None)
                            or getattr(user, "username", None)
                            or (getattr(user, "email", "").split("@")[0])
                        )
                        send_bulk_appointment_confirmation_email(
                            to_email=recipient_email,
                            client_name=str(client_display_name or "Cliente"),
                            items=consolidated_items,
                            salon_name=(tenant.name if tenant else "TimelyOne"),
                        )
                except Exception as e:  # pragma: no cover
                    logger.warning(
                        "Falha ao enviar e-mail consolidado", extra={"error": str(e)}
                    )

            response_payload = {
                "success": count == len(appointments_list),
                "appointment_ids": [a.id for a in appointments],
                "appointments_created": count,
                "total_value": total_value,
                # compatibilidade mínima
                "service_name": service_names[0] if service_names else None,
                "professional_name": (
                    professional_names[0] if professional_names else None
                ),
                # novos campos
                "service_names": service_names,
                "professional_names": professional_names,
                "appointments": serialized,
                "results": results,
                "message": message,
            }

            # Status HTTP
            if suggest_only:
                status_code = drf_status.HTTP_200_OK
            else:
                # 201 (sucesso total), 207 (sucesso parcial), 400 (todos falharam)
                if count == len(appointments_list):
                    status_code = drf_status.HTTP_201_CREATED
                    BULK_APPOINTMENTS_TOTAL.labels(
                        tenant_id=tenant_label, status="success"
                    ).inc()
                elif count == 0:
                    status_code = drf_status.HTTP_400_BAD_REQUEST
                    BULK_APPOINTMENTS_TOTAL.labels(
                        tenant_id=tenant_label, status="validation_error"
                    ).inc()
                    BULK_APPOINTMENTS_ERRORS.labels(
                        tenant_id=tenant_label, status="validation_error"
                    ).inc()
                else:
                    status_code = 207  # Multi-Status
                    BULK_APPOINTMENTS_TOTAL.labels(
                        tenant_id=tenant_label, status="partial"
                    ).inc()

            return Response(response_payload, status=status_code)

        except ValidationError as e:
            # se cair aqui por alguma validação de negócio extra
            BULK_APPOINTMENTS_TOTAL.labels(
                tenant_id=(tenant.id if tenant else "unknown"),
                status="validation_error",
            ).inc()
            BULK_APPOINTMENTS_ERRORS.labels(
                tenant_id=(tenant.id if tenant else "unknown"),
                status="validation_error",
            ).inc()
            return Response({"detail": str(e)}, status=drf_status.HTTP_400_BAD_REQUEST)

        except PermissionDenied:
            raise

        except Exception as e:
            # garante 500 para o teste que mocka .create
            tenant_id = tenant.id if tenant else "unknown"
            BULK_APPOINTMENTS_TOTAL.labels(tenant_id=tenant_id, status="error").inc()
            BULK_APPOINTMENTS_ERRORS.labels(tenant_id=tenant_id, status="error").inc()
            logger.error(
                f"Bulk appointments creation failed: {e}",
                exc_info=True,
                extra={
                    "tenant_id": tenant_id,
                    "user_id": getattr(request.user, "id", None),
                    "service_id": (
                        data.get("service_id") if isinstance(data, dict) else None
                    ),
                    "professional_id": (
                        data.get("professional_id") if isinstance(data, dict) else None
                    ),
                    "slot_ids": slot_ids if "slot_ids" in locals() else None,
                    "error": str(e),
                },
            )
            return Response(
                {"detail": "Erro interno do servidor."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MixedBulkAppointmentCreateView(TenantIsolatedMixin, APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=MixedBulkAppointmentRequestSerializer,
        responses={201: MixedBulkAppointmentResponseSerializer},
    )
    def post(self, request):
        serializer = MixedBulkAppointmentRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user
        tenant = getattr(user, "tenant", None) or getattr(request, "tenant", None)

        # Resolver/gerar cliente
        customer = None
        customer_id = data.get("customer_id")
        if customer_id:
            try:
                customer = SalonCustomer.objects.get(id=int(customer_id), tenant=tenant)
            except SalonCustomer.DoesNotExist:
                raise ValidationError(
                    {"customer_id": "Cliente não encontrado para este tenant."}
                )
        else:
            name = (data.get("client_name") or "").strip()
            email = (data.get("client_email") or "").strip()
            phone = (data.get("client_phone") or "").strip()
            if name or email or phone:
                # Primeiro tenta localizar cliente existente por e-mail (case-insensitive)
                existing = None
                if email:
                    existing = SalonCustomer.objects.filter(
                        tenant=tenant, email__iexact=email
                    ).first()
                if existing:
                    customer = existing
                else:
                    # Cria sem fallback para e-mail do usuário; se não informado, deixa vazio
                    customer = SalonCustomer.objects.create(
                        tenant=tenant,
                        name=name
                        or (getattr(user, "username", "Cliente") or "Cliente"),
                        email=email or None,
                        phone_number=phone,
                        marketing_opt_in=True,
                        is_active=True,
                        notes="Gerado via mixed bulk de agendamentos.",
                    )

        # Pré-carregar slots/serviços/profissionais
        item_list = cast(List[Dict[str, Any]], data.get("items") or [])
        slot_ids = [int(item["slot_id"]) for item in item_list if item.get("slot_id")]
        service_ids = [int(item["service_id"]) for item in item_list]
        professional_ids = [int(item["professional_id"]) for item in item_list]

        slots = list(ScheduleSlot.objects.filter(id__in=set(slot_ids), tenant=tenant))
        services = list(Service.objects.filter(id__in=set(service_ids), tenant=tenant))
        professionals = list(
            Professional.objects.filter(id__in=set(professional_ids), tenant=tenant)
        )
        slots_by_id = {s.id: s for s in slots}
        services_by_id = {s.id: s for s in services}
        professionals_by_id = {p.id: p for p in professionals}

        from decimal import Decimal

        total_value_dec = Decimal("0")
        appointments: List[Appointment] = []
        results: List[Dict[str, Any]] = []

        # Helper local para sugerir próximo slot
        from datetime import timedelta
        from django.utils import timezone

        def _suggest_next_slot(prof: Professional, ref_slot: ScheduleSlot):
            try:
                same_day_qs = (
                    ScheduleSlot.objects.filter(
                        tenant=tenant,
                        professional=prof,
                        is_available=True,
                        status="available",
                    )
                    .filter(start_time__date=ref_slot.start_time.date())
                    .filter(start_time__gt=ref_slot.start_time)
                    .order_by("start_time")
                )
                next_same = same_day_qs.first()
                if next_same:
                    return {
                        "slot_id": next_same.id,
                        "start_time": next_same.start_time,
                        "end_time": next_same.end_time,
                        "professional_id": prof.id,
                    }

                next_day = ref_slot.start_time.date() + timedelta(days=1)
                next_day_qs = (
                    ScheduleSlot.objects.filter(
                        tenant=tenant,
                        professional=prof,
                        is_available=True,
                        status="available",
                    )
                    .filter(start_time__date=next_day)
                    .order_by("start_time")
                )
                next_any = next_day_qs.first()
                if next_any:
                    return {
                        "slot_id": next_any.id,
                        "start_time": next_any.start_time,
                        "end_time": next_any.end_time,
                        "professional_id": prof.id,
                    }
            except Exception:
                pass
            return None

        # Helper para encontrar blocos contíguos suficientes para a duração

        def _find_contiguous_block(
            start_slot: ScheduleSlot, required_minutes: int
        ) -> List[ScheduleSlot]:
            block: List[ScheduleSlot] = [start_slot]
            accumulated = int(
                (start_slot.end_time - start_slot.start_time).total_seconds() // 60
            )
            if accumulated >= required_minutes:
                return block
            cursor_end = start_slot.end_time
            while accumulated < required_minutes:
                next_slot = (
                    ScheduleSlot.objects.filter(
                        tenant=tenant,
                        professional=start_slot.professional,
                        is_available=True,
                        status="available",
                        start_time=cursor_end,
                    )
                    .order_by("start_time")
                    .first()
                )
                if not next_slot:
                    break
                block.append(next_slot)
                accumulated += int(
                    (next_slot.end_time - next_slot.start_time).total_seconds() // 60
                )
                cursor_end = next_slot.end_time
            return block if accumulated >= required_minutes else []

        def _suggest_next_contiguous_block(
            prof: Professional, required_minutes: int, from_time
        ):
            qs = ScheduleSlot.objects.filter(
                tenant=tenant,
                professional=prof,
                is_available=True,
                status="available",
                start_time__gte=from_time,
            ).order_by("start_time")
            for candidate in qs[:50]:  # limitar busca
                block = _find_contiguous_block(candidate, required_minutes)
                if block:
                    first = block[0]
                    last = block[-1]
                    return {
                        "slot_id": first.id,
                        "start_time": first.start_time,
                        "end_time": last.end_time,
                        "professional_id": prof.id,
                    }
            return None

        # Processar itens com sucesso parcial
        for item in item_list:
            raw_slot_id = item.get("slot_id")
            slot = slots_by_id.get(int(raw_slot_id)) if raw_slot_id else None
            service = services_by_id.get(int(item["service_id"]))
            professional = professionals_by_id.get(int(item["professional_id"]))
            suggested = None

            error_code = None
            message = None

            if service is None or professional is None:
                error_code = "not_found"
                message = "Item inválido: recurso não encontrado."
            elif raw_slot_id and slot is None:
                error_code = "not_found"
                message = "Slot não encontrado para este tenant."
            elif slot is not None:
                if slot.professional_id != professional.id:
                    error_code = "wrong_professional"
                    message = "Slot não pertence ao profissional informado."
                elif slot.start_time <= timezone.now():
                    error_code = "slot_in_past"
                    message = "Slot no passado."
                elif (
                    not slot.is_available
                    or getattr(slot, "status", "available") != "available"
                ):
                    error_code = "slot_unavailable"
                    message = "Slot indisponível."
                else:
                    # serviço cabe no slot (ou requer bloco contínuo)
                    try:
                        duration = int(getattr(service, "duration_minutes", 0) or 0)
                    except Exception:
                        duration = 0
                    slot_minutes = int(
                        (slot.end_time - slot.start_time).total_seconds() // 60
                    )
                    if duration > 0 and duration > slot_minutes:
                        block = _find_contiguous_block(slot, duration)
                        if not block:
                            error_code = "continuous_block_unavailable"
                            message = (
                                "Bloco contínuo indisponível para a duração do serviço."
                            )
                    # profissional oferece serviço
                    elif not ProfessionalService.objects.filter(
                        tenant=tenant,
                        service_id=service.id,
                        professional_id=professional.id,
                    ).exists():
                        error_code = "not_offered"
                        message = "Profissional não oferece o serviço."
            else:
                # Caminho auto-criação: apenas validar que profissional oferece o serviço
                if not ProfessionalService.objects.filter(
                    tenant=tenant,
                    service_id=service.id,
                    professional_id=professional.id,
                ).exists():
                    error_code = "not_offered"
                    message = "Profissional não oferece o serviço."

            if error_code is None and service is not None and professional is not None:
                try:
                    with transaction.atomic():
                        if not raw_slot_id:
                            # Auto-criação de slot a partir de start_time/end_time
                            slot, _ = ScheduleSlot.objects.get_or_create(
                                professional=professional,
                                start_time=item["start_time"],
                                end_time=item["end_time"],
                                tenant=tenant,
                                defaults={"is_available": True, "status": "available"},
                            )
                            if not slot.is_available or slot.status != "available":
                                raise ValidationError(
                                    "O horário informado já está ocupado."
                                )
                        # Reservar bloco contínuo se necessário (apenas para slots pré-existentes)
                        try:
                            duration = int(getattr(service, "duration_minutes", 0) or 0)
                        except Exception:
                            duration = 0
                        slot_minutes = int(
                            (slot.end_time - slot.start_time).total_seconds() // 60
                        )
                        extra_slots: List[ScheduleSlot] = []
                        if raw_slot_id and duration > slot_minutes:
                            block = _find_contiguous_block(slot, duration)
                            for s in block[1:]:
                                s.mark_booked()
                                extra_slots.append(s)
                        slot.mark_booked()
                        appointment = Appointment.objects.create(
                            client=user,
                            service=service,
                            professional=professional,
                            slot=slot,
                            notes=str(item.get("notes") or ""),
                            status="scheduled",
                            tenant=tenant,
                            customer=customer,
                        )
                        if extra_slots:
                            from core.models import AppointmentReservedSlot

                            for s in extra_slots:
                                AppointmentReservedSlot.objects.create(
                                    tenant=tenant,
                                    appointment=appointment,
                                    slot=s,
                                )
                    appointments.append(appointment)
                    raw_unit = getattr(service, "price_eur", None) or getattr(
                        service, "price", 0
                    )
                    try:
                        unit_price = Decimal(str(raw_unit))
                    except Exception:
                        unit_price = Decimal("0")
                    total_value_dec += unit_price
                    results.append(
                        {
                            "slot_id": slot.id,
                            "status": "created",
                            "appointment_id": appointment.id,
                            "message": "Agendamento criado.",
                        }
                    )
                except Exception as e:
                    suggested = _suggest_next_slot(professional, slot) if slot is not None else None
                    results.append(
                        {
                            "slot_id": slot.id if slot is not None else None,
                            "status": "error",
                            "message": f"Falha ao criar agendamento: {str(e)}",
                            "suggested_slot": suggested,
                        }
                    )
            else:
                if slot is not None and professional is not None:
                    try:
                        duration = int(getattr(service, "duration_minutes", 0) or 0)
                    except Exception:
                        duration = 0
                    suggested = (
                        _suggest_next_contiguous_block(
                            professional, duration, slot.end_time
                        )
                        if duration
                        and duration
                        > int((slot.end_time - slot.start_time).total_seconds() // 60)
                        else _suggest_next_slot(professional, slot)
                    )
                results.append(
                    {
                        "slot_id": int(raw_slot_id) if raw_slot_id else None,
                        "status": "error",
                        "message": message or "Item inválido.",
                        "suggested_slot": suggested,
                    }
                )

        count = len(appointments)
        total_value = float(total_value_dec)

        tenant_label = tenant.id if tenant is not None else "unknown"
        if count == len(item_list):
            BULK_APPOINTMENTS_TOTAL.labels(
                tenant_id=tenant_label, status="success"
            ).inc()
        elif count == 0:
            BULK_APPOINTMENTS_TOTAL.labels(
                tenant_id=tenant_label, status="validation_error"
            ).inc()
            BULK_APPOINTMENTS_ERRORS.labels(
                tenant_id=tenant_label, status="validation_error"
            ).inc()
        else:
            BULK_APPOINTMENTS_TOTAL.labels(
                tenant_id=tenant_label, status="partial"
            ).inc()
        BULK_APPOINTMENTS_SIZE.labels(tenant_id=tenant_label).inc(count)

        logger.info(
            "Mixed bulk appointments processed",
            extra={
                "tenant_id": getattr(tenant, "id", None),
                "user_id": user.id,
                "appointments_count": count,
                "appointment_ids": [a.id for a in appointments],
                "total_value": total_value,
            },
        )

        # Enviar e-mail consolidado
        try:
            if count > 0:
                from core.email_utils import send_bulk_appointment_confirmation_email

                consolidated_items = [
                    {
                        "service_name": a.service.name,
                        "start_time": a.slot.start_time,
                        "professional_name": a.professional.name,
                        "appointment_id": a.id,
                    }
                    for a in appointments
                ]
                # Priorizar dados do cliente resolvido
                recipient_email = (
                    (customer.email if customer and customer.email else None)
                    or data.get("client_email")
                    or getattr(user, "email", "")
                )
                client_display_name = (
                    (customer.name if customer and customer.name else None)
                    or data.get("client_name")
                    or (getattr(user, "get_full_name", lambda: None)() or None)
                    or getattr(user, "username", None)
                    or (getattr(user, "email", "").split("@")[0])
                )
                send_bulk_appointment_confirmation_email(
                    to_email=recipient_email,
                    client_name=str(client_display_name or "Cliente"),
                    items=consolidated_items,
                    salon_name=(tenant.name if tenant else "TimelyOne"),
                )
        except Exception as e:  # pragma: no cover
            logger.warning(
                "Falha ao enviar e-mail consolidado (mixed)", extra={"error": str(e)}
            )

        message = (
            f"{count} agendamentos criados com sucesso"
            if count != 1
            else "1 agendamento criado com sucesso"
        )

        response_payload = {
            "success": count == len(item_list),
            "appointment_ids": [a.id for a in appointments],
            "appointments_created": count,
            "total_value": total_value,
            "results": results,
            "message": message,
        }

        if count == len(item_list):
            status_code = drf_status.HTTP_201_CREATED
        elif count == 0:
            status_code = drf_status.HTTP_400_BAD_REQUEST
        else:
            status_code = 207

        return Response(response_payload, status=status_code)


class AppointmentSeriesCreateView(TenantIsolatedMixin, APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=BulkAppointmentSerializer,
        responses={201: AppointmentSeriesCreateResponseSerializer},
    )
    def post(self, request):
        tenant = getattr(request.user, "tenant", None) or getattr(
            request, "tenant", None
        )
        serializer = BulkAppointmentSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=drf_status.HTTP_400_BAD_REQUEST)

        data = cast(Dict[str, Any], serializer.validated_data)
        user = request.user

        try:
            service = Service.objects.get(
                id=cast(int, data["service_id"]), tenant=tenant
            )
            professional = Professional.objects.get(
                id=cast(int, data["professional_id"]), tenant=tenant
            )
            staff_member = _get_staff_member(user)
            if _is_collaborator(user):
                allowed = professional.user_id == getattr(user, "id", None)
                if staff_member and professional.staff_member_id == staff_member.id:
                    allowed = True
                if not allowed:
                    raise PermissionDenied(
                        "Colaboradores só podem criar séries para si mesmos."
                    )
            customer = None
            customer_id = data.get("customer_id")
            if customer_id is not None:
                customer = SalonCustomer.objects.get(
                    id=cast(int, customer_id), tenant=tenant
                )
            elif tenant is not None:
                customer_email = data.get("client_email")
                customer_name = data.get("client_name") or "Cliente do salão"
                if customer_email:
                    customer = (
                        SalonCustomer.objects.filter(
                            tenant=tenant, email__iexact=customer_email
                        )
                        .order_by("id")
                        .first()
                    )
                if not customer:
                    customer = (
                        SalonCustomer.objects.filter(tenant=tenant)
                        .order_by("id")
                        .first()
                    )
                if not customer:
                    customer = SalonCustomer.objects.create(
                        tenant=tenant,
                        name=customer_name,
                        email=customer_email,
                        phone_number=data.get("client_phone") or "",
                        marketing_opt_in=True,
                        is_active=True,
                        notes="Gerado via criação de série de agendamentos.",
                    )

            appointments_list = cast(List[Dict[str, Any]], data["appointments"])
            slot_ids = [cast(int, a["slot_id"]) for a in appointments_list]
            slots = list(ScheduleSlot.objects.filter(id__in=slot_ids, tenant=tenant))

            with transaction.atomic():
                series = AppointmentSeries.objects.create(
                    tenant=tenant,
                    client=user,
                    service=service,
                    professional=professional,
                    notes=str(data.get("notes", "")),
                    recurrence_rule=None,
                )

                appointments = []
                for appt_data in appointments_list:
                    slot = next(s for s in slots if s.id == appt_data["slot_id"])
                    slot.mark_booked()
                    appointment = Appointment.objects.create(
                        client=user,
                        customer=customer,
                        service=service,
                        professional=professional,
                        slot=slot,
                        notes=str(appt_data.get("notes") or data.get("notes") or ""),
                        status="scheduled",
                        tenant=tenant,
                        series=series,
                    )
                    appointments.append(appointment)

                APPOINTMENT_SERIES_CREATED_TOTAL.labels(
                    tenant_id=getattr(tenant, "id", "unknown") or "unknown",
                    status="success",
                ).inc()
                APPOINTMENT_SERIES_SIZE_TOTAL.labels(
                    tenant_id=getattr(tenant, "id", "unknown") or "unknown",
                ).inc(len(appointments))

            from decimal import Decimal

            count = len(appointments)
            raw_unit = getattr(service, "price_eur", None)
            if raw_unit is None:
                raw_unit = getattr(service, "price", 0)
            try:
                unit_price = Decimal(str(raw_unit))
            except Exception:
                unit_price = Decimal("0")
            total_value = float(unit_price * count)

            serialized = AppointmentSerializer(
                appointments, many=True, context={"request": request}
            ).data

            # Envio de e-mail consolidado para o cliente da série
            try:
                count = len(appointments)
                if count > 0:
                    from core.email_utils import (
                        send_bulk_appointment_confirmation_email,
                    )

                    consolidated_items = [
                        {
                            "service_name": a.service.name,
                            "start_time": a.slot.start_time,
                            "professional_name": a.professional.name,
                            "appointment_id": a.id,
                        }
                        for a in appointments
                    ]
                    client_name = getattr(customer, "name", None) or str(
                        data.get("client_name") or getattr(user, "username", "Cliente")
                    )
                    to_email = (
                        getattr(customer, "email", None)
                        or data.get("client_email")
                        or getattr(user, "email", "")
                    )
                    if to_email:
                        send_bulk_appointment_confirmation_email(
                            to_email=to_email,
                            client_name=client_name,
                            items=consolidated_items,
                            salon_name=(tenant.name if tenant else "Salonix"),
                        )
            except Exception as e:  # pragma: no cover
                logger.warning(
                    "Falha ao enviar e-mail consolidado (series)",
                    extra={"error": str(e)},
                )

            return Response(
                {
                    "success": True,
                    "series_id": series.id,
                    "appointment_ids": [a.id for a in appointments],
                    "appointments_created": count,
                    "total_value": total_value,
                    "service_name": service.name,
                    "professional_name": professional.name,
                    "appointments": serialized,
                    "message": (
                        f"{count} agendamentos criados na série {series.id}"
                        if count != 1
                        else f"1 agendamento criado na série {series.id}"
                    ),
                },
                status=drf_status.HTTP_201_CREATED,
            )
        except PermissionDenied:
            raise
        except Exception as e:
            APPOINTMENT_SERIES_CREATED_TOTAL.labels(
                tenant_id=getattr(tenant, "id", "unknown") or "unknown",
                status="error",
            ).inc()
            logger.error(
                f"Series creation failed: {e}",
                exc_info=True,
                extra={
                    "tenant_id": getattr(tenant, "id", None),
                    "user_id": getattr(request.user, "id", None),
                },
            )
            return Response(
                {"detail": "Erro interno do servidor."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AppointmentSeriesDetailView(TenantIsolatedMixin, RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    queryset = AppointmentSeries.objects.all()
    serializer_class = AppointmentSeriesSerializer

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related(
                "tenant", "service", "professional__staff_member", "professional"
            )
        )
        user = self.request.user

        if user.is_superuser:
            return qs

        tenant = getattr(user, "tenant", None)
        if _is_owner_or_manager(user) and tenant:
            return qs.filter(tenant_id=tenant.id)

        base_filter = (
            Q(client=user) | Q(service__user=user) | Q(professional__user=user)
        )

        if _is_collaborator(user):
            staff_member = _get_staff_member(user)
            if staff_member:
                base_filter = (
                    Q(client=user)
                    | Q(professional__staff_member=staff_member)
                    | Q(professional__user=user)
                    | Q(service__user=user)
                )

        return qs.filter(base_filter)

    @extend_schema(
        request=AppointmentSeriesUpdateSerializer,
        responses={200: AppointmentSeriesUpdateResponseSerializer},
    )
    def patch(self, request, *args, **kwargs):
        series = self.get_object()
        tenant = getattr(request, "tenant", None) or series.tenant
        tenant_id_label = getattr(tenant, "id", "unknown") or "unknown"

        update_serializer = AppointmentSeriesUpdateSerializer(
            data=request.data,
            context={"request": request, "series": series, "tenant": tenant},
        )

        if not update_serializer.is_valid():
            action = request.data.get("action", "unknown")
            APPOINTMENT_SERIES_ERRORS_TOTAL.labels(
                tenant_id=tenant_id_label, action=action, error_type="validation_error"
            ).inc()
            return Response(
                update_serializer.errors, status=drf_status.HTTP_400_BAD_REQUEST
            )

        data = cast(Dict[str, Any], update_serializer.validated_data)
        action = cast(str, data["action"])
        start_from = (
            cast(Any, data.get("start_from")) or timezone.now()
        )  # atrasa para agora por padrão

        upcoming = list(
            series.appointments.filter(slot__start_time__gte=start_from)
            .select_related("slot")
            .order_by("slot__start_time")
        )

        try:
            with transaction.atomic():
                if action == "cancel_all":
                    payload = self._handle_cancel_all(
                        request=request,
                        series=series,
                        upcoming=upcoming,
                    )
                else:
                    payload = self._handle_edit_upcoming(
                        request=request,
                        series=series,
                        upcoming=upcoming,
                        data=data,
                        tenant=tenant,
                    )
        except ValidationError as exc:
            APPOINTMENT_SERIES_ERRORS_TOTAL.labels(
                tenant_id=tenant_id_label, action=action, error_type="validation_error"
            ).inc()
            detail = (
                getattr(exc, "detail", None)
                or exc.args
                or {
                    "detail": "Requisição inválida",
                }
            )
            return Response(detail, status=drf_status.HTTP_400_BAD_REQUEST)
        except Exception:  # pragma: no cover - guard para falhas imprevisíveis
            APPOINTMENT_SERIES_ERRORS_TOTAL.labels(
                tenant_id=tenant_id_label, action=action, error_type="exception"
            ).inc()
            logger.error(
                "appointment_series_patch_error",
                exc_info=True,
                extra={
                    "tenant_id": tenant_id_label,
                    "series_id": series.id,
                    "action": action,
                    "user_id": getattr(request.user, "id", None),
                },
            )
            return Response(
                {"detail": "Erro interno ao atualizar série."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        APPOINTMENT_SERIES_UPDATED_TOTAL.labels(
            tenant_id=tenant_id_label, action=action, status="success"
        ).inc()

        logger.info(
            "appointment_series_patch_success",
            extra={
                "tenant_id": tenant_id_label,
                "series_id": series.id,
                "action": action,
                "affected_count": payload.get("affected_count", 0),
            },
        )

        return Response(payload, status=drf_status.HTTP_200_OK)

    def _handle_cancel_all(
        self,
        *,
        request,
        series: AppointmentSeries,
        upcoming: List[Appointment],
    ) -> Dict[str, Any]:
        affected_ids: List[int] = []

        for appointment in upcoming:
            # Liberar slot independentemente do status atual
            if appointment.slot:
                appointment.slot.mark_available()
            # Libera também slots extras reservados para serviços longos
            _release_reserved_slots(appointment)

            if appointment.status != "cancelled":
                appointment.status = "cancelled"
                appointment.cancelled_by = request.user
                appointment.save(update_fields=["status", "cancelled_by"])

            affected_ids.append(appointment.id)

        message = (
            "Nenhum agendamento futuro encontrado para cancelar."
            if not affected_ids
            else f"{len(affected_ids)} agendamentos futuros cancelados."
        )

        return {
            "success": True,
            "series_id": series.id,
            "action": "cancel_all",
            "affected_count": len(affected_ids),
            "appointment_ids": affected_ids,
            "message": message,
        }

    def _handle_edit_upcoming(
        self,
        *,
        request,
        series: AppointmentSeries,
        upcoming: List[Appointment],
        data: Dict[str, Any],
        tenant,
    ) -> Dict[str, Any]:
        notes = data.get("notes")
        slot_ids = cast(Optional[List[int]], data.get("slot_ids"))

        if slot_ids:
            if len(slot_ids) != len(upcoming):
                raise ValidationError(
                    {
                        "slot_ids": [
                            "Quantidade de slots não corresponde aos agendamentos futuros."
                        ]
                    }
                )

            slots_qs = ScheduleSlot.objects.select_for_update().filter(
                id__in=slot_ids, tenant=tenant
            )
            slots_map = {slot.id: slot for slot in slots_qs}
            missing = [slot_id for slot_id in slot_ids if slot_id not in slots_map]
            if missing:
                raise ValidationError(
                    {"slot_ids": [f"Slots não encontrados: {missing}"]}
                )

            invalid_professional = [
                slot_id
                for slot_id, slot in slots_map.items()
                if slot.professional_id != series.professional_id
            ]
            if invalid_professional:
                raise ValidationError(
                    {
                        "slot_ids": [
                            "Todos os slots devem pertencer ao mesmo profissional da série."
                        ]
                    }
                )

        affected_ids: List[int] = []
        updated_notes = False

        if not upcoming:
            if notes is not None:
                series.notes = notes
                series.save(update_fields=["notes"])
                updated_notes = True

            return {
                "success": True,
                "series_id": series.id,
                "action": "edit_upcoming",
                "affected_count": 0,
                "appointment_ids": affected_ids,
                "message": "Nenhum agendamento futuro encontrado para atualizar.",
            }

        for idx, appointment in enumerate(upcoming):
            fields_to_update: List[str] = []

            if notes is not None:
                appointment.notes = notes
                fields_to_update.append("notes")
                updated_notes = True

            if slot_ids:
                desired_slot_id = slot_ids[idx]
                desired_slot = slots_map[desired_slot_id]

                if desired_slot_id != appointment.slot_id:
                    if (
                        desired_slot.is_available is False
                        or desired_slot.status != "available"
                    ):
                        raise ValidationError(
                            {
                                "slot_ids": [
                                    f"Slot {desired_slot_id} não está disponível."
                                ]
                            }
                        )

                    if desired_slot.start_time <= timezone.now():
                        raise ValidationError(
                            {"slot_ids": [f"Slot {desired_slot_id} está no passado."]}
                        )

                    # Encontrar bloco contínuo suficiente para a duração do serviço da série
                    duration = int(getattr(series.service, "duration_minutes", 0) or 0)
                    block = _find_contiguous_block_for(
                        tenant=tenant,
                        professional=series.professional,
                        start_slot=desired_slot,
                        required_minutes=duration,
                    )
                    if not block:
                        raise ValidationError(
                            {
                                "slot_ids": [
                                    f"Bloco contínuo indisponível para o slot {desired_slot_id}."
                                ]
                            }
                        )

                    # Libera slot antigo e quaisquer extras, reserva novo bloco contínuo
                    if appointment.slot:
                        appointment.slot.mark_available()
                    _release_reserved_slots(appointment)

                    for j, s in enumerate(block):
                        s.mark_booked()
                        if j > 0:
                            AppointmentReservedSlot.objects.create(
                                tenant=tenant,
                                appointment=appointment,
                                slot=s,
                            )

                    appointment.slot = block[0]
                    fields_to_update.append("slot")

            if fields_to_update:
                appointment.save(update_fields=list(set(fields_to_update)))

            affected_ids.append(appointment.id)

        if updated_notes:
            series.notes = notes
            series.save(update_fields=["notes"])

        message = (
            "Notas atualizadas para os agendamentos futuros."
            if notes is not None and not slot_ids
            else "Agendamentos futuros atualizados com sucesso."
        )

        return {
            "success": True,
            "series_id": series.id,
            "action": "edit_upcoming",
            "affected_count": len(affected_ids),
            "appointment_ids": affected_ids,
            "message": message,
        }


class AppointmentSeriesOccurrenceCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: AppointmentSeriesOccurrenceCancelResponseSerializer},
    )
    def post(self, request, series_id: int, occurrence_id: int):
        series = get_object_or_404(
            AppointmentSeries.objects.select_related("tenant"), pk=series_id
        )

        if not self._user_has_access(series, request.user):
            return Response(
                {
                    "detail": "Você não tem permissão para cancelar ocorrências desta série."
                },
                status=drf_status.HTTP_403_FORBIDDEN,
            )

        tenant = getattr(request, "tenant", None) or series.tenant
        tenant_id_label = getattr(tenant, "id", "unknown") or "unknown"

        appointment = get_object_or_404(
            Appointment.objects.select_related("slot", "tenant"),
            pk=occurrence_id,
            series=series,
        )

        if tenant and appointment.tenant_id != tenant.id:
            APPOINTMENT_SERIES_OCCURRENCE_CANCEL_TOTAL.labels(
                tenant_id=tenant_id_label, status="forbidden"
            ).inc()
            raise PermissionDenied("Agendamento não pertence ao seu tenant.")

        now = timezone.now()
        slot_start = getattr(appointment.slot, "start_time", None)
        if slot_start and slot_start <= now:
            APPOINTMENT_SERIES_OCCURRENCE_CANCEL_TOTAL.labels(
                tenant_id=tenant_id_label, status="invalid_past"
            ).inc()
            return Response(
                {"detail": "Não é possível cancelar ocorrências passadas."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        if appointment.status == "cancelled":
            APPOINTMENT_SERIES_OCCURRENCE_CANCEL_TOTAL.labels(
                tenant_id=tenant_id_label, status="already_cancelled"
            ).inc()
            return Response(
                {"detail": "Esta ocorrência já foi cancelada."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            if appointment.slot:
                appointment.slot.mark_available()
            # Libera slots extras vinculados
            _release_reserved_slots(appointment)
            appointment.status = "cancelled"
            appointment.cancelled_by = request.user
            appointment.save(update_fields=["status", "cancelled_by"])

        APPOINTMENT_SERIES_OCCURRENCE_CANCEL_TOTAL.labels(
            tenant_id=tenant_id_label, status="success"
        ).inc()

        logger.info(
            "appointment_series_occurrence_cancel_success",
            extra={
                "tenant_id": tenant_id_label,
                "series_id": series.id,
                "appointment_id": appointment.id,
                "user_id": getattr(request.user, "id", None),
            },
        )

        return Response(
            {
                "success": True,
                "series_id": series.id,
                "appointment_id": appointment.id,
                "message": "Ocorrência cancelada com sucesso.",
            },
            status=drf_status.HTTP_200_OK,
        )

    @staticmethod
    def _user_has_access(series: AppointmentSeries, user) -> bool:
        if user.is_superuser:
            return True
        if _is_owner_or_manager(user):
            tenant_id = getattr(series.tenant, "id", None) or series.tenant_id
            return tenant_id is not None and tenant_id == getattr(
                user, "tenant_id", None
            )

        if _is_collaborator(user):
            staff_member = _get_staff_member(user)
            if staff_member and series.professional.staff_member_id == staff_member.id:
                return True

        return (
            user == series.client
            or user == series.service.user
            or user == series.professional.user
        )


class AppointmentCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: AppointmentSerializer})
    def patch(self, request, pk):
        appointment = get_object_or_404(Appointment, pk=pk)

        if appointment.client != request.user:
            return Response(
                {"detail": "Você não tem permissão para cancelar este agendamento."},
                status=403,
            )

        if appointment.status == "cancelled":
            return Response(
                {"detail": "Este agendamento já foi cancelado."}, status=400
            )

        with cast(Any, transaction.atomic()):
            appointment.status = "cancelled"
            appointment.cancelled_by = request.user
            appointment.slot.mark_available()  # já salva o slot
            # Libera todos os slots extras reservados
            _release_reserved_slots(appointment)
            appointment.save()

        # E-mail para cliente e salão (não bloqueia a resposta)
        try:
            customer = appointment.customer
            client_email = (
                customer.email
                if customer and customer.email
                else appointment.client.email
            )
            client_name = (
                customer.name
                if customer and customer.name
                else (
                    appointment.client.get_full_name()
                    or appointment.client.username
                    or (appointment.client.email or "").split("@")[0]
                )
            )
            salon_email = appointment.professional.user.email
            if client_email:
                salon_name = (
                    appointment.tenant.name if appointment.tenant else "TimelyOne"
                )
                send_appointment_cancellation_email(
                    client_email=client_email,
                    salon_email=salon_email,
                    client_name=client_name,
                    service_name=appointment.service.name,
                    date_time=appointment.slot.start_time,
                    salon_name=salon_name,
                )
        except Exception:
            logger.error("Erro ao enviar e-mail de cancelamento", exc_info=True)

        logger.info(
            "Appointment cancelled successfully via View",
            extra={
                "appointment_id": appointment.id,
                "tenant_id": getattr(appointment.tenant, "id", None),
                "cancelled_by_id": request.user.id,
            },
        )

        serializer = AppointmentSerializer(appointment)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)


class ServiceViewSet(TenantIsolatedMixin, ModelViewSet):
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Filtrar por tenant (TenantIsolatedMixin cuida do escopo) e opcionalmente por professional_id
        qs = super().get_queryset()
        professional_id = self.request.query_params.get("professional_id")
        if professional_id and str(professional_id).isdigit():
            tenant = getattr(self.request, "tenant", None) or getattr(
                self.request.user, "tenant", None
            )
            if tenant:
                links = ProfessionalService.objects.filter(
                    tenant=tenant, professional_id=int(professional_id), is_active=True
                ).values_list("service_id", flat=True)
                qs = qs.filter(id__in=list(links))
        return qs

    def perform_create(self, serializer):
        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        if tenant is None:
            slug = self.request.headers.get(
                "X-Tenant-Slug"
            ) or self.request.query_params.get("tenant")
            if slug:
                try:
                    tenant = Tenant.objects.get(slug=slug, is_active=True)
                except Tenant.DoesNotExist:
                    tenant = None
        if tenant is None and not self.request.user.is_superuser:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"tenant": ["Tenant não encontrado para o usuário."]})

        if not (
            self.request.user.is_superuser
            or self.request.user.has_staff_role(
                TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
            )
        ):
            raise PermissionDenied("Apenas owner ou manager podem criar serviços.")

        serializer.save(user=self.request.user, tenant=tenant)

        logger.info(
            "Service created successfully",
            extra={
                "service_id": serializer.instance.id,
                "tenant_id": getattr(tenant, "id", None),
                "user_id": self.request.user.id,
                "service_name": serializer.instance.name,
            },
        )

    def perform_update(self, serializer):
        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        serializer.save()

        logger.info(
            "Service updated successfully",
            extra={
                "service_id": serializer.instance.id,
                "tenant_id": getattr(tenant, "id", None),
                "user_id": self.request.user.id,
                "updated_fields": list(self.request.data.keys()),
            },
        )

    def get_object(self):
        obj = get_object_or_404(
            Service, pk=self.kwargs.get(self.lookup_field, self.kwargs.get("pk"))
        )
        if self.request.user.is_superuser:
            return obj

        if self.request.method not in SAFE_METHODS:
            if not (
                self.request.user.has_staff_role(
                    TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
                )
            ):
                if obj.user_id != self.request.user.id:
                    raise PermissionDenied(
                        "Apenas owner/manager ou o responsável pelo serviço podem alterar."
                    )

        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        if tenant and hasattr(obj, "tenant"):
            if obj.tenant_id != tenant.id:
                raise PermissionDenied(
                    "Acesso negado: objeto não pertence ao seu tenant"
                )
        return obj


class ClientAccessLinkView(TenantIsolatedMixin, APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UsersClientAccessLinkThrottle]
    throttle_scope = "clients_access_link"

    @extend_schema(
        request=ClientAccessLinkRequestSerializer,
        responses={200: OpenApiTypes.OBJECT},
        description="Emite link/token de acesso para cliente (PWA).",
    )
    def post(self, request):
        user = request.user
        tenant = getattr(user, "tenant", None) or getattr(request, "tenant", None)
        if tenant is None:
            raise ValidationError("Tenant não encontrado para o usuário autenticado.")

        role = getattr(user, "staff_role", None)
        if role not in (TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER):
            raise PermissionDenied("Somente OWNER/MANAGER podem emitir link de acesso.")

        serializer = ClientAccessLinkRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        customer_id = int(data["customer_id"])
        try:
            customer = SalonCustomer.objects.get(id=customer_id, tenant=tenant)
        except SalonCustomer.DoesNotExist:
            raise ValidationError("Cliente não encontrado para este tenant.")

        to_email = (customer.email or "").strip()
        if not to_email:
            return Response(
                {
                    "detail": "E-mail do cliente ausente. Atualize o cadastro e tente novamente."
                },
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        # Gerar token/link (uso único por jti)
        payload, token, link = create_client_access_data(tenant, customer)

        try:
            send_customer_pwa_invite(
                tenant=tenant, customer=customer, invited_by=user, link=link
            )
        except Exception:
            CLIENT_ACCESS_EVENTS_TOTAL.labels(
                event="emit_staff",
                result="failure",
                tenant_id=str(tenant.id),
            ).inc()
        else:
            CLIENT_ACCESS_EVENTS_TOTAL.labels(
                event="emit_staff",
                result="success",
                tenant_id=str(tenant.id),
            ).inc()

        return Response(
            {"access_link_sent": True, "customer_id": customer.id, "access_link": link},
            status=drf_status.HTTP_200_OK,
        )


class PublicClientAccessLinkView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [UsersClientAccessLinkThrottle]
    throttle_scope = "clients_access_link"

    @extend_schema(
        request=PublicClientAccessLinkRequestSerializer,
        responses={
            200: OpenApiResponse(response=OpenApiTypes.OBJECT),
            400: OpenApiResponse(response=OpenApiTypes.OBJECT),
        },
        examples=[
            OpenApiExample(
                name="Request",
                description="Solicitação de envio de link",
                value={
                    "tenant_slug": "beleza-top",
                    "email": "ana@example.com",
                    "captcha_token": "dev-bypass",
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Sucesso",
                value={"access_link_requested": True},
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                name="Captcha inválido",
                value={"detail": "Captcha inválido."},
                response_only=True,
                status_codes=["400"],
            ),
        ],
        description="Solicita envio de link de acesso (self-service) para cliente via e-mail.",
    )
    def post(self, request):
        try:
            enforce_captcha_or_raise(request)
        except ValidationError:
            return Response(
                {"detail": "Captcha inválido."}, status=drf_status.HTTP_400_BAD_REQUEST
            )

        serializer = PublicClientAccessLinkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant_slug = (data.get("tenant_slug") or "").strip().lower()
        email = data["email"].strip().lower()

        resp = Response({"access_link_requested": True}, status=drf_status.HTTP_200_OK)

        tenant = None
        customer = None
        if tenant_slug:
            try:
                tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
            except Tenant.DoesNotExist:
                CLIENT_ACCESS_EVENTS_TOTAL.labels(
                    event="emit_public",
                    result="tenant_not_found",
                    tenant_id=str(0),
                ).inc()
                return resp
        else:
            possible = SalonCustomer.objects.select_related("tenant").filter(
                email__iexact=email, tenant__is_active=True
            )
            matches = [c for c in possible if c.tenant.can_use_pwa_client()]
            if len(matches) == 0:
                CLIENT_ACCESS_EVENTS_TOTAL.labels(
                    event="emit_public",
                    result="customer_not_found",
                    tenant_id=str(0),
                ).inc()
                return resp
            if len(matches) > 1:
                CLIENT_ACCESS_EVENTS_TOTAL.labels(
                    event="emit_public",
                    result="ambiguous",
                    tenant_id=str(0),
                ).inc()
                return resp
            customer = matches[0]
            tenant = customer.tenant

        if not tenant.can_use_pwa_client():
            return resp

        if customer is None:
            try:
                customer = SalonCustomer.objects.get(tenant=tenant, email__iexact=email)
            except SalonCustomer.DoesNotExist:
                CLIENT_ACCESS_EVENTS_TOTAL.labels(
                    event="emit_public",
                    result="customer_not_found",
                    tenant_id=str(tenant.id),
                ).inc()
                return resp

        if not (customer.email or "").strip():
            return resp

        # Gerar token/link (uso único por jti) e logar em dev
        payload, token, link = create_client_access_data(tenant, customer)

        security_logger = logging.getLogger("users.security")
        env_name = getattr(settings, "ENV_NAME", "dev")
        if getattr(settings, "DEBUG", False) or env_name == "dev":
            security_logger.info(
                f"Client access link (dev): {link} | email={email}",
                extra={
                    "event": "client_access_link",
                    "email": email,
                    "link": link,
                    "tenant_id": tenant.id,
                },
            )

        try:
            send_customer_pwa_invite(
                tenant=tenant, customer=customer, invited_by=None, link=link
            )
        except Exception:
            CLIENT_ACCESS_EVENTS_TOTAL.labels(
                event="emit_public",
                result="failure",
                tenant_id=str(tenant.id),
            ).inc()
        else:
            CLIENT_ACCESS_EVENTS_TOTAL.labels(
                event="emit_public",
                result="success",
                tenant_id=str(tenant.id),
            ).inc()

        return resp


class ClientAccessAcceptView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [UsersClientAccessLinkThrottle]
    throttle_scope = "clients_access_link"

    @extend_schema(
        request=ClientAccessAcceptSerializer,
        responses={
            200: OpenApiResponse(response=OpenApiTypes.OBJECT),
            400: OpenApiResponse(response=OpenApiTypes.OBJECT),
        },
        examples=[
            OpenApiExample(
                name="Request",
                description="Aceitar convite com token",
                value={"token": "<token-assinado>"},
                request_only=True,
            ),
            OpenApiExample(
                name="Sessão criada",
                value={
                    "session": "created",
                    "tenant_id": 1,
                    "customer_id": 42,
                    "has_password": False,
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                name="Token inválido",
                value={"detail": "Token inválido"},
                response_only=True,
                status_codes=["400"],
            ),
            OpenApiExample(
                name="Token expirado",
                value={"detail": "Token expirado"},
                response_only=True,
                status_codes=["400"],
            ),
        ],
        description="Aceita link/token de acesso do cliente e cria sessão.",
    )
    def post(self, request):
        serializer = ClientAccessAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw = serializer.validated_data["token"]
        try:
            payload = signing.loads(raw, salt="CLIENT_PWA_INVITE_SALT")
        except signing.BadSignature:
            CLIENT_ACCESS_EVENTS_TOTAL.labels(
                event="accept",
                result="bad_signature",
                tenant_id=str(0),
            ).inc()
            raise ValidationError("Token inválido")

        tenant_id = int(payload.get("tenant_id"))
        customer_id = int(payload.get("customer_id"))
        ts = int(payload.get("ts", 0))
        jti = str(payload.get("jti", ""))

        ttl = getattr(settings, "CLIENT_PWA_INVITE_TTL_SECONDS", 15 * 60)
        if int(timezone.now().timestamp()) - ts > ttl:
            CLIENT_ACCESS_EVENTS_TOTAL.labels(
                event="accept",
                result="expired",
                tenant_id=str(tenant_id),
            ).inc()
            raise ValidationError("Token expirado")

        # Uso único do token por jti com Grace Period (para evitar erros em redirects/previews)
        if not jti:
            CLIENT_ACCESS_EVENTS_TOTAL.labels(
                event="accept",
                result="missing_jti",
                tenant_id=str(tenant_id),
            ).inc()
            raise ValidationError("Token inválido")

        remaining = ttl - (int(timezone.now().timestamp()) - ts)
        if remaining < 0:
            remaining = 0

        cache_key = f"client_invite_jti:{tenant_id}:{customer_id}:{jti}"

        # Verificar contador de usos no cache
        use_count = cache.get(cache_key, 0)

        # Permitir até 2 usos do token
        if use_count >= 2:
            CLIENT_ACCESS_EVENTS_TOTAL.labels(
                event="accept",
                result="reused",
                tenant_id=str(tenant_id),
            ).inc()
            raise ValidationError("Token já utilizado")

        # Incrementar contador de usos
        cache.set(cache_key, use_count + 1, timeout=remaining or ttl)

        # Verificar existência
        try:
            tenant = Tenant.objects.get(id=tenant_id, is_active=True)
        except Tenant.DoesNotExist:
            CLIENT_ACCESS_EVENTS_TOTAL.labels(
                event="accept",
                result="tenant_not_found",
                tenant_id=str(tenant_id),
            ).inc()
            raise ValidationError("Tenant inválido")

        try:
            customer = SalonCustomer.objects.get(id=customer_id, tenant=tenant)
        except SalonCustomer.DoesNotExist:
            CLIENT_ACCESS_EVENTS_TOTAL.labels(
                event="accept",
                result="customer_not_found",
                tenant_id=str(tenant_id),
            ).inc()
            raise ValidationError("Cliente inválido")

        # Criar tokens JWT para cliente
        tokens = _create_client_jwt_tokens(tenant, customer)

        CLIENT_ACCESS_EVENTS_TOTAL.labels(
            event="accept",
            result="success",
            tenant_id=str(tenant.id),
        ).inc()

        # Adicionar informação se cliente já tem senha
        tokens["has_password"] = bool(customer.password)

        return Response(tokens, status=drf_status.HTTP_200_OK)


class ClientLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [UsersClientAccessLinkThrottle]

    @extend_schema(
        request=ClientLoginSerializer,
        responses={200: OpenApiTypes.OBJECT},
        description="Login de cliente via email/senha. Retorna tokens JWT (access + refresh).",
    )
    def post(self, request):
        serializer = ClientLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant_slug = data["tenant_slug"]
        email = data["email"]
        password = data["password"]

        try:
            tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant inválido.")

        if not tenant.can_use_pwa_client():
            raise ValidationError("Funcionalidade indisponível para este tenant.")

        try:
            customer = SalonCustomer.objects.get(
                tenant=tenant, email=email, is_active=True
            )
        except SalonCustomer.DoesNotExist:
            raise ValidationError("Credenciais inválidas.")

        if not customer.password:
            raise ValidationError(
                "Cliente não possui senha definida. Use o link de acesso mágico."
            )

        if not customer.check_password(password):
            raise ValidationError("Credenciais inválidas.")

        # Criar tokens JWT para cliente
        tokens = _create_client_jwt_tokens(tenant, customer)

        return Response(tokens, status=drf_status.HTTP_200_OK)


class ClientTokenRefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request={"refresh": OpenApiTypes.STR},
        responses={200: OpenApiTypes.OBJECT},
        description="Renova access token de cliente usando refresh token.",
    )
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            raise ValidationError("Refresh token é obrigatório")

        try:
            from rest_framework_simplejwt.tokens import RefreshToken

            refresh = RefreshToken(refresh_token)

            # Verificar se é token de cliente
            scope = refresh.get("scope")
            if scope != "client":
                raise ValidationError("Token não é de cliente")

            tenant_id = refresh.get("tenant_id")
            customer_id = refresh.get("customer_id")

            if not tenant_id or not customer_id:
                raise ValidationError("Token inválido: dados ausentes")

            # Validar se tenant e customer ainda existem
            try:
                tenant = Tenant.objects.get(id=tenant_id, is_active=True)
                customer = SalonCustomer.objects.get(
                    id=customer_id, tenant=tenant, is_active=True
                )
            except (Tenant.DoesNotExist, SalonCustomer.DoesNotExist):
                raise ValidationError("Tenant ou cliente inválido")

            # Sessao deslizante: rotaciona o refresh (novo jti + janela de
            # REFRESH_TOKEN_LIFETIME renovada), preservando os claims de cliente
            # (scope/tenant_id/customer_id). Espelha o comportamento do staff
            # (ROTATE_REFRESH_TOKENS) e do Ops, que tambem rodam a cada refresh.
            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()

            # Gerar novo access token
            access_token = refresh.access_token
            access_token["scope"] = "client"
            access_token["tenant_id"] = str(tenant.id)
            access_token["tenant_slug"] = tenant.slug
            access_token["customer_id"] = customer.id

            return Response(
                {"access": str(access_token), "refresh": str(refresh)},
                status=drf_status.HTTP_200_OK,
            )
        except Exception as e:
            raise ValidationError(f"Token inválido: {str(e)}")


class ClientSetPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # No auto-authentication, we handle JWT manually

    @extend_schema(
        request=ClientSetPasswordSerializer,
        responses={200: OpenApiTypes.OBJECT},
        description="Define senha para o cliente autenticado via JWT.",
    )
    def post(self, request):
        tenant, customer = _get_client_from_jwt(request)

        serializer = ClientSetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer.set_password(serializer.validated_data["password"])
        customer.save()

        return Response({"status": "password_set"}, status=drf_status.HTTP_200_OK)


class ClientsMeAppointmentsUpcomingView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # No auto-authentication, we handle JWT manually

    @extend_schema(responses={200: AppointmentDetailSerializer(many=True)})
    def get(self, request):
        tenant, customer = _get_client_from_jwt(request)
        now = timezone.now()
        qs = (
            Appointment.objects.filter(
                tenant=tenant,
                customer=customer,
                slot__start_time__gte=now,
                status="scheduled",
            )
            .select_related("slot", "service", "professional")
            .order_by("slot__start_time")
        )
        ser = AppointmentDetailSerializer(qs, many=True)
        return Response(ser.data, status=drf_status.HTTP_200_OK)


class ClientsMeAppointmentsHistoryView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # No auto-authentication, we handle JWT manually

    @extend_schema(responses={200: AppointmentDetailSerializer(many=True)})
    def get(self, request):
        tenant, customer = _get_client_from_jwt(request)
        now = timezone.now()
        qs = (
            Appointment.objects.filter(
                tenant=tenant,
                customer=customer,
                slot__start_time__lt=now,
                status__in=["completed", "paid", "cancelled"],
            )
            .select_related("slot", "service", "professional")
            .order_by("-slot__start_time")
        )
        ser = AppointmentDetailSerializer(qs, many=True)
        return Response(ser.data, status=drf_status.HTTP_200_OK)


class ClientsMeAppointmentCreateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # No auto-authentication, we handle JWT manually
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "clients_me_appointments_create"

    @extend_schema(
        request=AppointmentSerializer, responses={201: AppointmentDetailSerializer}
    )
    def post(self, request):
        tenant, customer = _get_client_from_jwt(request)

        raw = request.data or {}
        try:
            service_id = int(raw.get("service") or raw.get("service_id") or 0)
            professional_id = int(
                raw.get("professional") or raw.get("professional_id") or 0
            )
            slot_id = int(raw.get("slot") or raw.get("slot_id") or 0)
        except Exception:
            raise ValidationError({"detail": "Parâmetros inválidos."})
        notes = str(raw.get("notes") or "")

        with transaction.atomic():
            service = get_object_or_404(Service, pk=service_id, tenant=tenant)
            professional = get_object_or_404(
                Professional, pk=professional_id, tenant=tenant
            )
            slot = get_object_or_404(
                ScheduleSlot.objects.select_for_update(), pk=slot_id, tenant=tenant
            )

            if slot.professional_id != professional.id:
                raise ValidationError(
                    {"slot": ["Slot não pertence ao profissional informado."]}
                )
            if slot.start_time <= timezone.now():
                raise ValidationError(
                    {"slot": ["Não é possível agendar horários no passado."]}
                )
            if (not slot.is_available) or (slot.status != "available"):
                raise ValidationError(
                    {"slot": ["Este horário já foi agendado ou não está disponível."]}
                )

            if not ProfessionalService.objects.filter(
                tenant=tenant,
                professional=professional,
                service=service,
                is_active=True,
            ).exists():
                raise ValidationError(
                    {"service": ["Profissional não atende este serviço."]}
                )

            owner = TenantStaffMember.objects.filter(
                tenant=tenant, role=TenantStaffMember.Role.OWNER
            ).first()
            client_user = getattr(owner, "user", None)
            if client_user is None:
                manager = TenantStaffMember.objects.filter(
                    tenant=tenant, role=TenantStaffMember.Role.MANAGER
                ).first()
                client_user = getattr(manager, "user", None)
            if client_user is None:
                raise ValidationError(
                    "Tenant sem responsável cadastrado para vincular o agendamento."
                )

            duration = int(getattr(service, "duration_minutes", 0) or 0)
            slot_minutes = int((slot.end_time - slot.start_time).total_seconds() // 60)
            extra_slots: list[ScheduleSlot] = []

            if duration > slot_minutes:
                block = _find_contiguous_block_for(
                    tenant=tenant,
                    professional=professional,
                    start_slot=slot,
                    required_minutes=duration,
                )
                total_minutes = sum(
                    int((s.end_time - s.start_time).total_seconds() // 60)
                    for s in block
                )
                if not block or total_minutes < duration:
                    raise ValidationError(
                        {
                            "slot": [
                                "Não há slots suficientes para a duração do serviço."
                            ]
                        }
                    )
                for s in block[1:]:
                    if (not s.is_available) or (s.status != "available"):
                        raise ValidationError(
                            {"slot": ["Bloco contíguo de slots indisponível."]}
                        )
                for s in block[1:]:
                    s.mark_booked()
                    extra_slots.append(s)

            slot.mark_booked()
            appointment = Appointment.objects.create(
                tenant=tenant,
                client=client_user,
                customer=customer,
                service=service,
                professional=professional,
                slot=slot,
                notes=notes,
                status="scheduled",
            )
            for s in extra_slots:
                AppointmentReservedSlot.objects.create(
                    tenant=tenant, appointment=appointment, slot=s
                )

        try:
            to_email = (customer.email or "").strip()
            if to_email:
                client_name = customer.name or "Cliente"
                salon_name = tenant.name or "TimelyOne"
                send_appointment_confirmation_email(
                    to_email=to_email,
                    client_name=client_name,
                    service_name=service.name,
                    date_time=slot.start_time,
                    salon_name=salon_name,
                    appointment_id=appointment.id,
                )
        except Exception as e:
            logger.warning(
                "Falha ao enviar e-mail de confirmação (cliente)",
                extra={"error": str(e)},
            )

        ser = AppointmentDetailSerializer(appointment)
        return Response(ser.data, status=drf_status.HTTP_201_CREATED)


class ClientsMeProfileView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # No auto-authentication, we handle JWT manually

    @extend_schema(responses={200: SalonCustomerSerializer})
    def get(self, request):
        _, customer = _get_client_from_jwt(request)
        ser = SalonCustomerSerializer(customer)
        return Response(ser.data, status=drf_status.HTTP_200_OK)

    @extend_schema(
        request=SalonCustomerSerializer, responses={200: SalonCustomerSerializer}
    )
    def patch(self, request):
        tenant, customer = _get_client_from_jwt(request)
        allowed = {
            "name",
            "phone_number",
            "photo",
            "birthday",
            "notes",
            "marketing_opt_in",
        }
        data = {k: v for k, v in request.data.items() if k in allowed}
        ser = SalonCustomerSerializer(customer, data=data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save(tenant=tenant)
        return Response(ser.data, status=drf_status.HTTP_200_OK)


class ClientAppointmentCancelView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # No auto-authentication, we handle JWT manually

    @extend_schema(request=None, responses={200: AppointmentSerializer})
    def patch(self, request, pk: int):
        tenant, customer = _get_client_from_jwt(request)
        appt = get_object_or_404(
            Appointment.objects.select_related("slot", "tenant"),
            pk=pk,
            tenant=tenant,
            customer=customer,
        )

        now = timezone.now()
        slot_start = getattr(appt.slot, "start_time", None)
        if slot_start and slot_start <= now:
            return Response(
                {"detail": "Não é possível cancelar agendamentos passados."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        if appt.status == "cancelled":
            return Response(
                {"detail": "Este agendamento já foi cancelado."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            if appt.slot:
                appt.slot.mark_available()
            _release_reserved_slots(appt)
            appt.status = "cancelled"
            appt.cancelled_by = None
            appt.save(update_fields=["status", "cancelled_by"])

        ser = AppointmentSerializer(appt)
        return Response(ser.data, status=drf_status.HTTP_200_OK)

    def get_object(self):
        # Busca direta por PK e valida tenant explicitamente (evita filtros indevidos no queryset)
        obj = get_object_or_404(
            Service, pk=self.kwargs.get(self.lookup_field, self.kwargs.get("pk"))
        )
        if self.request.user.is_superuser:
            return obj

        if self.request.method not in SAFE_METHODS:
            if not (
                self.request.user.has_staff_role(
                    TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
                )
            ):
                if obj.user_id != self.request.user.id:
                    raise PermissionDenied(
                        "Apenas owner/manager ou o responsável pelo serviço podem alterar."
                    )

        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        if tenant and hasattr(obj, "tenant"):
            if obj.tenant_id != tenant.id:
                raise PermissionDenied(
                    "Acesso negado: objeto não pertence ao seu tenant"
                )
        return obj


class ProfessionalViewSet(TenantIsolatedMixin, ModelViewSet):
    queryset = Professional.objects.all()
    serializer_class = ProfessionalSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        # Filtro opcional por service_id
        service_id = self.request.query_params.get("service_id")
        if service_id and str(service_id).isdigit():
            tenant = getattr(self.request, "tenant", None) or getattr(
                self.request.user, "tenant", None
            )
            if tenant:
                links = ProfessionalService.objects.filter(
                    tenant=tenant, service_id=int(service_id), is_active=True
                ).values_list("professional_id", flat=True)
                qs = qs.filter(id__in=list(links))
        user = self.request.user
        if user.is_superuser or user.has_staff_role(
            TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
        ):
            return qs

        if user.has_staff_role(TenantStaffMember.Role.COLLABORATOR):
            staff_member = getattr(user, "staff_member", None)
            if staff_member:
                return qs.filter(staff_member=staff_member)
            return qs.none()

        return qs.filter(user=user)

    def perform_create(self, serializer):
        staff_member = serializer.validated_data.get("staff_member")
        user = self.request.user

        if staff_member is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"staff_member": ["Selecione um membro de equipe responsável."]}
            )

        if user.has_staff_role(TenantStaffMember.Role.COLLABORATOR):
            requester_staff = getattr(user, "staff_member", None)
            if not requester_staff:
                raise PermissionDenied("Colaborador não possui staff associado.")
            if staff_member.id != requester_staff.id:
                raise PermissionDenied(
                    "Colaborador não pode criar profissional para outro membro."
                )
        elif not (
            user.is_superuser
            or user.has_staff_role(
                TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
            )
        ):
            raise PermissionDenied("Apenas owner ou manager podem criar profissionais.")

        tenant = staff_member.tenant
        current_tenant = getattr(self.request, "tenant", None)
        if (
            not user.is_superuser
            and current_tenant is not None
            and tenant.id != current_tenant.id
        ):
            raise PermissionDenied("Staff informado não pertence ao tenant atual.")

        serializer.save(
            user=staff_member.user,
            tenant=tenant,
            staff_member=staff_member,
        )
        logger.info(
            "Professional created successfully",
            extra={
                "professional_id": serializer.instance.id,
                "tenant_id": getattr(tenant, "id", None),
                "user_id": self.request.user.id,
                "professional_name": serializer.instance.name,
            },
        )

    def get_object(self):
        obj = get_object_or_404(
            Professional, pk=self.kwargs.get(self.lookup_field, self.kwargs.get("pk"))
        )
        if self.request.user.is_superuser:
            return obj
        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        if tenant and hasattr(obj, "tenant"):
            if obj.tenant_id != tenant.id:
                raise PermissionDenied(
                    "Acesso negado: objeto não pertence ao seu tenant"
                )

        if self.request.user.has_staff_role(TenantStaffMember.Role.COLLABORATOR):
            staff_member = getattr(self.request.user, "staff_member", None)
            if not staff_member or obj.staff_member_id != staff_member.id:
                raise PermissionDenied("Você só pode acessar o seu próprio perfil.")
        return obj

    def perform_update(self, serializer):
        instance = serializer.instance
        self._ensure_update_allowed(instance)
        staff_member = serializer.validated_data.get(
            "staff_member", instance.staff_member
        )
        user = self.request.user

        if user.has_staff_role(TenantStaffMember.Role.COLLABORATOR):
            staff_member = getattr(user, "staff_member", None)
            if not staff_member or instance.staff_member_id != staff_member.id:
                raise PermissionDenied(
                    "Colaborador não pode alterar outro profissional."
                )
        elif staff_member and staff_member.tenant_id != instance.tenant_id:
            raise PermissionDenied("Staff informado não pertence ao tenant.")

        if staff_member is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"staff_member": ["Profissional deve estar associado a um staff."]}
            )

        serializer.save(
            staff_member=staff_member,
            user=staff_member.user,
            tenant=staff_member.tenant,
        )
        logger.info(
            "Professional updated successfully",
            extra={
                "professional_id": serializer.instance.id,
                "tenant_id": getattr(serializer.instance.tenant, "id", None),
                "user_id": self.request.user.id,
                "updated_fields": list(self.request.data.keys()),
            },
        )

    def perform_destroy(self, instance):
        self._ensure_update_allowed(instance)
        super().perform_destroy(instance)

    def _ensure_update_allowed(self, instance: Professional):
        user = self.request.user
        if user.is_superuser or user.has_staff_role(
            TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
        ):
            return
        staff_member = getattr(user, "staff_member", None)
        if not staff_member or instance.staff_member_id != staff_member.id:
            raise PermissionDenied("Você não possui permissão para esta operação.")


class SalonCustomerViewSet(TenantIsolatedMixin, ModelViewSet):
    queryset = SalonCustomer.objects.all().select_related("tenant")
    serializer_class = SalonCustomerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if not getattr(self.request, "tenant", None) and getattr(
            self.request.user, "tenant", None
        ):
            self.request.tenant = self.request.user.tenant

        qs = super().get_queryset()
        params = self.request.query_params
        search = params.get("q")
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone_number__icontains=search)
            )
        is_active = params.get("is_active")
        if is_active is not None:
            is_active_bool = str(is_active).lower() in {"1", "true", "t", "yes", "y"}
            qs = qs.filter(is_active=is_active_bool)
        return qs.order_by("name", "id")

    def perform_create(self, serializer):
        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        if tenant is None and not self.request.user.is_superuser:
            raise ValidationError(
                {"tenant": ["Tenant não encontrado para o usuário autenticado."]}
            )
        customer = serializer.save(tenant=tenant)

        if (
            tenant
            and tenant.auto_invite_enabled
            and tenant.pwa_client_enabled
            and customer.email
        ):
            try:
                send_customer_pwa_invite(
                    tenant=tenant,
                    customer=customer,
                    invited_by=self.request.user,
                )
            except Exception:  # pragma: no cover
                logger.error(
                    "Auto invite dispatch failed",
                    exc_info=True,
                    extra={
                        "tenant_id": tenant.id,
                        "customer_id": customer.id,
                        "user_id": getattr(self.request.user, "id", None),
                    },
                )

    def perform_update(self, serializer):
        serializer.save(tenant=serializer.instance.tenant)

    def get_object(self):
        obj = super().get_object()
        if self.request.user.is_superuser:
            return obj
        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        if tenant and obj.tenant_id != tenant.id:
            raise PermissionDenied("Acesso negado: cliente não pertence ao seu tenant.")
        return obj

    def destroy(self, request, *args, **kwargs):
        self.get_object()
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Clientes com histórico de agendamentos não podem ser excluídos. "
                        "Defina como inativo para mantê-lo fora da agenda."
                    )
                },
                status=drf_status.HTTP_409_CONFLICT,
            )

    @action(detail=True, methods=["post"], url_path="invite")
    def invite(self, request, pk=None):
        customer = self.get_object()
        tenant = getattr(request, "tenant", None) or getattr(
            request.user, "tenant", None
        )

        if tenant is None:
            return Response(
                {"detail": "Tenant não identificado para o usuário autenticado."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        if not tenant.pwa_client_enabled:
            return Response(
                {
                    "detail": "PWA Cliente não habilitado para este salão. Atualize o plano para reenviar convites."
                },
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        if not customer.email:
            return Response(
                {
                    "detail": "Cliente não possui e-mail cadastrado. Informe um e-mail antes de reenviar o convite."
                },
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        try:
            send_customer_pwa_invite(
                tenant=tenant,
                customer=customer,
                invited_by=request.user,
            )
        except Exception:  # pragma: no cover - logging crítico
            logger.error(
                "Falha ao reenviar convite do PWA",
                exc_info=True,
                extra={
                    "tenant_id": getattr(tenant, "id", None),
                    "customer_id": customer.id,
                    "user_id": getattr(request.user, "id", None),
                },
            )
            return Response(
                {"detail": "Erro ao reenviar convite. Tente novamente mais tarde."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"status": "queued"}, status=drf_status.HTTP_202_ACCEPTED)


_import_logger = logging.getLogger("core.import")


def _reject_csv(reason: str, extra: dict) -> None:
    """Logs a structured rejection event and increments the Prometheus counter."""
    CSV_IMPORT_REJECTIONS_TOTAL.labels(reason=reason).inc()
    _import_logger.warning(
        "csv_import_rejected",
        extra={"reason": reason, **extra},
    )


class ImportCSVBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def _require_owner(self, request):
        if not request.user.has_staff_role(TenantStaffMember.Role.OWNER):
            raise PermissionDenied("Apenas owner pode importar dados.")

    def _get_tenant(self, request):
        return getattr(request, "tenant", None) or getattr(request.user, "tenant", None)

    def _parse_bool(self, value):
        return str(value).lower() in {"1", "true", "t", "yes", "y"}

    _CSV_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
    _CSV_MAX_ROWS = 5_000
    _CSV_ALLOWED_CONTENT_TYPES = frozenset({
        "text/csv", "text/plain", "application/csv",
        "application/octet-stream",  # common browser fallback for .csv
    })
    # Signatures of binary formats that must never be accepted as CSV
    _BINARY_MAGIC_BYTES = (
        b"\x50\x4b\x03\x04",  # ZIP / xlsx / docx
        b"\xd0\xcf\x11\xe0",  # OLE2 / xls / doc
        b"\x89\x50\x4e\x47",  # PNG
        b"\xff\xd8\xff",       # JPEG
        b"\x25\x50\x44\x46",  # PDF
    )

    def _log_ctx(self, request) -> dict:
        tenant = self._get_tenant(request)
        return {
            "tenant_id": getattr(tenant, "id", None),
            "user_id": getattr(request.user, "id", None),
            "view": self.__class__.__name__,
        }

    def _validate_csv_file(self, f, log_ctx: dict) -> None:
        import os
        ext = os.path.splitext(f.name or "")[1].lower()
        if ext not in (".csv", ".txt", ""):
            _reject_csv("invalid_extension", {**log_ctx, "ext": ext})
            raise ValidationError({"file": ["Apenas arquivos .csv são aceitos."]})
        mime = (f.content_type or "").split(";")[0].strip().lower()
        if mime and mime not in self._CSV_ALLOWED_CONTENT_TYPES:
            _reject_csv("invalid_mime_type", {**log_ctx, "mime": mime})
            raise ValidationError({"file": [f"Tipo de arquivo '{mime}' não é permitido. Envie um CSV."]})

    def _read_csv(self, request):
        f = request.FILES.get("file")
        if not f:
            raise ValidationError({"file": ["Arquivo CSV obrigatório."]})
        ctx = self._log_ctx(request)
        self._validate_csv_file(f, ctx)
        if f.size > self._CSV_MAX_BYTES:
            _reject_csv("file_too_large", {**ctx, "size_bytes": f.size})
            raise ValidationError(
                {"file": [f"Arquivo CSV excede o limite de {self._CSV_MAX_BYTES // (1024 * 1024)} MB."]}
            )
        raw = f.read(self._CSV_MAX_BYTES + 1)
        if len(raw) > self._CSV_MAX_BYTES:
            _reject_csv("file_too_large", {**ctx, "size_bytes": len(raw)})
            raise ValidationError(
                {"file": [f"Arquivo CSV excede o limite de {self._CSV_MAX_BYTES // (1024 * 1024)} MB."]}
            )
        # Reject files whose first bytes match known binary formats
        for magic in self._BINARY_MAGIC_BYTES:
            if raw.startswith(magic):
                _reject_csv("binary_content", {**ctx, "magic_prefix": raw[:4].hex()})
                raise ValidationError({"file": ["Formato de arquivo inválido. Envie um CSV em texto plano."]})
        # Strip UTF-8 BOM if present, then require valid UTF-8
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            _reject_csv("encoding_error", ctx)
            raise ValidationError({"file": ["Arquivo CSV deve estar em UTF-8."]})
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        if len(rows) > self._CSV_MAX_ROWS:
            _reject_csv("too_many_rows", {**ctx, "row_count": len(rows)})
            raise ValidationError(
                {"file": [f"CSV excede o limite de {self._CSV_MAX_ROWS} linhas. Divida o arquivo e reimporte."]}
            )
        return rows


class ExportCSVBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def _require_owner(self, request):
        if not request.user.has_staff_role(TenantStaffMember.Role.OWNER):
            raise PermissionDenied("Apenas owner pode exportar dados.")

    def _get_tenant(self, request):
        header_slug = request.headers.get("X-Tenant-Slug")
        user_tenant = getattr(request.user, "tenant", None)
        if header_slug:
            try:
                tenant = Tenant.objects.get(slug=header_slug, is_active=True)
            except Tenant.DoesNotExist:
                raise ValidationError(
                    {"tenant": ["Tenant especificado no header inválido"]}
                )
            if (
                user_tenant
                and tenant.id != user_tenant.id
                and not getattr(request.user, "is_superuser", False)
            ):
                raise PermissionDenied(
                    "Tenant do header não corresponde ao seu tenant."
                )
            return tenant
        return getattr(request, "tenant", None) or user_tenant


class ExportCustomersCSVView(TenantIsolatedMixin, ExportCSVBaseView):
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "export_csv"

    @extend_schema(
        tags=["Export"],
        parameters=[
            OpenApiParameter(
                name="updated_since",
                type=OpenApiTypes.DATETIME,
                required=False,
                location="query",
                description="Exportar registros com updated_at >= valor",
            ),
            OpenApiParameter(
                name="active",
                type=OpenApiTypes.BOOL,
                required=False,
                location="query",
                description="Filtrar clientes ativos (is_active=true)",
            ),
            OpenApiParameter(
                name="X-Tenant-Slug",
                type=OpenApiTypes.STR,
                required=False,
                location="header",
                description="Slug do tenant (opcional, deve corresponder ao do usuário)",
            ),
        ],
        responses={200: OpenApiTypes.BINARY},
    )
    def get(self, request):
        self._require_owner(request)
        tenant = self._get_tenant(request)
        qs = SalonCustomer.objects.filter(tenant=tenant)
        updated_since = request.query_params.get("updated_since")
        if updated_since:
            dt = parse_datetime(updated_since)
            if not dt:
                d = parse_date(updated_since)
                if d:
                    from datetime import datetime, time as dt_time

                    dt = timezone.make_aware(datetime.combine(d, dt_time.min))
            if dt:
                qs = qs.filter(updated_at__gte=dt)
        active = request.query_params.get("active")
        if active is not None:
            val = str(active).lower() in {"1", "true", "t", "yes", "y"}
            qs = qs.filter(is_active=val)

        qs = qs.order_by("name", "id")

        def _iter():
            yield ",".join(["name", "email", "phone"]) + "\n"
            for c in qs.iterator():
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow([c.name, c.email or "", c.phone_number or ""])
                yield buf.getvalue()

        resp = StreamingHttpResponse(_iter(), content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=customers-export.csv"
        logging.getLogger(__name__).info(
            "csv_export_customers",
            extra={
                "request_id": getattr(request, "request_id", "-"),
                "tenant_id": getattr(tenant, "id", None),
                "count": qs.count(),
            },
        )
        return resp


class ExportServicesCSVView(TenantIsolatedMixin, ExportCSVBaseView):
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "export_csv"

    @extend_schema(
        tags=["Export"],
        parameters=[
            OpenApiParameter(
                name="X-Tenant-Slug",
                type=OpenApiTypes.STR,
                required=False,
                location="header",
                description="Slug do tenant (opcional, deve corresponder ao do usuário)",
            ),
        ],
        responses={200: OpenApiTypes.BINARY},
    )
    def get(self, request):
        self._require_owner(request)
        tenant = self._get_tenant(request)
        qs = Service.objects.filter(tenant=tenant).order_by("name", "id")

        def _iter():
            yield ",".join(["name", "duration_minutes", "price_eur"]) + "\n"
            for s in qs.iterator():
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow([s.name, int(s.duration_minutes), str(s.price_eur)])
                yield buf.getvalue()

        resp = StreamingHttpResponse(_iter(), content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=services-export.csv"
        logging.getLogger(__name__).info(
            "csv_export_services",
            extra={
                "request_id": getattr(request, "request_id", "-"),
                "tenant_id": getattr(tenant, "id", None),
                "count": qs.count(),
            },
        )
        return resp


class ExportStaffCSVView(TenantIsolatedMixin, ExportCSVBaseView):
    throttle_classes = (PerUserScopedRateThrottle,)
    throttle_scope = "export_csv"

    @extend_schema(
        tags=["Export"],
        parameters=[
            OpenApiParameter(
                name="updated_since",
                type=OpenApiTypes.DATETIME,
                required=False,
                location="query",
                description="Exportar registros com updated_at >= valor",
            ),
            OpenApiParameter(
                name="active",
                type=OpenApiTypes.BOOL,
                required=False,
                location="query",
                description="Filtrar membros ativos (status=active)",
            ),
            OpenApiParameter(
                name="X-Tenant-Slug",
                type=OpenApiTypes.STR,
                required=False,
                location="header",
                description="Slug do tenant (opcional, deve corresponder ao do usuário)",
            ),
        ],
        responses={200: OpenApiTypes.BINARY},
    )
    def get(self, request):
        self._require_owner(request)
        tenant = self._get_tenant(request)
        qs = TenantStaffMember.objects.filter(tenant=tenant).select_related("user")
        updated_since = request.query_params.get("updated_since")
        if updated_since:
            dt = parse_datetime(updated_since)
            if not dt:
                d = parse_date(updated_since)
                if d:
                    from datetime import datetime, time as dt_time

                    dt = timezone.make_aware(datetime.combine(d, dt_time.min))
            if dt:
                qs = qs.filter(updated_at__gte=dt)
        active = request.query_params.get("active")
        if active is not None:
            val = str(active).lower() in {"1", "true", "t", "yes", "y"}
            qs = qs.filter(
                status=(
                    TenantStaffMember.Status.ACTIVE
                    if val
                    else TenantStaffMember.Status.DISABLED
                )
            )
        qs = qs.order_by("id")

        def _iter():
            yield ",".join(["name", "email", "role"]) + "\n"
            for staff in qs.iterator():
                user = getattr(staff, "user", None)
                full_name = None
                if user is not None:
                    try:
                        full_name = user.get_full_name()
                    except Exception:
                        full_name = None
                name_val = (
                    full_name
                    or getattr(user, "first_name", "")
                    or getattr(user, "username", "")
                ).strip()
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow([name_val, getattr(user, "email", ""), staff.role])
                yield buf.getvalue()

        resp = StreamingHttpResponse(_iter(), content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=staff-export.csv"
        logging.getLogger(__name__).info(
            "csv_export_staff",
            extra={
                "request_id": getattr(request, "request_id", "-"),
                "tenant_id": getattr(tenant, "id", None),
                "count": qs.count(),
            },
        )
        return resp


class ImportCustomersCSVView(TenantIsolatedMixin, ImportCSVBaseView):
    @extend_schema(
        tags=["Import"],
        parameters=[
            OpenApiParameter(
                name="dry_run",
                type=OpenApiTypes.BOOL,
                required=False,
                location="query",
                description="Valida sem gravar quando true",
            )
        ],
        request={
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {"file": {"type": "string", "format": "binary"}},
                    "required": ["file"],
                }
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "example": "customers"},
                    "summary": {
                        "type": "object",
                        "properties": {
                            "processed": {"type": "integer"},
                            "created": {"type": "integer"},
                            "updated": {"type": "integer"},
                            "skipped": {"type": "integer"},
                            "errors": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "line": {"type": "integer"},
                                        "error": {"type": "string"},
                                        "row": {"type": "object"},
                                    },
                                },
                            },
                        },
                    },
                },
            }
        },
    )
    def post(self, request):
        self._require_owner(request)
        tenant = self._get_tenant(request)
        dry_run = self._parse_bool(request.query_params.get("dry_run", "false"))
        rows = self._read_csv(request)
        processed = 0
        created = 0
        updated = 0
        skipped = 0
        errors = []
        for idx, row in enumerate(rows, start=2):
            processed += 1
            name = sanitize_text_input((row.get("name") or "").strip())
            email = (row.get("email") or "").strip().lower() or None
            phone = (row.get("phone") or "").strip() or None
            if phone:
                try:
                    validate_phone_number(phone)
                except Exception:
                    errors.append({"line": idx, "error": "phone inválido", "row": row})
                    skipped += 1
                    continue
            if not name:
                errors.append({"line": idx, "error": "name obrigatório", "row": row})
                skipped += 1
                continue
            existing = None
            if email:
                existing = SalonCustomer.objects.filter(
                    tenant=tenant, email__iexact=email
                ).first()
            if not existing and phone:
                existing = SalonCustomer.objects.filter(
                    tenant=tenant, phone_number=phone
                ).first()
            if dry_run:
                if existing:
                    updated += 1
                else:
                    created += 1
                continue
            if existing:
                changed = False
                if existing.name != name:
                    existing.name = name
                    changed = True
                if email and existing.email != email:
                    existing.email = email
                    changed = True
                if phone and existing.phone_number != phone:
                    existing.phone_number = phone
                    changed = True
                if changed:
                    existing.save(
                        update_fields=["name", "email", "phone_number", "updated_at"]
                    )
                    updated += 1
                else:
                    skipped += 1
            else:
                SalonCustomer.objects.create(
                    tenant=tenant,
                    name=name,
                    email=email or None,
                    phone_number=phone or None,
                )
                created += 1
        return Response(
            {
                "entity": "customers",
                "summary": {
                    "processed": processed,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                    "errors": errors,
                },
            }
        )


class ImportServicesCSVView(TenantIsolatedMixin, ImportCSVBaseView):
    @extend_schema(
        tags=["Import"],
        parameters=[
            OpenApiParameter(
                name="dry_run",
                type=OpenApiTypes.BOOL,
                required=False,
                location="query",
                description="Valida sem gravar quando true",
            )
        ],
        request={
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {"file": {"type": "string", "format": "binary"}},
                    "required": ["file"],
                }
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "example": "services"},
                    "summary": {
                        "type": "object",
                        "properties": {
                            "processed": {"type": "integer"},
                            "created": {"type": "integer"},
                            "updated": {"type": "integer"},
                            "skipped": {"type": "integer"},
                            "errors": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "line": {"type": "integer"},
                                        "error": {"type": "string"},
                                        "row": {"type": "object"},
                                    },
                                },
                            },
                        },
                    },
                },
            }
        },
    )
    def post(self, request):
        self._require_owner(request)
        tenant = self._get_tenant(request)
        dry_run = self._parse_bool(request.query_params.get("dry_run", "false"))
        rows = self._read_csv(request)
        processed = 0
        created = 0
        updated = 0
        skipped = 0
        errors = []
        for idx, row in enumerate(rows, start=2):
            processed += 1
            name = sanitize_text_input((row.get("name") or "").strip())
            duration_val = (row.get("duration_minutes") or "").strip()
            price_val = (row.get("price_eur") or "").strip()
            if not name or not duration_val or not price_val:
                errors.append(
                    {"line": idx, "error": "campos obrigatórios ausentes", "row": row}
                )
                skipped += 1
                continue
            try:
                duration = int(duration_val)
            except Exception:
                errors.append({"line": idx, "error": "duration inválido", "row": row})
                skipped += 1
                continue
            try:
                from decimal import Decimal

                price = Decimal(price_val)
            except Exception:
                errors.append({"line": idx, "error": "price inválido", "row": row})
                skipped += 1
                continue
            existing = Service.objects.filter(
                tenant=tenant, name__iexact=name, duration_minutes=duration
            ).first()
            if dry_run:
                if existing:
                    updated += 1
                else:
                    created += 1
                continue
            if existing:
                changed = False
                if existing.price_eur != price:
                    existing.price_eur = price
                    changed = True
                if changed:
                    (
                        existing.save(update_fields=["price_eur", "updated_at"])
                        if hasattr(existing, "updated_at")
                        else existing.save()
                    )
                    updated += 1
                else:
                    skipped += 1
            else:
                Service.objects.create(
                    tenant=tenant,
                    user=request.user,
                    name=name,
                    duration_minutes=duration,
                    price_eur=price,
                )
                created += 1
        return Response(
            {
                "entity": "services",
                "summary": {
                    "processed": processed,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                    "errors": errors,
                },
            }
        )


class ImportStaffCSVView(TenantIsolatedMixin, ImportCSVBaseView):
    @extend_schema(
        tags=["Import"],
        parameters=[
            OpenApiParameter(
                name="dry_run",
                type=OpenApiTypes.BOOL,
                required=False,
                location="query",
                description="Valida sem gravar quando true",
            )
        ],
        request={
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {"file": {"type": "string", "format": "binary"}},
                    "required": ["file"],
                }
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "example": "staff"},
                    "summary": {
                        "type": "object",
                        "properties": {
                            "processed": {"type": "integer"},
                            "created": {"type": "integer"},
                            "updated": {"type": "integer"},
                            "skipped": {"type": "integer"},
                            "errors": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "line": {"type": "integer"},
                                        "error": {"type": "string"},
                                        "row": {"type": "object"},
                                    },
                                },
                            },
                        },
                    },
                },
            }
        },
    )
    def post(self, request):
        self._require_owner(request)
        tenant = self._get_tenant(request)
        dry_run = self._parse_bool(request.query_params.get("dry_run", "false"))
        rows = self._read_csv(request)
        processed = 0
        created = 0
        updated = 0
        skipped = 0
        errors = []
        for idx, row in enumerate(rows, start=2):
            processed += 1
            name = sanitize_text_input((row.get("name") or "").strip())
            email = (row.get("email") or "").strip().lower()
            role = (row.get("role") or "collaborator").strip().lower()
            if not email:
                errors.append({"line": idx, "error": "email obrigatório", "row": row})
                skipped += 1
                continue
            if role not in {
                TenantStaffMember.Role.OWNER,
                TenantStaffMember.Role.MANAGER,
                TenantStaffMember.Role.COLLABORATOR,
            }:
                errors.append({"line": idx, "error": "role inválido", "row": row})
                skipped += 1
                continue
            staff = (
                TenantStaffMember.objects.filter(
                    tenant=tenant, user__email__iexact=email
                )
                .select_related("user")
                .first()
            )
            if dry_run:
                if staff:
                    updated += 1
                else:
                    created += 1
                continue
            if staff:
                changed = False
                if staff.role != role:
                    staff.role = role
                    changed = True
                if changed:
                    (
                        staff.save(update_fields=["role", "updated_at"])
                        if hasattr(staff, "updated_at")
                        else staff.save()
                    )
                    updated += 1
                else:
                    skipped += 1
            else:
                user = CustomUser.objects.filter(email__iexact=email).first()
                if not user:
                    username_seed = (name or email.split("@")[0] or "user")[:150]
                    unique_suffix = secrets.token_hex(3)
                    username = f"{username_seed}-{unique_suffix}"[:150]
                    user = CustomUser.objects.create(
                        username=username,
                        email=email,
                        first_name=(name or "").split(" ")[0],
                    )
                TenantStaffMember.objects.create(
                    tenant=tenant,
                    user=user,
                    role=role,
                    status=TenantStaffMember.Status.INVITED,
                    invited_by=request.user,
                )
                created += 1
        return Response(
            {
                "entity": "staff",
                "summary": {
                    "processed": processed,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                    "errors": errors,
                },
            }
        )


class ImportAppointmentsCSVView(TenantIsolatedMixin, ImportCSVBaseView):
    @extend_schema(
        tags=["Import"],
        parameters=[
            OpenApiParameter(
                name="dry_run",
                type=OpenApiTypes.BOOL,
                required=False,
                location="query",
                description="Valida sem gravar quando true",
            )
        ],
        request={
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {"file": {"type": "string", "format": "binary"}},
                    "required": ["file"],
                }
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "example": "appointments"},
                    "summary": {
                        "type": "object",
                        "properties": {
                            "processed": {"type": "integer"},
                            "created": {"type": "integer"},
                            "updated": {"type": "integer"},
                            "skipped": {"type": "integer"},
                            "errors": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "line": {"type": "integer"},
                                        "error": {"type": "string"},
                                        "row": {"type": "object"},
                                    },
                                },
                            },
                        },
                    },
                },
            }
        },
    )
    def post(self, request):
        self._require_owner(request)
        tenant = self._get_tenant(request)
        dry_run = self._parse_bool(request.query_params.get("dry_run", "false"))
        rows = self._read_csv(request)
        processed = 0
        created = 0
        updated = 0
        skipped = 0
        errors = []

        for idx, row in enumerate(rows, start=2):
            processed += 1
            customer_email = (
                (row.get("customer_email") or row.get("email") or "").strip().lower()
            )
            customer_phone = (
                row.get("customer_phone") or row.get("phone") or ""
            ).strip()
            service_name = (row.get("service_name") or row.get("service") or "").strip()
            professional_name = (
                row.get("professional_name") or row.get("professional") or ""
            ).strip()
            start_dt_str = (row.get("start_datetime") or row.get("start") or "").strip()
            duration_val = (
                row.get("duration_minutes") or row.get("duration") or ""
            ).strip()

            if not (
                service_name
                and professional_name
                and start_dt_str
                and (customer_email or customer_phone)
            ):
                errors.append(
                    {"line": idx, "error": "campos obrigatórios ausentes", "row": row}
                )
                skipped += 1
                continue

            dt = parse_datetime(start_dt_str)
            if dt is None:
                errors.append(
                    {"line": idx, "error": "start_datetime inválido", "row": row}
                )
                skipped += 1
                continue
            try:
                from zoneinfo import ZoneInfo

                tz_name = getattr(tenant, "timezone", None) or "UTC"
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo(tz_name))
            except Exception:
                errors.append({"line": idx, "error": "timezone inválida", "row": row})
                skipped += 1
                continue

            customer = None
            if customer_email:
                customer = SalonCustomer.objects.filter(
                    tenant=tenant, email__iexact=customer_email
                ).first()
            if customer is None and customer_phone:
                customer = SalonCustomer.objects.filter(
                    tenant=tenant, phone_number=customer_phone
                ).first()
            if customer is None:
                errors.append(
                    {"line": idx, "error": "cliente não encontrado", "row": row}
                )
                skipped += 1
                continue

            service = Service.objects.filter(
                tenant=tenant, name__iexact=service_name
            ).first()
            professional = Professional.objects.filter(
                tenant=tenant, name__iexact=professional_name
            ).first()
            if not service or not professional:
                errors.append(
                    {
                        "line": idx,
                        "error": "serviço/profissional não encontrado",
                        "row": row,
                    }
                )
                skipped += 1
                continue

            slot = ScheduleSlot.objects.filter(
                tenant=tenant,
                professional=professional,
                start_time=dt,
            ).first()
            if slot is None:
                errors.append({"line": idx, "error": "slot não encontrado", "row": row})
                skipped += 1
                continue
            if not slot.is_available:
                errors.append({"line": idx, "error": "slot indisponível", "row": row})
                skipped += 1
                continue

            use_duration = None
            if duration_val:
                try:
                    use_duration = int(duration_val)
                except Exception:
                    errors.append(
                        {"line": idx, "error": "duration_minutes inválido", "row": row}
                    )
                    skipped += 1
                    continue
            else:
                use_duration = service.duration_minutes

            slot_minutes = int((slot.end_time - slot.start_time).total_seconds() // 60)
            if use_duration > slot_minutes:
                errors.append(
                    {"line": idx, "error": "duração maior que o slot", "row": row}
                )
                skipped += 1
                continue

            existing = None
            if slot:
                existing = Appointment.objects.filter(
                    tenant=tenant,
                    customer=customer,
                    service=service,
                    professional=professional,
                    slot=slot,
                ).first()

            if dry_run:
                if existing:
                    updated += 1
                else:
                    created += 1
                continue

            if existing:
                skipped += 1
            else:
                notes_val = sanitize_text_input(str(row.get("notes") or ""), max_length=1000)
                slot.mark_booked()
                Appointment.objects.create(
                    client=request.user,
                    service=service,
                    professional=professional,
                    slot=slot,
                    notes=notes_val,
                    status="scheduled",
                    tenant=tenant,
                    customer=customer,
                )
                created += 1

        payload = {
            "entity": "appointments",
            "summary": {
                "processed": processed,
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "errors": errors,
            },
            "request_id": getattr(request, "request_id", None),
        }
        try:
            import_logger = logging.getLogger("core.import")
            import_logger.info(
                "import.appointments",
                extra={
                    "tenant_id": getattr(tenant, "id", None),
                    "tenant_slug": getattr(tenant, "slug", None),
                    "request_id": getattr(request, "request_id", None),
                    "processed": processed,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                    "errors_count": len(errors),
                },
            )
        except Exception:
            pass
        return Response(payload)


class ImportTemplateCSVView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(tags=["Import"], responses={200: OpenApiTypes.BINARY})
    def get(self, request, entity):
        if entity not in {"customers", "services", "staff", "appointments"}:
            return Response(
                {"detail": "template não disponível"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )
        output = io.StringIO()
        writer = csv.writer(output)
        if entity == "customers":
            writer.writerow(["name", "email", "phone"])
        elif entity == "services":
            writer.writerow(["name", "duration_minutes", "price_eur"])
        elif entity == "staff":
            writer.writerow(["name", "email", "role"])
        else:  # appointments
            writer.writerow(
                [
                    "customer_email",
                    "customer_phone",
                    "service_name",
                    "professional_name",
                    "start_datetime",
                    "duration_minutes",
                    "notes",
                ]
            )
        response = StreamingHttpResponse(
            iter([output.getvalue()]), content_type="text/csv"
        )
        response["Content-Disposition"] = f"attachment; filename={entity}-template.csv"
        return response


class ScheduleSlotViewSet(TenantIsolatedMixin, ModelViewSet):
    queryset = ScheduleSlot.objects.all()
    serializer_class = ScheduleSlotSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [OrderingFilter]
    ordering_fields = ["start_time", "end_time", "created_at", "id"]
    ordering = ["-start_time"]

    def get_queryset(self):
        # Garantir que request.tenant esteja definido para o mixin, usando o tenant do usuário autenticado
        if not getattr(self.request, "tenant", None) and getattr(
            self.request.user, "tenant", None
        ):
            self.request.tenant = self.request.user.tenant

        qs = super().get_queryset()
        user = self.request.user
        if user.has_staff_role(TenantStaffMember.Role.COLLABORATOR):
            staff_member = getattr(user, "staff_member", None)
            if staff_member:
                qs = qs.filter(professional__staff_member=staff_member)
            else:
                qs = qs.none()
        params = self.request.query_params
        professional_id = params.get("professional_id")
        if professional_id:
            qs = qs.filter(professional_id=professional_id)
        is_available = params.get("is_available")
        if is_available is not None:
            val = str(is_available).lower() in {"1", "true", "t", "yes", "y"}
            qs = qs.filter(is_available=val)

        date_from = params.get("date_from")
        date_to = params.get("date_to")
        if date_from:
            qs = qs.filter(start_time__gte=date_from)
        if date_to:
            qs = qs.filter(start_time__lte=date_to)

        return qs

    def perform_create(self, serializer):
        # Sempre usar o tenant do usuário do salão
        tenant = getattr(self.request.user, "tenant", None)
        if tenant is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"tenant": ["Usuário sem tenant. Não é possível criar slot."]}
            )

        validated = getattr(serializer, "validated_data", {}) or {}
        professional = validated.get("professional")
        if professional is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"professional": ["Profissional é obrigatório."]})
        if hasattr(professional, "tenant_id") and professional.tenant_id != tenant.id:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"professional": ["Profissional não pertence ao tenant atual."]}
            )

        user = self.request.user
        if user.has_staff_role(TenantStaffMember.Role.COLLABORATOR):
            staff_member = getattr(user, "staff_member", None)
            if not staff_member or professional.staff_member_id != staff_member.id:
                raise PermissionDenied(
                    "Colaboradores só podem criar slots para si mesmos."
                )
        elif not (
            user.is_superuser
            or user.has_staff_role(
                TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
            )
        ):
            raise PermissionDenied("Permissão insuficiente para criar slots.")

        serializer.save(tenant=tenant)

    @action(detail=False, methods=["post"], url_path="bulk-generate")
    def bulk_generate(self, request):
        """
        POST /api/slots/bulk-generate/

        Gera slots em bulk para um profissional dentro do horário de funcionamento.

        Body: { professional_id, period ("day"|"week"|"month"), interval_minutes (default 30), date (YYYY-MM-DD, default hoje) }
        Retorna: { created: N, skipped: M }
        """
        import zoneinfo
        from datetime import date as date_type, datetime, timedelta

        user = request.user
        tenant = getattr(user, "tenant", None)
        if not tenant:
            raise ValidationError("Usuário sem tenant.")

        if not (
            user.is_superuser
            or user.has_staff_role(TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER)
        ):
            raise PermissionDenied("Apenas owner ou manager podem gerar slots em bulk.")

        professional_id = request.data.get("professional_id")
        period = request.data.get("period")
        interval_minutes = request.data.get("interval_minutes", 30)
        date_str = request.data.get("date")

        if not professional_id:
            raise ValidationError({"professional_id": "Campo obrigatório."})
        if period not in ("day", "week", "month"):
            raise ValidationError({"period": "Deve ser 'day', 'week' ou 'month'."})
        try:
            interval_minutes = int(interval_minutes)
        except (TypeError, ValueError):
            raise ValidationError({"interval_minutes": "Deve ser um número inteiro."})
        if not (15 <= interval_minutes <= 480):
            raise ValidationError({"interval_minutes": "Deve ser entre 15 e 480 minutos."})

        try:
            professional = Professional.objects.get(id=professional_id, tenant=tenant)
        except Professional.DoesNotExist:
            raise ValidationError({"professional_id": "Profissional não encontrado para este tenant."})

        tz = zoneinfo.ZoneInfo(tenant.timezone or "Europe/Lisbon")
        if date_str:
            try:
                base_date = date_type.fromisoformat(str(date_str))
            except ValueError:
                raise ValidationError({"date": "Data inválida. Use formato YYYY-MM-DD."})
        else:
            base_date = datetime.now(tz).date()

        if period == "day":
            dates = [base_date]
        elif period == "week":
            monday = base_date - timedelta(days=base_date.weekday())
            dates = [monday + timedelta(days=i) for i in range(7)]
        else:
            first = base_date.replace(day=1)
            if first.month == 12:
                last = first.replace(year=first.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                last = first.replace(month=first.month + 1, day=1) - timedelta(days=1)
            dates = [first + timedelta(days=i) for i in range((last - first).days + 1)]

        bh_qs = TenantBusinessHours.objects.filter(tenant=tenant, is_active=True)
        if not bh_qs.exists():
            raise ValidationError(
                "Tenant não possui horário de funcionamento configurado. "
                "Configure em Configurações > Horário de funcionamento."
            )
        bh_by_day = {bh.day_of_week: bh for bh in bh_qs}

        period_start = datetime.combine(dates[0], datetime.min.time()).replace(tzinfo=tz)
        period_end = datetime.combine(dates[-1], datetime.max.time()).replace(tzinfo=tz)
        existing_starts = set(
            ScheduleSlot.objects.filter(
                tenant=tenant,
                professional=professional,
                start_time__gte=period_start,
                start_time__lte=period_end,
            ).values_list("start_time", flat=True)
        )

        interval = timedelta(minutes=interval_minutes)
        slots_to_create = []
        skipped_count = 0
        pending_starts = set()

        for day in dates:
            bh = bh_by_day.get(day.weekday())
            if not bh:
                continue
            current = datetime.combine(day, bh.start_time).replace(tzinfo=tz)
            end_dt = datetime.combine(day, bh.end_time).replace(tzinfo=tz)
            while current + interval <= end_dt:
                slot_end = current + interval
                if current in existing_starts or current in pending_starts:
                    skipped_count += 1
                else:
                    slots_to_create.append(ScheduleSlot(
                        tenant=tenant,
                        professional=professional,
                        start_time=current,
                        end_time=slot_end,
                        is_available=True,
                        status="available",
                    ))
                    pending_starts.add(current)
                current += interval

        if slots_to_create:
            ScheduleSlot.objects.bulk_create(slots_to_create)

        return Response({"created": len(slots_to_create), "skipped": skipped_count})

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()  # get_object valida o tenant via mixin/checagem
        obj.delete()
        return Response(status=drf_status.HTTP_204_NO_CONTENT)

    def perform_update(self, serializer):
        obj = serializer.instance
        tenant = getattr(self.request.user, "tenant", None)
        professional = serializer.validated_data.get("professional", obj.professional)
        if professional.tenant_id != tenant.id:
            raise PermissionDenied("Profissional não pertence ao tenant.")

        user = self.request.user
        if user.has_staff_role(TenantStaffMember.Role.COLLABORATOR):
            staff_member = getattr(user, "staff_member", None)
            if not staff_member or professional.staff_member_id != staff_member.id:
                raise PermissionDenied(
                    "Colaborador só pode alterar seus próprios slots."
                )

        serializer.save()

    def get_object(self):
        obj = get_object_or_404(
            ScheduleSlot, pk=self.kwargs.get(self.lookup_field, self.kwargs.get("pk"))
        )
        if self.request.user.is_superuser:
            return obj
        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        if tenant and hasattr(obj, "tenant"):
            if obj.tenant_id != tenant.id:
                raise PermissionDenied(
                    "Acesso negado: objeto não pertence ao seu tenant"
                )
        if self.request.user.has_staff_role(TenantStaffMember.Role.COLLABORATOR):
            staff_member = getattr(self.request.user, "staff_member", None)
            if not staff_member or obj.professional.staff_member_id != staff_member.id:
                raise PermissionDenied(
                    "Colaboradores só podem acessar seus próprios slots."
                )
        return obj


class SalonAppointmentViewSet(TenantIsolatedMixin, ModelViewSet):
    """
    Endpoints para o SALÃO visualizar e editar seus agendamentos.
    - list/retrieve: vê apenas agendamentos do próprio salão
      (match por professional.user == request.user OU service.user == request.user)
    - update/partial_update: permite editar SOMENTE o campo 'notes'
      (cancelamento continua pelo endpoint específico de cancelamento).
    - destroy: opcionalmente podemos permitir apagar; por padrão vou desabilitar abaixo.
    """

    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated, IsSalonOwnerOfAppointment]

    def get_queryset(self):
        user = self.request.user

        if getattr(self.request, "tenant", None) is None:
            tenant_from_user = getattr(user, "tenant", None)
            if tenant_from_user is not None:
                self.request.tenant = tenant_from_user

        qs = (
            super()
            .get_queryset()
            .select_related("client", "customer", "service", "professional", "slot")
        )

        if not (
            user.is_superuser
            or user.has_staff_role(
                TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
            )
        ):
            qs = qs.filter(Q(professional__user=user) | Q(service__user=user))

        qs = qs.order_by("-created_at")

        params = self.request.query_params

        # status
        status_value = cast(Optional[str], params.get("status"))
        if status_value in {"scheduled", "cancelled", "completed", "paid"}:
            qs = qs.filter(status=status_value)

        # -------- datas --------
        date_from_raw = cast(Optional[str], params.get("date_from"))
        date_to_raw = cast(Optional[str], params.get("date_to"))

        def is_plain_date(s: str | None) -> bool:
            return bool(s) and ("T" not in s) and (":" not in s)

        # date_from
        if is_plain_date(date_from_raw):
            d = parse_date(cast(str, date_from_raw))
            if d:
                qs = qs.filter(slot__start_time__date__gte=d)
        elif date_from_raw:
            dt = parse_datetime(cast(str, date_from_raw))
            if dt is None:
                raise ValidationError({"date_from": "Formato inválido."})
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            qs = qs.filter(slot__start_time__gte=dt)

        # date_to
        if is_plain_date(date_to_raw):
            d = parse_date(cast(str, date_to_raw))
            if d:
                qs = qs.filter(slot__start_time__date__lte=d)
        elif date_to_raw:
            dt = parse_datetime(cast(str, date_to_raw))
            if dt is None:
                raise ValidationError({"date_to": "Formato inválido."})
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            qs = qs.filter(slot__start_time__lte=dt)

        # professional_id / service_id
        professional_id = cast(Optional[str], params.get("professional_id"))
        if professional_id:
            qs = qs.filter(professional_id=professional_id)

        service_id = cast(Optional[str], params.get("service_id"))
        if service_id:
            qs = qs.filter(service_id=service_id)

        customer_id = cast(Optional[str], params.get("customer_id"))
        if customer_id:
            qs = qs.filter(customer_id=customer_id)

        # ordering
        ordering = cast(Optional[str], params.get("ordering"))
        if ordering in {"created_at", "-created_at"}:
            qs = qs.order_by(ordering)
        elif ordering in {"slot_time", "-slot_time"}:
            qs = qs.order_by(
                "slot__start_time" if ordering == "slot_time" else "-slot__start_time"
            )
        elif ordering in {"start_time", "-start_time"}:
            qs = qs.order_by(
                "slot__start_time" if ordering == "start_time" else "-slot__start_time"
            )

        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="limit",
                required=False,
                type=int,
                description="Quantidade por página (default=20, max=100)",
            ),
            OpenApiParameter(
                name="offset",
                required=False,
                type=int,
                description="Deslocamento de registros (default=0)",
            ),
            OpenApiParameter(
                name="ordering",
                required=False,
                type=str,
                description="Ordenação: start_time, -start_time, created_at, -created_at, slot_time, -slot_time",
            ),
            OpenApiParameter(
                name="Accept-Language",
                location=OpenApiParameter.HEADER,
                required=False,
                type=OpenApiTypes.STR,
                description="Idioma preferido da resposta (suportado: pt-PT, en)",
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=AppointmentSerializer(many=True),
                description="Lista paginada. Headers de resposta: X-Total-Count, X-Limit, X-Offset, Link (RFC 5988), Content-Language.",
            )
        },
    )
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()

        # paginação limit/offset
        limit, offset = get_limit_offset(request, default=20, max_limit=100)
        total = qs.count()
        sliced = qs[offset : offset + limit]

        serializer = self.get_serializer(sliced, many=True)
        resp = Response(serializer.data, status=drf_status.HTTP_200_OK)
        set_pagination_headers(
            resp, request, total_count=total, limit=limit, offset=offset
        )
        return resp

    def perform_create(self, serializer):
        tenant = getattr(self.request.user, "tenant", None)
        if tenant is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"tenant": ["Usuário sem tenant."]})

        professional = serializer.validated_data.get("professional")
        if professional is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"professional": ["Profissional é obrigatório."]})

        if professional.tenant_id != tenant.id:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"professional": ["Profissional não pertence ao tenant."]}
            )

        if self.request.user.has_staff_role(TenantStaffMember.Role.COLLABORATOR):
            staff_member = getattr(self.request.user, "staff_member", None)
            if not staff_member or professional.staff_member_id != staff_member.id:
                raise PermissionDenied("Colaboradores só podem agendar para si mesmos.")

        serializer.save(tenant=tenant)

    def partial_update(self, request, *args, **kwargs):
        """
        Permite ao salão editar:
        - notes                (campo livre)
        - slot                 (reagendamento para outro horário livre)
        - status='cancelled'   (cancela + libera slot + registra cancelled_by)
        Regras:
        - Não permite alterar outros campos.
        - Não permite combinar status='cancelled' com troca de slot na mesma requisição.
        """
        instance: Appointment = self.get_object()

        # Segurança extra: além do permission, revalida ownership
        u = request.user
        is_owner = (
            instance.professional.user_id == u.id or instance.service.user_id == u.id
        )
        if not is_owner:
            raise PermissionDenied(
                "Você não tem permissão para alterar este agendamento."
            )

        data = request.data or {}
        allowed_keys = {"notes", "slot", "status"}
        unknown = set(data.keys()) - allowed_keys
        if unknown:
            raise ValidationError(
                {"detail": f"Campos não permitidos: {', '.join(sorted(unknown))}"}
            )

        new_notes = data.get("notes", None) if "notes" in data else None
        new_status = data.get("status", None)
        new_slot_id = data.get("slot", None)

        # Notas
        if "notes" in data:
            instance.notes = new_notes or ""

        # Regra: não combinar cancelamento com troca de slot
        if new_status == "cancelled" and new_slot_id is not None:
            raise ValidationError(
                {"detail": "Não é permitido reagendar e cancelar na mesma operação."}
            )

        # Reagendamento
        if new_slot_id is not None:
            try:
                new_slot = ScheduleSlot.objects.select_for_update().get(pk=new_slot_id)
            except ScheduleSlot.DoesNotExist:
                raise ValidationError({"slot": "Horário não encontrado."})

            if new_slot.id == instance.slot_id:
                raise ValidationError({"slot": "O novo horário é igual ao atual."})

            if new_slot.professional_id != instance.professional_id:
                raise ValidationError(
                    {"slot": "Slot não pertence ao mesmo profissional."}
                )

            if (not new_slot.is_available) or (new_slot.status != "available"):
                raise ValidationError(
                    {"slot": "Horário selecionado não está disponível."}
                )

            if new_slot.start_time <= timezone.now():
                raise ValidationError(
                    {"slot": "Não é possível reagendar para horário passado."}
                )

            # Encontrar bloco contínuo suficiente para a duração do serviço
            duration = int(getattr(instance.service, "duration_minutes", 0) or 0)
            tenant = getattr(instance, "tenant", None)
            professional = getattr(instance, "professional", None)

            block: List[ScheduleSlot] = _find_contiguous_block_for(
                tenant=tenant,
                professional=professional,
                start_slot=new_slot,
                required_minutes=duration,
            )
            if not block:
                raise ValidationError(
                    {"slot": "Bloco contínuo indisponível para a duração do serviço."}
                )

            # Aplicar reagendamento atômico: libera todos os slots antigos (incl. extras) e reserva novo bloco
            with cast(Any, transaction.atomic()):
                old_slot = ScheduleSlot.objects.select_for_update().get(
                    pk=instance.slot_id
                )
                # Libera slot principal antigo e quaisquer slots extras vinculados
                old_slot.mark_available()
                _release_reserved_slots(instance)

                # Reserva novo bloco contínuo
                for idx, s in enumerate(block):
                    s.mark_booked()
                    if idx > 0:
                        AppointmentReservedSlot.objects.create(
                            tenant=tenant,
                            appointment=instance,
                            slot=s,
                        )

                # Atualiza slot principal do agendamento
                instance.slot = block[0]
                instance.save(update_fields=["slot", "notes"])  # status inalterado aqui

                logger.info(
                    "Appointment rescheduled successfully",
                    extra={
                        "appointment_id": instance.id,
                        "tenant_id": getattr(instance.tenant, "id", None),
                        "new_slot_id": instance.slot.id,
                        "rescheduled_by_id": request.user.id,
                    },
                )

        # Alteração de status
        if new_status is not None:
            if new_status not in ("scheduled", "cancelled", "completed", "paid"):
                raise ValidationError({"status": "Status inválido."})

            if new_status == "cancelled":
                if instance.status == "cancelled":
                    raise ValidationError(
                        {"status": "Este agendamento já foi cancelado."}
                    )

                with cast(Any, transaction.atomic()):
                    instance.status = "cancelled"
                    instance.cancelled_by = request.user
                    instance.slot.mark_available()
                    # Libera slots extras vinculados a este agendamento
                    _release_reserved_slots(instance)
                    instance.save(update_fields=["status", "cancelled_by", "notes"])

                    logger.info(
                        "Appointment cancelled successfully via partial_update",
                        extra={
                            "appointment_id": instance.id,
                            "tenant_id": getattr(instance.tenant, "id", None),
                            "cancelled_by_id": request.user.id,
                        },
                    )

                # e-mail (não bloqueia a resposta)
                try:
                    customer = instance.customer
                    client_email = (
                        customer.email
                        if customer and customer.email
                        else instance.client.email
                    )
                    client_name = (
                        customer.name
                        if customer and customer.name
                        else (
                            instance.client.get_full_name()
                            or instance.client.username
                            or (instance.client.email or "").split("@")[0]
                        )
                    )
                    salon_email = instance.professional.user.email
                    if client_email:
                        salon_name = (
                            instance.tenant.name if instance.tenant else "Salonix"
                        )
                        send_appointment_cancellation_email(
                            client_email=client_email,
                            salon_email=salon_email,
                            client_name=client_name,
                            service_name=instance.service.name,
                            date_time=instance.slot.start_time,
                            salon_name=salon_name,
                        )
                except Exception:
                    logger.error("Erro ao enviar e-mail de cancelamento", exc_info=True)

            elif new_status in ("completed", "paid"):
                # Transição para completed ou paid - slot continua ocupado
                if instance.status == "cancelled":
                    raise ValidationError(
                        {
                            "status": "Não é possível alterar status de agendamento cancelado."
                        }
                    )

                instance.status = new_status
                instance.save(update_fields=["status", "notes"])

            elif new_status == "scheduled":
                # Voltar para scheduled - só se não estiver cancelado
                if instance.status == "cancelled":
                    raise ValidationError(
                        {
                            "status": "Não é possível reagendar agendamento cancelado. Crie um novo agendamento."
                        }
                    )

                instance.status = "scheduled"
                instance.cancelled_by = None
                instance.save(update_fields=["status", "cancelled_by", "notes"])

        # Caso só tenha mudado notes (sem slot/status), salva aqui
        if new_slot_id is None and new_status is None and "notes" in data:
            instance.save(update_fields=["notes"])

        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)

    def get_object(self):
        # busca sem restringir por get_queryset(), para podermos diferenciar 403 de 404
        obj = get_object_or_404(
            Appointment.objects.select_related(
                "client", "service", "professional", "slot"
            ),
            pk=self.kwargs["pk"],
        )
        u = self.request.user
        is_owner = (obj.professional.user_id == u.id) or (obj.service.user_id == u.id)
        if not is_owner:
            raise PermissionDenied(
                "Você não tem permissão para alterar este agendamento."
            )
        return obj

    def destroy(self, request, *args, **kwargs):
        # Evitamos delete duro via API do salão (histórico importa).
        return Response(
            {
                "detail": "Exclusão de agendamentos não é permitida. Cancele o agendamento."
            },
            status=drf_status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    MAX_EXPORT_ROWS = 20_000

    def get_throttles(self):
        # Aplica o escopo de throttle apenas no endpoint de exportação
        if getattr(self, "action", None) == "export_csv":
            self.throttle_scope = "export_csv"
        else:
            # Sem escopo nas demais ações do ViewSet (fica só o UserRateThrottle)
            self.throttle_scope = None
        return super().get_throttles()

    @action(
        detail=False,
        methods=["get"],
        url_path="export",
        throttle_classes=[ScopedRateThrottle],
    )
    def export_csv(self, request, *args, **kwargs):
        """
        Exporta a lista de agendamentos do salão (respeitando os mesmos filtros
        de listagem) em CSV.
        """
        try:
            # 1) Começa com o mesmo queryset filtrado da listagem
            qs = self.get_queryset()

            # 2) Fallback: se o parâmetro veio como data pura (YYYY-MM-DD),
            # reforça o filtro por __date para evitar edge cases de TZ/microsegundos.
            params = request.query_params
            df = params.get("date_from")
            dt = params.get("date_to")

            try:
                d_from = parse_date(df) if df and len(df) == 10 else None
                d_to = parse_date(dt) if dt and len(dt) == 10 else None
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid date format in export request: {e}")
                return Response(
                    {"error": "Formato de data inválido. Use YYYY-MM-DD."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )

            if d_from:
                qs = qs.filter(slot__start_time__date__gte=d_from)
            if d_to:
                qs = qs.filter(slot__start_time__date__lte=d_to)

            # 3) Materializa as linhas antes do streaming (evita DB depois do yield)
            # Importar utilitários de formatação
            from reports.utils.csv_formatter import (
                write_timely_one_header,
                format_datetime_pt,
            )

            column_mapping = {
                "id": "ID",
                "client_name": "Nome do Cliente",
                "client_email": "Email do Cliente",
                "service_name": "Serviço",
                "professional_name": "Profissional",
                "slot_start_time": "Início",
                "slot_end_time": "Fim",
                "status": "Status",
                "notes": "Observações",
                "created_at": "Criado em",
            }

            headers = list(column_mapping.values())

            def row(a):
                try:
                    client_name = (
                        a.client.get_full_name()
                        or a.client.username
                        or (a.client.email or "").split("@")[0]
                    )
                    return [
                        a.id,
                        client_name,
                        a.client.email or "",
                        a.service.name if a.service else "",
                        a.professional.name if a.professional else "",
                        format_datetime_pt(a.slot.start_time) if a.slot else "",
                        format_datetime_pt(a.slot.end_time) if a.slot else "",
                        a.status or "",
                        (a.notes or "").replace("\n", " ").strip(),
                        format_datetime_pt(a.created_at),
                    ]
                except Exception as e:
                    logger.error(
                        f"Error processing appointment {getattr(a, 'id', 'unknown')}: {e}"
                    )
                    # Retorna linha com dados básicos em caso de erro
                    return [
                        getattr(a, "id", ""),
                        "Erro ao processar",
                        "",
                        "",
                        "",
                        "",
                        "",
                        getattr(a, "status", ""),
                        "Erro na exportação",
                        format_datetime_pt(getattr(a, "created_at", timezone.now())),
                    ]

            # aplica o limite de linhas (proteção)
            # importante: não alteramos o comportamento normal — apenas
            # truncamos quando exceder o teto e sinalizamos por header
            try:
                limited_qs = qs[: self.MAX_EXPORT_ROWS]
                rows = [row(appt) for appt in limited_qs]
            except Exception as e:
                logger.error(f"Error querying appointments for export: {e}")
                return Response(
                    {"error": "Erro ao consultar agendamentos. Tente novamente."},
                    status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            class Echo:
                def write(self, value):
                    return value

            writer = csv.writer(Echo())

            def generate():
                try:
                    # Cabeçalho TimelyOne
                    header_buffer = io.StringIO()
                    header_writer = csv.writer(header_buffer)
                    write_timely_one_header(
                        header_writer,
                        report_title="Relatório de Agendamentos",
                        start_date=d_from,
                        end_date=d_to,
                    )
                    yield header_buffer.getvalue()

                    # Cabeçalho das colunas
                    yield writer.writerow(headers)
                    for r in rows:
                        yield writer.writerow(r)
                except Exception as e:
                    logger.error(f"Error generating CSV content: {e}")
                    yield writer.writerow(["Erro na geração do CSV"])

            ts = timezone.now().strftime("%Y%m%d_%H%M%S")
            filename = f"salon_appointments_{ts}.csv"

            response = StreamingHttpResponse(
                generate(), content_type="text/csv; charset=utf-8"
            )
            response["Content-Disposition"] = f'attachment; filename="{filename}"'

            # headers de segurança/cache
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["X-Content-Type-Options"] = "nosniff"

            # sinaliza truncamento quando aplicável (sem quebrar clientes)
            try:
                total = qs.count()
            except Exception as e:
                logger.warning(f"Could not count total appointments for export: {e}")
                total = None

            if total is not None and total > len(rows):
                response["X-Result-Truncated"] = "1"
                response["X-Result-Total"] = str(total)
                response["X-Result-Returned"] = str(len(rows))

            logger.info(
                f"CSV export completed successfully. Rows: {len(rows)}, Total: {total}"
            )
            return response

        except PermissionDenied:
            logger.warning(
                f"Permission denied for CSV export by user {request.user.id}"
            )
            raise
        except ValidationError as e:
            logger.warning(f"Validation error in CSV export: {e}")
            return Response(
                {"error": "Dados inválidos para exportação."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Unexpected error in CSV export: {e}", exc_info=True)
            return Response(
                {"error": "Erro interno do servidor. Tente novamente mais tarde."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MyAppointmentsListView(TenantIsolatedMixin, ListAPIView):
    """
    Lista os agendamentos do usuário autenticado (como cliente).
    GET /api/me/appointments/
    """

    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # Usar o mixin para filtrar por tenant primeiro
        qs = super().get_queryset()

        return (
            qs.filter(client=user)
            .select_related("client", "service", "professional", "slot")
            .order_by("-slot__start_time", "-created_at")
        )


class AppointmentDetailView(TenantIsolatedMixin, RetrieveAPIView):
    queryset = Appointment.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = AppointmentDetailSerializer

    def get_queryset(self):
        user = self.request.user
        # Usar o mixin para filtrar por tenant primeiro
        qs = (
            super()
            .get_queryset()
            .select_related(
                "client",
                "service",
                "professional",
                "professional__staff_member",
                "slot",
                "tenant",
            )
        )

        if user.is_superuser:
            return qs

        tenant = getattr(user, "tenant", None)
        if _is_owner_or_manager(user) and tenant:
            return qs.filter(tenant_id=tenant.id)

        filters: Any = (
            Q(client=user) | Q(service__user=user) | Q(professional__user=user)
        )

        if _is_collaborator(user):
            staff_member = _get_staff_member(user)
            if staff_member:
                filters = (
                    Q(client=user)
                    | Q(professional__staff_member=staff_member)
                    | Q(professional__user=user)
                )
            filters = filters | Q(service__user=user)

        return qs.filter(filters)


class AppointmentICSDownloadView(TenantIsolatedMixin, APIView):
    """
    GET /api/appointments/{id}/ics/

    Download de arquivo .ics (iCalendar) para um agendamento específico.
    Permite que clientes e donos do salão baixem eventos de calendário.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: OpenApiResponse(
                description="ICS calendar file",
                response=OpenApiTypes.BINARY,
            )
        }
    )
    def get(self, request, pk):
        """Gerar e retornar arquivo .ics para download."""
        user = request.user
        tenant = request.tenant

        if not tenant:
            ICS_DOWNLOADS_TOTAL.labels(tenant_id="unknown", status="error").inc()
            return Response(
                {"detail": "Tenant não identificado."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        try:
            appointment = Appointment.objects.select_related(
                "client",
                "service",
                "professional",
                "professional__staff_member",
                "slot",
                "tenant",
            ).get(pk=pk, tenant=tenant)
        except Appointment.DoesNotExist:
            ICS_DOWNLOADS_TOTAL.labels(tenant_id=tenant.id, status="not_found").inc()
            logger.warning(
                f"ICS download failed - appointment {pk} not found",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "appointment_id": pk,
                },
            )
            return Response(
                {"detail": "Agendamento não encontrado."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            ICS_DOWNLOADS_TOTAL.labels(tenant_id=tenant.id, status="error").inc()
            logger.error(
                f"ICS download failed with error: {e}",
                exc_info=True,
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "appointment_id": pk,
                    "error": str(e),
                },
            )
            return Response(
                {"detail": "Erro interno do servidor."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        has_permission = (
            appointment.client_id == user.id
            or IsSalonOwnerOfAppointment().has_object_permission(
                request, self, appointment
            )
        )
        if not has_permission:
            ICS_DOWNLOADS_TOTAL.labels(tenant_id=tenant.id, status="forbidden").inc()
            logger.warning(
                "ICS download forbidden",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "appointment_id": appointment.id,
                },
            )
            return Response(
                {"detail": "Você não tem permissão para acessar este agendamento."},
                status=drf_status.HTTP_403_FORBIDDEN,
            )

        try:
            ics_content = ICSGenerator.generate_ics(appointment)
            filename = ICSGenerator.get_filename(appointment)
        except Exception as e:
            ICS_DOWNLOADS_TOTAL.labels(tenant_id=tenant.id, status="error").inc()
            logger.error(
                f"ICS generation failed with error: {e}",
                exc_info=True,
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "appointment_id": appointment.id,
                    "error": str(e),
                },
            )
            return Response(
                {"detail": "Erro interno do servidor."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response = HttpResponse(
            ics_content.encode("utf-8"), content_type="text/calendar; charset=utf-8"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"

        ICS_DOWNLOADS_TOTAL.labels(tenant_id=tenant.id, status="success").inc()

        logger.info(
            f"ICS download successful for appointment {appointment.id}",
            extra={
                "tenant_id": tenant.id,
                "user_id": user.id,
                "appointment_id": appointment.id,
                "ics_filename": filename,
            },
        )
        return response


class AppointmentICSDownloadPublicView(APIView):
    """
    GET/POST /api/public/appointments/{id}/ics/

    Download público de arquivo .ics protegido por token HMAC.
    Não requer autenticação.

    Métodos aceitos:
    - GET: token em query string (?token=...) [legacy]
    - POST: token em header (X-ICS-Token) [seguro, recomendado]
    """

    permission_classes = [AllowAny]

    @extend_schema(
        responses={
            200: OpenApiResponse(
                description="ICS calendar file",
                response=OpenApiTypes.BINARY,
            )
        }
    )
    def _get_token(self, request, pk):
        """Extrai token do header, query string ou rid temporário."""
        # Prioridade 1: Header (mais seguro)
        token = request.META.get("HTTP_X_ICS_TOKEN")
        if token:
            return token

        # Compatibilidade com links antigos.
        token = request.query_params.get("token")
        if token:
            return token

        # Link por rid opaco (e-mails), com resolução no cache.
        rid = request.query_params.get("rid")
        if not rid:
            return None

        entry = cache.get(f"ics:rid:{rid}")
        if not isinstance(entry, dict):
            return None

        try:
            entry_appt_id = int(entry.get("appointment_id"))
            if int(pk) != entry_appt_id:
                return None
        except Exception:
            return None

        token_from_rid = entry.get("token")
        return token_from_rid if isinstance(token_from_rid, str) else None

    def _download_ics(self, request, pk):
        """Lógica compartilhada de download entre GET e POST."""
        token = self._get_token(request, pk)
        if not token:
            ICS_DOWNLOADS_TOTAL.labels(
                tenant_id="unknown", status="missing_token"
            ).inc()
            return Response(
                {"detail": "Token obrigatório."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        try:
            appointment = Appointment.objects.select_related(
                "client",
                "service",
                "professional",
                "professional__staff_member",
                "slot",
                "tenant",
            ).get(pk=pk)
        except Appointment.DoesNotExist:
            ICS_DOWNLOADS_TOTAL.labels(tenant_id="unknown", status="not_found").inc()
            return Response(
                {"detail": "Agendamento não encontrado."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            ICS_DOWNLOADS_TOTAL.labels(tenant_id="unknown", status="error").inc()
            logger.error(
                f"Public ICS download failed with error: {e}",
                exc_info=True,
                extra={
                    "appointment_id": pk,
                    "error": str(e),
                },
            )
            return Response(
                {"detail": "Erro interno do servidor."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        tenant_id = str(getattr(appointment, "tenant_id", "unknown"))

        # Verificar token
        if not verify_public_ics_token(appointment, token):
            ICS_DOWNLOADS_TOTAL.labels(
                tenant_id=tenant_id, status="invalid_token"
            ).inc()
            return Response(
                {"detail": "Token inválido."},
                status=drf_status.HTTP_403_FORBIDDEN,
            )

        try:
            ics_content = ICSGenerator.generate_ics(appointment)
            filename = ICSGenerator.get_filename(appointment)
        except Exception as e:
            ICS_DOWNLOADS_TOTAL.labels(tenant_id=tenant_id, status="error").inc()
            logger.error(
                f"Public ICS generation failed with error: {e}",
                exc_info=True,
                extra={
                    "tenant_id": tenant_id,
                    "appointment_id": appointment.id,
                    "error": str(e),
                },
            )
            return Response(
                {"detail": "Erro ao gerar arquivo ICS."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response = HttpResponse(
            ics_content.encode("utf-8"), content_type="text/calendar; charset=utf-8"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"

        ICS_DOWNLOADS_TOTAL.labels(tenant_id=tenant_id, status="success").inc()
        logger.info(
            f"Public ICS download successful for appointment {appointment.id}",
            extra={
                "tenant_id": tenant_id,
                "appointment_id": appointment.id,
                "ics_filename": filename,
            },
        )
        return response

    def get(self, request, pk):
        """GET com token em query string (compatibilidade)."""
        return self._download_ics(request, pk)

    def post(self, request, pk):
        """POST com token em header (recomendado para segurança)."""
        return self._download_ics(request, pk)


class FeedbackListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Feedback"],
        summary="Listar feedbacks",
        parameters=[
            OpenApiParameter(
                name="from",
                description="Data/hora inicial (ISO)",
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="to",
                description="Data/hora final (ISO)",
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="category",
                description="Filtro de categoria",
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="rating",
                description="Filtro por rating exato (1-5)",
                required=False,
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name="min_rating",
                description="Rating mínimo (1-5)",
                required=False,
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name="max_rating",
                description="Rating máximo (1-5)",
                required=False,
                type=OpenApiTypes.INT,
            ),
        ],
        responses={
            200: OpenApiResponse(response=FeedbackSerializer(many=True)),
            403: OpenApiResponse(response=OpenApiTypes.OBJECT),
        },
        examples=[
            OpenApiExample(
                name="Listar por categoria e rating mínimo",
                value={"results": []},
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request):
        user = request.user
        tenant = getattr(request, "tenant", None)
        if not tenant and getattr(user, "tenant", None):
            tenant = user.tenant
        if not tenant:
            raise PermissionDenied("Tenant não resolvido")
        if not user.has_staff_role(
            TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
        ):
            raise PermissionDenied("Apenas owner/manager podem listar feedbacks")

        qs = Feedback.objects.filter(tenant=tenant)
        start_q = request.query_params.get("from")
        end_q = request.query_params.get("to")
        if start_q:
            try:
                start = parse_datetime(start_q) or (
                    parse_date(start_q)
                    and timezone.make_aware(
                        timezone.datetime.combine(
                            parse_date(start_q), timezone.datetime.min.time()
                        )
                    )
                )
                if start:
                    qs = qs.filter(created_at__gte=start)
            except Exception:
                pass
        if end_q:
            try:
                end = parse_datetime(end_q) or (
                    parse_date(end_q)
                    and timezone.make_aware(
                        timezone.datetime.combine(
                            parse_date(end_q), timezone.datetime.max.time()
                        )
                    )
                )
                if end:
                    qs = qs.filter(created_at__lte=end)
            except Exception:
                pass
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        rating = request.query_params.get("rating")
        if rating:
            try:
                qs = qs.filter(rating=int(rating))
            except Exception:
                pass
        min_rating = request.query_params.get("min_rating")
        max_rating = request.query_params.get("max_rating")
        try:
            if min_rating:
                qs = qs.filter(rating__gte=int(min_rating))
            if max_rating:
                qs = qs.filter(rating__lte=int(max_rating))
        except Exception:
            pass

        data = FeedbackSerializer(qs.order_by("-created_at"), many=True).data
        cat_label = (request.query_params.get("category") or "-").strip() or "-"
        FEEDBACK_EVENTS_TOTAL.labels(
            tenant_id=str(tenant.id),
            action="list",
            result="success",
            category=cat_label,
        ).inc()
        logger.info(
            "feedback_list_ok",
            extra={
                "tenant_id": tenant.id,
                "count": len(data),
                "category_filter": cat_label,
            },
        )
        return Response(data)

    throttle_classes = [FeedbackCreateThrottle]
    throttle_scope = "feedback_create"

    @extend_schema(
        tags=["Feedback"],
        summary="Criar feedback",
        request=FeedbackSerializer,
        responses={
            201: FeedbackSerializer,
            400: OpenApiResponse(response=OpenApiTypes.OBJECT),
            403: OpenApiResponse(response=OpenApiTypes.OBJECT),
            429: OpenApiResponse(response=OpenApiTypes.OBJECT),
        },
        examples=[
            OpenApiExample(
                name="Request (anônimo)",
                description="Criação de feedback anônimo",
                value={
                    "category": "praise",
                    "rating": 5,
                    "message": "Excelente",
                    "is_anonymous": True,
                    "captcha_token": "dev-bypass",
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Sucesso",
                value={
                    "id": 1,
                    "tenant": 1,
                    "category": "praise",
                    "rating": 5,
                    "message": "Excelente",
                    "is_anonymous": True,
                    "created_at": "2025-12-04T12:00:00Z",
                    "updated_at": "2025-12-04T12:00:00Z",
                },
                response_only=True,
                status_codes=["201"],
            ),
            OpenApiExample(
                name="Captcha inválido",
                value={"detail": "Captcha inválido."},
                response_only=True,
                status_codes=["400"],
            ),
            OpenApiExample(
                name="Permissão necessária",
                value={"detail": "Apenas owner pode criar feedback"},
                response_only=True,
                status_codes=["403"],
            ),
            OpenApiExample(
                name="Duplicado recente",
                value={"detail": "Feedback duplicado recente."},
                response_only=True,
                status_codes=["429"],
            ),
        ],
    )
    def post(self, request):
        try:
            enforce_captcha_or_raise(request)
        except ValidationError:
            return Response(
                {"detail": "Captcha inválido."}, status=drf_status.HTTP_400_BAD_REQUEST
            )

        serializer = FeedbackSerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            from salonix_backend.pii_utils import sanitize_log_data

            logger.warning(
                "feedback_create_validation_error",
                extra={
                    "errors": e.detail,
                    "data": sanitize_log_data(dict(request.data)),
                },
            )
            raise e

        try:
            user = request.user
            if not getattr(user, "is_authenticated", False):
                raise PermissionDenied("Autenticação necessária")
            if not user.has_staff_role(TenantStaffMember.Role.OWNER):
                raise PermissionDenied("Apenas owner pode criar feedback")
            tenant = getattr(request, "tenant", None)
            if not tenant and getattr(user, "tenant", None):
                tenant = user.tenant

            if not tenant:
                # Se mesmo sendo Owner não tiver tenant (ex: erro de integridade),
                # retornamos erro amigável em vez de 500
                logger.error("feedback_create_no_tenant", extra={"user_id": user.id})
                raise ValidationError(
                    {
                        "detail": "Não foi possível identificar o salão (tenant) para registrar o feedback."
                    }
                )

            data = serializer.validated_data
            cutoff = timezone.now() - timezone.timedelta(minutes=10)
            dup_qs = Feedback.objects.filter(
                tenant=tenant,
                created_at__gte=cutoff,
                message=data.get("message"),
                rating=data.get("rating"),
                category=data.get("category"),
            )
            customer = data.get("customer")
            if customer is None:
                dup_qs = dup_qs.filter(customer__isnull=True)
            else:
                dup_qs = dup_qs.filter(customer_id=getattr(customer, "id", customer))
            if dup_qs.exists():
                FEEDBACK_EVENTS_TOTAL.labels(
                    tenant_id=str(getattr(tenant, "id", "")),
                    action="create",
                    result="duplicate",
                    category=str(data.get("category") or "-"),
                ).inc()
                logger.warning(
                    "feedback_create_duplicate",
                    extra={
                        "tenant_id": getattr(tenant, "id", None),
                        "category": data.get("category"),
                        "rating": data.get("rating"),
                    },
                )
                return Response(
                    {"detail": "Feedback duplicado recente."},
                    status=drf_status.HTTP_429_TOO_MANY_REQUESTS,
                )
            obj = serializer.save(tenant=tenant)
            FEEDBACK_EVENTS_TOTAL.labels(
                tenant_id=str(tenant.id),
                action="create",
                result="success",
                category=obj.category,
            ).inc()
            FEEDBACK_RATINGS_SUM.labels(tenant_id=str(tenant.id)).inc(obj.rating)
            FEEDBACK_RATINGS_COUNT.labels(tenant_id=str(tenant.id)).inc()
            FEEDBACK_CATEGORY_TOTAL.labels(
                tenant_id=str(tenant.id), category=obj.category
            ).inc()
            try:
                trigger_feedback_notifications(tenant, obj)
            except Exception:
                logger.exception(
                    "feedback_notifications_failed",
                    extra={"tenant_id": tenant.id, "feedback_id": obj.id},
                )
            logger.info(
                "feedback_create_ok",
                extra={
                    "tenant_id": tenant.id,
                    "feedback_id": obj.id,
                    "category": obj.category,
                    "rating": obj.rating,
                },
            )
            return Response(
                FeedbackSerializer(obj).data, status=drf_status.HTTP_201_CREATED
            )
        except Exception as e:
            if isinstance(e, PermissionDenied):
                raise e
            logger.exception("feedback_create_failed_unexpected")
            raise e


class FeedbackDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Feedback"],
        summary="Detalhar feedback",
        responses={
            200: FeedbackSerializer,
            403: OpenApiResponse(response=OpenApiTypes.OBJECT),
        },
        examples=[
            OpenApiExample(
                name="Sucesso",
                value={
                    "id": 1,
                    "tenant": 1,
                    "category": "bug",
                    "rating": 2,
                    "message": "Erro ao abrir relatório",
                    "is_anonymous": False,
                    "created_at": "2025-12-04T12:00:00Z",
                    "updated_at": "2025-12-04T12:00:00Z",
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request, pk: int):
        tenant = getattr(request, "tenant", None)
        user = request.user
        if not tenant and getattr(user, "tenant", None):
            tenant = user.tenant
        if not tenant:
            raise PermissionDenied("Tenant não resolvido")
        user = request.user
        if not user.has_staff_role(
            TenantStaffMember.Role.OWNER, TenantStaffMember.Role.MANAGER
        ):
            raise PermissionDenied("Apenas owner/manager podem ver feedbacks")
        obj = get_object_or_404(Feedback, pk=pk, tenant=tenant)
        FEEDBACK_EVENTS_TOTAL.labels(
            tenant_id=str(tenant.id),
            action="detail",
            result="success",
            category=obj.category,
        ).inc()
        logger.info(
            "feedback_detail_ok",
            extra={
                "tenant_id": tenant.id,
                "feedback_id": obj.id,
                "category": obj.category,
            },
        )
        return Response(FeedbackSerializer(obj).data)


class FeedbackExportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Feedback"],
        summary="Exportar feedbacks por cliente",
        parameters=[
            OpenApiParameter(
                name="customer_id",
                description="ID do cliente",
                required=False,
                type=OpenApiTypes.INT,
            ),
        ],
        responses={
            200: OpenApiResponse(response=OpenApiTypes.OBJECT),
            403: OpenApiResponse(response=OpenApiTypes.OBJECT),
        },
        examples=[
            OpenApiExample(
                name="Sucesso",
                value={
                    "count": 2,
                    "items": [
                        {
                            "id": 1,
                            "tenant": 1,
                            "category": "praise",
                            "rating": 5,
                            "message": "Excelente",
                            "is_anonymous": True,
                            "created_at": "2025-12-04T12:00:00Z",
                            "updated_at": "2025-12-04T12:00:00Z",
                        }
                    ],
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise PermissionDenied("Tenant não resolvido")
        user = request.user
        if not user.has_staff_role(TenantStaffMember.Role.OWNER):
            raise PermissionDenied("Apenas owner pode exportar feedbacks")
        customer_id = request.query_params.get("customer_id")
        qs = Feedback.objects.filter(tenant=tenant)
        if customer_id:
            try:
                qs = qs.filter(customer_id=int(customer_id))
            except Exception:
                pass
        data = FeedbackSerializer(qs.order_by("-created_at"), many=True).data
        FEEDBACK_EVENTS_TOTAL.labels(
            tenant_id=str(tenant.id), action="export", result="success", category="-"
        ).inc()
        logger.info(
            "feedback_export_ok",
            extra={
                "tenant_id": tenant.id,
                "count": len(data),
                "customer_id": customer_id,
            },
        )
        return Response({"count": len(data), "items": data})


class FeedbackPurgeByCustomerView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Feedback"],
        summary="Apagar feedbacks por cliente",
        responses={
            200: OpenApiResponse(response=OpenApiTypes.OBJECT),
            403: OpenApiResponse(response=OpenApiTypes.OBJECT),
        },
        examples=[
            OpenApiExample(
                name="Sucesso",
                value={"deleted": 3},
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def delete(self, request, customer_id: int):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise PermissionDenied("Tenant não resolvido")
        user = request.user
        if not user.has_staff_role(TenantStaffMember.Role.OWNER):
            raise PermissionDenied("Apenas owner pode apagar feedbacks")
        qs = Feedback.objects.filter(tenant=tenant, customer_id=customer_id)
        deleted, _ = qs.delete()
        FEEDBACK_EVENTS_TOTAL.labels(
            tenant_id=str(tenant.id), action="purge", result="success", category="-"
        ).inc()
        logger.info(
            "feedback_purge_ok",
            extra={
                "tenant_id": tenant.id,
                "customer_id": customer_id,
                "deleted": deleted,
            },
        )
        return Response({"deleted": deleted})


class FeedbackRetentionEnforceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Feedback"],
        summary="Aplicar retenção RGPD (apagar antigos)",
        request=None,
        responses={
            200: OpenApiResponse(response=OpenApiTypes.OBJECT),
            403: OpenApiResponse(response=OpenApiTypes.OBJECT),
        },
        examples=[
            OpenApiExample(
                name="Sucesso",
                value={"deleted": 10, "retention_days": 365},
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            raise PermissionDenied("Tenant não resolvido")
        user = request.user
        if not user.has_staff_role(TenantStaffMember.Role.OWNER):
            raise PermissionDenied("Apenas owner pode aplicar retenção")
        days = getattr(settings, "FEEDBACK_RETENTION_DAYS", 365)
        cutoff = timezone.now() - timezone.timedelta(days=int(days))
        qs = Feedback.objects.filter(tenant=tenant, created_at__lt=cutoff)
        deleted, _ = qs.delete()
        FEEDBACK_EVENTS_TOTAL.labels(
            tenant_id=str(tenant.id), action="retention", result="success", category="-"
        ).inc()
        logger.info(
            "feedback_retention_ok",
            extra={"tenant_id": tenant.id, "deleted": deleted, "days": int(days)},
        )
        return Response({"deleted": deleted, "retention_days": int(days)})


# ===== Sistema de Cancelamento de Conta (BE-ACCOUNT-CANCEL #396) =====


class TenantCancelView(APIView):
    """
    POST /api/tenants/cancel-account/

    Cancela conta do tenant (soft delete).
    Requer autenticação de OWNER + confirmação dupla.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Tenants"],
        summary="Cancelar conta do tenant",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "password": {"type": "string", "writeOnly": True},
                    "confirmation_text": {"type": "string", "writeOnly": True},
                    "cancellation_reason": {"type": "string", "nullable": True},
                },
                "required": ["password", "confirmation_text"],
            }
        },
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Conta cancelada com sucesso",
            ),
            400: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Senha incorreta ou confirmação inválida",
            ),
            403: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Apenas owner pode cancelar",
            ),
        },
        examples=[
            OpenApiExample(
                name="Sucesso",
                value={
                    "message": "Conta cancelada com sucesso.",
                    "cancelled_at": "2026-02-05T14:00:00Z",
                    "deletion_date": "2026-04-06T14:00:00Z",
                    "reactivation_link": "/reativar/123/abc123token/",
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def post(self, request):
        # Importar aqui para evitar circular import
        from core.permissions import IsOwner
        from core.serializers import TenantCancelSerializer

        # Verificar se é owner
        is_owner_perm = IsOwner()
        if not is_owner_perm.has_permission(request, self):
            raise PermissionDenied("Somente o owner pode cancelar a conta.")

        serializer = TenantCancelSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        tenant = request.user.tenant

        # 1. Soft delete do tenant
        tenant.status = Tenant.STATUS_CANCELLED
        tenant.cancelled_at = timezone.now()
        tenant.cancellation_reason = serializer.validated_data.get(
            "cancellation_reason", ""
        )
        tenant.scheduled_deletion_at = tenant.calculate_deletion_date()
        tenant.reactivation_token = tenant.generate_reactivation_token()
        tenant.save()

        # 2. Cancelar assinaturas Stripe (BE-ACCOUNT-CANCEL #396)
        stripe_result = {"success": True, "cancelled_count": 0}
        try:
            from payments.services import SubscriptionService

            stripe_result = SubscriptionService.cancel_tenant_subscriptions(tenant)

            if not stripe_result["success"]:
                logger.warning(
                    f"Stripe cancellation had errors for tenant {tenant.id}: "
                    f"{stripe_result['errors']}"
                )
        except Exception as e:
            logger.error(f"Erro ao cancelar Stripe para tenant {tenant.id}: {e}")
            stripe_result = {"success": False, "cancelled_count": 0, "errors": [str(e)]}

        # 3. Enviar email de confirmação (BE-ACCOUNT-CANCEL #396)
        try:
            from core.email_utils import send_account_cancellation_email

            # Construir URL de reativação (ajustar conforme frontend)
            reactivation_url = f"{settings.FRONTEND_URL}/reativar/{tenant.id}/{tenant.reactivation_token}/"
            send_account_cancellation_email(tenant, request.user, reactivation_url)
            logger.info(
                "Email de cancelamento enviado",
                extra={"user_email": mask_email(request.user.email)},
            )
        except Exception as e:
            logger.error(f"Erro ao enviar email para tenant {tenant.id}: {e}")

        # 4. Registrar log de auditoria
        logger.info(
            f"Tenant {tenant.id} ({tenant.slug}) cancelado por owner {request.user.id}. "
            f"Deletado em {tenant.scheduled_deletion_at}. "
            f"Stripe: {stripe_result['cancelled_count']} assinaturas canceladas"
        )

        return Response(
            {
                "message": "Conta cancelada com sucesso.",
                "cancelled_at": tenant.cancelled_at,
                "deletion_date": tenant.scheduled_deletion_at,
                "reactivation_link": f"/reativar/{tenant.id}/{tenant.reactivation_token}/",
                "stripe_subscriptions_cancelled": stripe_result["cancelled_count"],
            },
            status=drf_status.HTTP_200_OK,
        )


class TenantDataExportView(APIView):
    """
    GET /api/tenants/data-export/

    BE-RGPD-01: exporta os dados pessoais do tenant do utilizador autenticado
    como ficheiro JSON (download). Direito de acesso/portabilidade (Art. 15/20).
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "data_export"

    def get(self, request):
        import json as _json

        from rest_framework.exceptions import PermissionDenied

        from core.permissions import IsOwner
        from core.tasks import build_tenant_data_export

        # Apenas o owner pode exportar os dados do tenant.
        if not IsOwner().has_permission(request, self):
            raise PermissionDenied("Somente o owner pode exportar os dados.")

        tenant = request.user.tenant
        export = build_tenant_data_export(tenant)
        body = _json.dumps(export, ensure_ascii=False, indent=2)
        filename = f"timelyone-data-export-{tenant.slug}.json"
        resp = HttpResponse(body, content_type="application/json; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp


class TenantReactivateView(APIView):
    """
    POST /api/tenants/reactivate/

    Reativa conta cancelada (dentro do período de retenção).
    Requer token válido do email de cancelamento.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Tenants"],
        summary="Reativar conta cancelada",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                },
                "required": ["token"],
            }
        },
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Conta reativada com sucesso",
            ),
            400: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Conta não está cancelada",
            ),
            403: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Apenas owner pode reativar",
            ),
            410: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Período de reativação expirado",
            ),
        },
    )
    def post(self, request):
        # Importar aqui para evitar circular import
        from core.permissions import IsOwner
        from core.serializers import TenantReactivateSerializer

        # Verificar se é owner
        is_owner_perm = IsOwner()
        if not is_owner_perm.has_permission(request, self):
            raise PermissionDenied("Somente o owner pode reativar a conta.")

        tenant = request.user.tenant

        # 1. Validar que está cancelled
        if tenant.status != Tenant.STATUS_CANCELLED:
            return Response(
                {"error": "Conta não está cancelada."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        # 2. Validar período de retenção
        if not tenant.can_reactivate():
            return Response(
                {"error": "Período de reativação expirado. Dados já foram deletados."},
                status=drf_status.HTTP_410_GONE,
            )

        # 3. Validar token
        serializer = TenantReactivateSerializer(
            data=request.data, context={"tenant": tenant}
        )
        serializer.is_valid(raise_exception=True)

        # 4. Reativar tenant
        tenant.status = Tenant.STATUS_ACTIVE
        tenant.cancelled_at = None
        tenant.scheduled_deletion_at = None
        tenant.reactivation_token = None
        tenant.save()

        # 5. Reativar Stripe (TODO: implementar se possível)
        # try:
        #     from payments.services import reactivate_stripe_subscription
        #     reactivate_stripe_subscription(tenant)
        # except Exception as e:
        #     logger.error(f"Erro ao reativar Stripe para tenant {tenant.id}: {e}")

        # 6. Enviar email de confirmação (BE-ACCOUNT-CANCEL #396)
        try:
            from core.email_utils import send_account_reactivation_email

            send_account_reactivation_email(tenant, request.user)
            logger.info(
                "Email de reativação enviado",
                extra={"user_email": mask_email(request.user.email)},
            )
        except Exception as e:
            logger.error(
                f"Erro ao enviar email de reativação para tenant {tenant.id}: {e}"
            )

        # 7. Log auditoria
        logger.info(
            f"Tenant {tenant.id} ({tenant.slug}) reativado por owner {request.user.id}"
        )

        return Response(
            {
                "message": "Conta reativada com sucesso!",
                "status": tenant.status,
            },
            status=drf_status.HTTP_200_OK,
        )
