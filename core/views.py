from rest_framework import status as drf_status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.generics import ListAPIView, CreateAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from django.core.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema

from core.email_utils import (
    send_appointment_confirmation_email,
    send_appointment_cancellation_email,
)
from core.models import Appointment, AppointmentSeries, Professional, Service, ScheduleSlot
from users.models import Tenant
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
    ProfessionalSerializer,
    ServiceSerializer,
    ScheduleSlotSerializer,
)
from core.mixins import TenantIsolatedMixin

from django.db import transaction
from django.db.models import Q
from django.http import StreamingHttpResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from prometheus_client import Counter, REGISTRY

from users.permissions import IsSalonOwnerOfAppointment
from core.utils.ics import ICSGenerator

import csv
import logging
from typing import Any, Dict, List, Optional, cast

def _get_or_create_counter(name: str, documentation: str, labelnames: tuple[str, ...]):
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing
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

APPOINTMENT_SERIES_UPDATED_TOTAL = _get_or_create_counter(
    "appointment_series_updated_total",
    "Total number of series update operations",
    ("tenant_id", "action", "status"),
)

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
                return Service.objects.filter(tenant=tenant)
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
                return Professional.objects.filter(tenant=tenant, is_active=True)
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

        # Respeitar o tenant informado (header X-Tenant-Slug ou query param tenant)
        tenant_slug = self.request.headers.get("X-Tenant-Slug") or self.request.GET.get(
            "tenant"
        )

        qs = ScheduleSlot.objects.filter(
            professional_id=professional_id, is_available=True
        )

        if tenant_slug:
            try:
                from users.models import Tenant

                tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
                qs = qs.filter(tenant=tenant)
            except Tenant.DoesNotExist:
                # Se o tenant não existir, não retornar slots
                return ScheduleSlot.objects.none()

        return qs.order_by("start_time")


