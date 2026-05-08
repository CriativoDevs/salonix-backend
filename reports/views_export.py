import logging
import os

from django.conf import settings
from django.http import FileResponse, Http404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes

from reports.models import ExportJob
from reports.views import RequiresBasicReports, RequiresProReports
from reports.tasks import generate_csv_export

logger = logging.getLogger("reports")

PRO_REPORT_TYPES = {
    ExportJob.ReportType.TOP_SERVICES,
    ExportJob.ReportType.REVENUE,
    ExportJob.ReportType.ADVANCED,
}


def _permission_for_type(report_type: str):
    if report_type in PRO_REPORT_TYPES:
        return RequiresProReports()
    return RequiresBasicReports()


@extend_schema(
    tags=["Reports - Async Export"],
    summary="Inicia export assíncrono de CSV",
    request={
        "application/json": {
            "type": "object",
            "required": ["report_type"],
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": [c.value for c in ExportJob.ReportType],
                    "example": "basic",
                },
                "from": {
                    "type": "string",
                    "format": "date-time",
                    "example": "2026-01-01T00:00:00Z",
                },
                "to": {
                    "type": "string",
                    "format": "date-time",
                    "example": "2026-01-31T23:59:59Z",
                },
            },
        }
    },
    responses={
        202: {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "format": "uuid"},
                "status": {"type": "string", "example": "pending"},
                "report_type": {"type": "string"},
            },
        },
        400: OpenApiTypes.OBJECT,
        403: OpenApiTypes.OBJECT,
    },
)
class ExportJobCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        report_type = request.data.get("report_type", "").strip()

        valid_types = [c.value for c in ExportJob.ReportType]
        if report_type not in valid_types:
            return Response(
                {"detail": f"report_type inválido. Opções: {valid_types}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        perm = _permission_for_type(report_type)
        if not perm.has_permission(request, self):
            return Response(
                {"detail": "Plano atual não permite este tipo de export."},
                status=status.HTTP_403_FORBIDDEN,
            )

        parameters = {}
        if "from" in request.data:
            parameters["from"] = request.data["from"]
        if "to" in request.data:
            parameters["to"] = request.data["to"]

        job = ExportJob.objects.create(
            tenant=request.user.tenant,
            requested_by=request.user,
            report_type=report_type,
            parameters=parameters,
        )

        logger.info(
            "export_job_created",
            extra={
                "job_id": str(job.id),
                "report_type": report_type,
                "tenant_id": request.user.tenant_id,
                "user_id": request.user.id,
            },
        )

        generate_csv_export.delay(str(job.id))

        return Response(
            {
                "job_id": str(job.id),
                "status": job.status,
                "report_type": job.report_type,
            },
            status=status.HTTP_202_ACCEPTED,
        )


def _get_owned_job(request, job_id):
    """Retorna o job garantindo isolamento por tenant. Lança Http404 se não encontrado."""
    try:
        return ExportJob.objects.get(id=job_id, tenant=request.user.tenant)
    except (ExportJob.DoesNotExist, ValueError):
        raise Http404


def _job_payload(job, request):
    payload = {
        "job_id": str(job.id),
        "status": job.status,
        "report_type": job.report_type,
        "created_at": job.created_at,
        "expires_at": job.expires_at,
        "download_url": None,
        "error_message": job.error_message or None,
    }
    if job.status == ExportJob.Status.DONE and job.file_path and not job.is_expired:
        payload["download_url"] = request.build_absolute_uri(
            f"/api/reports/exports/{job.id}/download/"
        )
    return payload


@extend_schema(
    tags=["Reports - Async Export"],
    summary="Consulta status de um export job",
    responses={
        200: {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "format": "uuid"},
                "status": {"type": "string", "enum": ["pending", "processing", "done", "failed"]},
                "report_type": {"type": "string"},
                "created_at": {"type": "string", "format": "date-time"},
                "expires_at": {"type": "string", "format": "date-time"},
                "download_url": {"type": "string", "nullable": True},
                "error_message": {"type": "string", "nullable": True},
            },
        },
        404: OpenApiTypes.OBJECT,
    },
)
class ExportJobStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        job = _get_owned_job(request, job_id)
        return Response(_job_payload(job, request))


@extend_schema(
    tags=["Reports - Async Export"],
    summary="Download do CSV gerado pelo export job",
    responses={
        200: {"type": "string", "format": "binary"},
        404: OpenApiTypes.OBJECT,
        410: OpenApiTypes.OBJECT,
    },
)
class ExportJobDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        job = _get_owned_job(request, job_id)

        if job.status != ExportJob.Status.DONE or not job.file_path:
            return Response(
                {"detail": "Export ainda não está disponível."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if job.is_expired:
            return Response(
                {"detail": "Export expirado. Solicite um novo."},
                status=status.HTTP_410_GONE,
            )

        abs_path = os.path.join(settings.MEDIA_ROOT, job.file_path)
        if not os.path.exists(abs_path):
            return Response(
                {"detail": "Arquivo não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        filename = os.path.basename(abs_path)
        response = FileResponse(
            open(abs_path, "rb"),
            content_type="text/csv",
            as_attachment=True,
            filename=filename,
        )
        return response
