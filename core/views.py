from rest_framework import status as drf_status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.generics import ListAPIView, CreateAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from core.email_utils import (
    send_appointment_confirmation_email,
    send_appointment_cancellation_email,
)
from core.models import Appointment, Professional, Service, ScheduleSlot
from core.serializers import (
    AppointmentDetailSerializer,
    AppointmentSerializer,
    ProfessionalSerializer,
    ServiceSerializer,
    ScheduleSlotSerializer,
)

from django.db import transaction
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date

from users.permissions import IsSalonOwnerOfAppointment

import csv


class PublicServiceListView(ListAPIView):
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    permission_classes = []


class PublicProfessionalListView(ListAPIView):
    queryset = Professional.objects.filter(is_active=True)
    serializer_class = ProfessionalSerializer
    permission_classes = []


class PublicSlotListView(ListAPIView):
    serializer_class = ScheduleSlotSerializer
    permission_classes = []

    def get_queryset(self):
        professional_id = self.request.query_params.get("professional_id")
        if not professional_id:
            raise ValidationError({"professional_id": "Este parâmetro é obrigatório."})

        return ScheduleSlot.objects.filter(
            professional_id=professional_id, is_available=True
        ).order_by("start_time")


class AppointmentCreateView(CreateAPIView):
    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        slot = serializer.validated_data["slot"]
        if (not slot.is_available) or (slot.status != "available"):
            raise ValidationError(
                "Este horário já foi agendado ou não está disponível."
            )

        # marca como reservado via helper do model
        slot.mark_booked()

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


class AppointmentCancelView(APIView):
    permission_classes = [IsAuthenticated]

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

        with transaction.atomic():
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


class ServiceViewSet(ModelViewSet):
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Service.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ProfessionalViewSet(ModelViewSet):
    queryset = Professional.objects.all()
    serializer_class = ProfessionalSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ScheduleSlotViewSet(ModelViewSet):
    queryset = ScheduleSlot.objects.all()
    serializer_class = ScheduleSlotSerializer
    permission_classes = [IsAuthenticated]


class SalonAppointmentViewSet(ModelViewSet):
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

        qs = (
            Appointment.objects.filter(
                Q(professional__user=user) | Q(service__user=user)
            )
            .select_related("client", "service", "professional", "slot")
            .order_by("-created_at")
        )

        params = self.request.query_params

        # status
        status_value = params.get("status")
        if status_value in {"scheduled", "cancelled", "completed", "paid"}:
            qs = qs.filter(status=status_value)

        # -------- datas --------
        date_from_raw = params.get("date_from")
        date_to_raw = params.get("date_to")

        def is_plain_date(s: str | None) -> bool:
            return bool(s) and ("T" not in s) and (":" not in s)

        # date_from
        if is_plain_date(date_from_raw):
            d = parse_date(date_from_raw)
            if d:
                qs = qs.filter(slot__start_time__date__gte=d)
        elif date_from_raw:
            dt = parse_datetime(date_from_raw)
            if dt is None:
                raise ValidationError({"date_from": "Formato inválido."})
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            qs = qs.filter(slot__start_time__gte=dt)

        # date_to
        if is_plain_date(date_to_raw):
            d = parse_date(date_to_raw)
            if d:
                qs = qs.filter(slot__start_time__date__lte=d)
        elif date_to_raw:
            dt = parse_datetime(date_to_raw)
            if dt is None:
                raise ValidationError({"date_to": "Formato inválido."})
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            qs = qs.filter(slot__start_time__lte=dt)

        # professional_id / service_id
        professional_id = params.get("professional_id")
        if professional_id:
            qs = qs.filter(professional_id=professional_id)

        service_id = params.get("service_id")
        if service_id:
            qs = qs.filter(service_id=service_id)

        # ordering
        ordering = params.get("ordering")
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

            with transaction.atomic():
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

                with transaction.atomic():
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


class MyAppointmentsListView(ListAPIView):
    """
    Lista os agendamentos do usuário autenticado (como cliente).
    GET /api/me/appointments/
    """

    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return (
            Appointment.objects.filter(client=user)
            .select_related("client", "service", "professional", "slot")
            .order_by("-slot__start_time", "-created_at")
        )


class AppointmentDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AppointmentDetailSerializer

    def get_queryset(self):
        user = self.request.user
        # Acessível para:
        # - o próprio cliente do agendamento
        # - o salão (dono) via service.user ou professional.user
        return Appointment.objects.filter(
            Q(client=user) | Q(service__user=user) | Q(professional__user=user)
        ).select_related("client", "service", "professional", "slot")