class AppointmentCreateView(TenantIsolatedMixin, CreateAPIView):
    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        data = cast(Dict[str, Any], serializer.validated_data)
        slot = data["slot"]
        if (not slot.is_available) or (slot.status != "available"):
            raise ValidationError(
                "Este horário já foi agendado ou não está disponível."
            )

        # marca como reservado via helper do model
        slot.mark_booked()

        # Definir tenant e client
        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        if tenant:
            appointment = serializer.save(client=self.request.user, tenant=tenant)
        else:
            appointment = serializer.save(client=self.request.user)

        # Envia e-mail de confirmação
        try:
            send_appointment_confirmation_email(
                to_email=self.request.user.email,
                client_name=(
                    self.request.user.get_full_name()
                    or self.request.user.username
                    or self.request.user.email.split("@")[0]
                ),
                service_name=appointment.service.name,
                date_time=appointment.slot.start_time,
            )
        except Exception as e:
            print("Falha ao enviar e-mail:", e)


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
            # garantir consistência com o tenant resolvido
            service = Service.objects.get(
                id=cast(int, data["service_id"]), tenant=tenant
            )
            professional = Professional.objects.get(
                id=cast(int, data["professional_id"]), tenant=tenant
            )

            appointments_list = cast(List[Dict[str, Any]], data["appointments"]) 
            slot_ids = [cast(int, a["slot_id"]) for a in appointments_list]
            slots = list(ScheduleSlot.objects.filter(id__in=slot_ids, tenant=tenant))

            with cast(Any, transaction.atomic()):
                appointments = []
                for appt_data in appointments_list:
                    slot = next(s for s in slots if s.id == appt_data["slot_id"])
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
                    )
                    appointments.append(appointment)

            from decimal import Decimal

            count = len(appointments)

            # use price_eur (fallback para price se existir)
            raw_unit = getattr(service, "price_eur", None)
            if raw_unit is None:
                raw_unit = getattr(service, "price", 0)

            try:
                unit_price = Decimal(str(raw_unit))
            except Exception:
                unit_price = Decimal("0")

            total_value = float(unit_price * count)

            tenant_label = tenant.id if tenant is not None else "unknown"
            BULK_APPOINTMENTS_TOTAL.labels(tenant_id=tenant_label, status="success").inc()
            BULK_APPOINTMENTS_SIZE.labels(tenant_id=tenant_label).inc(len(appointments))

            # log estruturado de sucesso (exatamente 1 vez)
            logger.info(
                "Bulk appointments created successfully",
                extra={
                    "tenant_id": getattr(tenant, "id", None),
                    "user_id": user.id,
                    "service_id": service.id,  # <-- necessário
                    "professional_id": professional.id,  # <-- necessário
                    "appointments_count": count,  # <-- o teste espera esta chave
                    "appointment_ids": [a.id for a in appointments],
                    "total_value": total_value,  # <-- o teste valida 25.0 quando count=1
                },
            )

            # payload que os testes esperam
            serialized = AppointmentSerializer(
                appointments, many=True, context={"request": request}
            ).data
            message = f"{count} agendamentos criados com sucesso" if count != 1 else "1 agendamento criado com sucesso"

            return Response(
                {
                    "success": True,
                    "appointment_ids": [a.id for a in appointments],
                    "appointments_created": count,
                    "total_value": total_value,  # <-- o teste valida 75.0 (3 * 25.00)
                    "service_name": service.name,
                    "professional_name": professional.name,
                    "appointments": serialized,
                    "message": message,
                },
                status=drf_status.HTTP_201_CREATED,
            )

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
                        service=service,
                        professional=professional,
                        slot=slot,
                        notes=str(
                            appt_data.get("notes") or data.get("notes") or ""
                        ),
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
        qs = super().get_queryset()
        user = self.request.user
        return qs.filter(
            Q(client=user) | Q(service__user=user) | Q(professional__user=user)
        )

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
        start_from = cast(
            Any, data.get("start_from")
        ) or timezone.now()  # atrasa para agora por padrão

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
            detail = getattr(exc, "detail", None) or exc.args or {
                "detail": "Requisição inválida",
            }
            return Response(detail, status=drf_status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - guard para falhas imprevisíveis
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
                    {"slot_ids": ["Quantidade de slots não corresponde aos agendamentos futuros."]}
                )

            slots_qs = (
                ScheduleSlot.objects.select_for_update()
                .filter(id__in=slot_ids, tenant=tenant)
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
                    if desired_slot.is_available is False or desired_slot.status != "available":
                        raise ValidationError(
                            {"slot_ids": [f"Slot {desired_slot_id} não está disponível."]}
                        )

                    if appointment.slot:
                        appointment.slot.mark_available()

                    appointment.slot = desired_slot
                    fields_to_update.append("slot")
                    desired_slot.mark_booked()

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
        series = get_object_or_404(AppointmentSeries.objects.select_related("tenant"), pk=series_id)

        if not self._user_has_access(series, request.user):
            return Response(
                {"detail": "Você não tem permissão para cancelar ocorrências desta série."},
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
        return user == series.client or user == series.service.user or user == series.professional.user

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
            appointment.save()

        # E-mail para cliente e salão (não bloqueia a resposta)
        try:
            send_appointment_cancellation_email(
                client_email=appointment.client.email,
                salon_email=appointment.professional.user.email,
                client_name=appointment.client.get_full_name()
                or appointment.client.username,
                service_name=appointment.service.name,
                date_time=appointment.slot.start_time,
            )
        except Exception as e:
            print("Erro ao enviar e-mail de cancelamento:", str(e))

        serializer = AppointmentSerializer(appointment)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)


class ServiceViewSet(TenantIsolatedMixin, ModelViewSet):
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Filtrar apenas por tenant (TenantIsolatedMixin cuida do escopo)
        return super().get_queryset()

    def perform_create(self, serializer):
        # Preferir tenant do request (usuário autenticado); se ausente (ex.: superuser),
        # tentar resolver via header 'X-Tenant-Slug' ou query param 'tenant'.
        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        if tenant is None:
            slug = (
                self.request.headers.get("X-Tenant-Slug")
                or self.request.query_params.get("tenant")
            )
            if slug:
                try:
                    tenant = Tenant.objects.get(slug=slug, is_active=True)
                except Tenant.DoesNotExist:
                    tenant = None
        if tenant is None and not self.request.user.is_superuser:
            # Usuário comum sem tenant não deve criar registros órfãos
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"tenant": ["Tenant não encontrado para o usuário."]})

        serializer.save(user=self.request.user, tenant=tenant)

    def get_object(self):
        # Busca direta por PK e valida tenant explicitamente (evita filtros indevidos no queryset)
        obj = get_object_or_404(Service, pk=self.kwargs.get(self.lookup_field, self.kwargs.get('pk')))
        if self.request.user.is_superuser:
            return obj
        tenant = getattr(self.request, 'tenant', None) or getattr(self.request.user, 'tenant', None)
        if tenant and hasattr(obj, 'tenant'):
            if obj.tenant_id != tenant.id:
                raise PermissionDenied("Acesso negado: objeto não pertence ao seu tenant")
        return obj


class ProfessionalViewSet(TenantIsolatedMixin, ModelViewSet):
    queryset = Professional.objects.all()
    serializer_class = ProfessionalSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Filtrar apenas por tenant (TenantIsolatedMixin cuida do escopo)
        return super().get_queryset()

    def perform_create(self, serializer):
        tenant = getattr(self.request, "tenant", None) or getattr(
            self.request.user, "tenant", None
        )
        if tenant is None:
            slug = (
                self.request.headers.get("X-Tenant-Slug")
                or self.request.query_params.get("tenant")
            )
            if slug:
                try:
                    tenant = Tenant.objects.get(slug=slug, is_active=True)
                except Tenant.DoesNotExist:
                    tenant = None
        if tenant is None and not self.request.user.is_superuser:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"tenant": ["Tenant não encontrado para o usuário."]})

        serializer.save(user=self.request.user, tenant=tenant)

    def get_object(self):
        obj = get_object_or_404(Professional, pk=self.kwargs.get(self.lookup_field, self.kwargs.get('pk')))
        if self.request.user.is_superuser:
            return obj
        tenant = getattr(self.request, 'tenant', None) or getattr(self.request.user, 'tenant', None)
        if tenant and hasattr(obj, 'tenant'):
            if obj.tenant_id != tenant.id:
                raise PermissionDenied("Acesso negado: objeto não pertence ao seu tenant")
        return obj


class ScheduleSlotViewSet(TenantIsolatedMixin, ModelViewSet):
    queryset = ScheduleSlot.objects.all()
    serializer_class = ScheduleSlotSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Garantir que request.tenant esteja definido para o mixin, usando o tenant do usuário autenticado
        if not getattr(self.request, "tenant", None) and getattr(self.request.user, "tenant", None):
            self.request.tenant = self.request.user.tenant

        qs = super().get_queryset()
        params = self.request.query_params
        professional_id = params.get("professional_id")
        if professional_id:
            qs = qs.filter(professional_id=professional_id)
        is_available = params.get("is_available")
        if is_available is not None:
            val = str(is_available).lower() in {"1", "true", "t", "yes", "y"}
            qs = qs.filter(is_available=val)
        ordering = params.get("ordering") or "-start_time"
        if ordering in {"start_time", "-start_time"}:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by("-start_time")
        return qs

    def perform_create(self, serializer):
        # Sempre usar o tenant do usuário do salão
        tenant = getattr(self.request.user, "tenant", None)
        if tenant is None:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"tenant": ["Usuário sem tenant. Não é possível criar slot."]})

        validated = getattr(serializer, "validated_data", {}) or {}
        professional = validated.get("professional")
        if professional is None:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"professional": ["Profissional é obrigatório."]})
        if hasattr(professional, "tenant_id") and professional.tenant_id != tenant.id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"professional": ["Profissional não pertence ao tenant atual."]})

        serializer.save(tenant=tenant)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()  # get_object valida o tenant via mixin/checagem
        obj.delete()
        return Response(status=drf_status.HTTP_204_NO_CONTENT)

    def get_object(self):
        obj = get_object_or_404(
            ScheduleSlot, pk=self.kwargs.get(self.lookup_field, self.kwargs.get('pk'))
        )
        if self.request.user.is_superuser:
            return obj
        tenant = getattr(self.request, 'tenant', None) or getattr(
            self.request.user, 'tenant', None
        )
        if tenant and hasattr(obj, 'tenant'):
            if obj.tenant_id != tenant.id:
                raise PermissionDenied("Acesso negado: objeto não pertence ao seu tenant")
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

        # Garantir que request.tenant esteja definido (algumas integrações não passam pelo middleware)
        if getattr(self.request, "tenant", None) is None:
            tenant_from_user = getattr(user, "tenant", None)
            if tenant_from_user is not None:
                self.request.tenant = tenant_from_user

        # Usar o mixin para filtrar por tenant primeiro
        qs = super().get_queryset()

        # Depois filtrar por user dentro do tenant
        qs = (
            qs.filter(Q(professional__user=user) | Q(service__user=user))
            .select_related("client", "service", "professional", "slot")
            .order_by("-created_at")
        )

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

        # ordering
        ordering = cast(Optional[str], params.get("ordering"))
        if ordering in {"created_at", "-created_at"}:
            qs = qs.order_by(ordering)
        elif ordering in {"slot_time", "-slot_time"}:
            qs = qs.order_by(
                "slot__start_time" if ordering == "slot_time" else "-slot__start_time"
            )

        return qs

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

            if (not new_slot.is_available) or (new_slot.status != "available"):
                raise ValidationError(
                    {"slot": "Horário selecionado não está disponível."}
                )

            with cast(Any, transaction.atomic()):
                old_slot = ScheduleSlot.objects.select_for_update().get(
                    pk=instance.slot_id
                )
                old_slot.mark_available()
                new_slot.mark_booked()
                instance.slot = new_slot
                instance.save(update_fields=["slot", "notes"])  # status inalterado aqui

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
                    instance.save(update_fields=["status", "cancelled_by", "notes"])

                # e-mail (não bloqueia a resposta)
                try:
                    send_appointment_cancellation_email(
                        client_email=instance.client.email,
                        salon_email=instance.professional.user.email,
                        client_name=(
                            instance.client.get_full_name()
                            or instance.client.username
                            or (instance.client.email or "").split("@")[0]
                        ),
                        service_name=instance.service.name,
                        date_time=instance.slot.start_time,
                    )
                except Exception as e:
                    print("Erro ao enviar e-mail de cancelamento:", str(e))

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
        # 1) Começa com o mesmo queryset filtrado da listagem
        qs = self.get_queryset()

        # 2) Fallback: se o parâmetro veio como data pura (YYYY-MM-DD),
        # reforça o filtro por __date para evitar edge cases de TZ/microsegundos.
        params = request.query_params
        df = params.get("date_from")
        dt = params.get("date_to")

        d_from = parse_date(df) if df and len(df) == 10 else None
        d_to = parse_date(dt) if dt and len(dt) == 10 else None

        if d_from:
            qs = qs.filter(slot__start_time__date__gte=d_from)
        if d_to:
            qs = qs.filter(slot__start_time__date__lte=d_to)

        # 3) Materializa as linhas antes do streaming (evita DB depois do yield)
        headers = [
            "id",
            "client_name",
            "client_email",
            "service_name",
            "professional_name",
            "slot_start_time",
            "slot_end_time",
            "status",
            "notes",
            "created_at",
        ]

        def row(a):
            client_name = (
                a.client.get_full_name()
                or a.client.username
                or (a.client.email or "").split("@")[0]
            )
            return [
                a.id,
                client_name,
                a.client.email,
                a.service.name,
                a.professional.name,
                a.slot.start_time.isoformat(),
                a.slot.end_time.isoformat(),
                a.status,
                (a.notes or "").replace("\n", " ").strip(),
                a.created_at.isoformat(),
            ]

        # aplica o limite de linhas (proteção)
        # importante: não alteramos o comportamento normal — apenas
        # truncamos quando exceder o teto e sinalizamos por header
        limited_qs = qs[: self.MAX_EXPORT_ROWS]
        rows = [row(appt) for appt in limited_qs]

        class Echo:
            def write(self, value):
                return value

        writer = csv.writer(Echo())

        def generate():
            yield writer.writerow(headers)
            for r in rows:
                yield writer.writerow(r)

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
        except Exception:
            total = None
        if total is not None and total > len(rows):
            response["X-Result-Truncated"] = "1"
            response["X-Result-Total"] = str(total)
            response["X-Result-Returned"] = str(len(rows))

        return response


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
        qs = super().get_queryset()

        # Acessível para:
        # - o próprio cliente do agendamento
        # - o salão (dono) via service.user ou professional.user
        cond_any = cast(Any, Q(client=user))
        cond_any = cond_any | cast(Any, Q(service__user=user))
        cond_any = cond_any | cast(Any, Q(professional__user=user))
        return qs.filter(cond_any).select_related("client", "service", "professional", "slot")


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
            # Buscar agendamento com verificação de permissão
            appointment = get_object_or_404(
                Appointment.objects.select_related(
                    "client", "service", "professional", "slot", "tenant"
                )
                .filter(
                    # Filtro por tenant
                    tenant=tenant,
                    # Permissão: cliente do agendamento OU dono do salão
                    **{
                        "pk": pk,
                    },
                )
                .filter(
                    (cast(Any, Q(client=user))
                     | cast(Any, Q(service__user=user))
                     | cast(Any, Q(professional__user=user)))
                )
            )

            # Gerar conteúdo .ics
            ics_content = ICSGenerator.generate_ics(appointment)
            filename = ICSGenerator.get_filename(appointment)

            # Criar response com headers apropriados
            response = HttpResponse(
                ics_content.encode("utf-8"), content_type="text/calendar; charset=utf-8"
            )
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            response["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"

            # Métricas e logs
            ICS_DOWNLOADS_TOTAL.labels(tenant_id=tenant.id, status="success").inc()

            logger.info(
                f"ICS download successful for appointment {appointment.id}",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "appointment_id": appointment.id,
                    "filename": filename,
                },
            )

            return response

        except Appointment.DoesNotExist:
            ICS_DOWNLOADS_TOTAL.labels(tenant_id=tenant.id, status="not_found").inc()

            logger.warning(
                f"ICS download failed - appointment {pk} not found or no permission",
                extra={
                    "tenant_id": tenant.id,
                    "user_id": user.id,
                    "appointment_id": pk,
                },
            )

            return Response(
                {"detail": "Agendamento não encontrado ou sem permissão."},
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
