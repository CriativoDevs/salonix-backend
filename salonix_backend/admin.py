from django.contrib import admin
from django.contrib.admin import AdminSite
from django.template.response import TemplateResponse
from django.urls import path
from django.db.models import Count, Q
from django.utils.html import format_html
from django.urls import reverse
from users.models import Tenant, CustomUser
from core.models import Appointment, Service, Professional
from notifications.models import Notification, NotificationLog
from payments.models import Subscription
from datetime import datetime, timedelta


class SalonixAdminSite(AdminSite):
    """
    Site Admin personalizado do Salonix com dashboard estatístico.
    """

    site_title = "Salonix Admin"
    site_header = "🏢 Salonix - Gestão de Salões"
    index_title = "Dashboard de Administração"

    def get_urls(self):
        """Adiciona URLs personalizadas ao admin."""
        urls = super().get_urls()
        custom_urls = [
            path("dashboard/", self.admin_view(self.dashboard_view), name="dashboard"),
        ]
        return custom_urls + urls

    def index(self, request, extra_context=None):
        """
        Dashboard personalizado com estatísticas e alertas.
        """
        extra_context = extra_context or {}

        try:
            # Usar métodos seguros para obter dados
            stats = self._get_general_stats()
            top_tenants = list(self._get_top_tenants())
            recent_activity = self._get_recent_activity()
            alerts = self._get_system_alerts()

            extra_context.update(
                {
                    "stats": stats,
                    "top_tenants": top_tenants,
                    "recent_activity": recent_activity,
                    "alerts": alerts,
                }
            )
        except Exception as e:
            # Log do erro para debugging
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Erro no dashboard admin: {e}")

            # Fallback seguro
            extra_context.update(
                {
                    "stats": {
                        "total_tenants": 0,
                        "total_users": 0,
                        "total_appointments_today": 0,
                        "total_appointments_week": 0,
                        "active_subscriptions": 0,
                        "notifications_sent_today": 0,
                    },
                    "top_tenants": [],
                    "recent_activity": [],
                    "alerts": [],
                }
            )

        return super().index(request, extra_context)

    def dashboard_view(self, request):
        """
        View personalizada para dashboard detalhado.
        """
        context = {
            "title": "Dashboard Detalhado",
            "stats": self._get_detailed_stats(),
            "charts_data": self._get_charts_data(),
        }

        return TemplateResponse(request, "admin/dashboard.html", context)

    def _get_general_stats(self):
        """Retorna estatísticas gerais do sistema."""
        try:
            today = datetime.now().date()
            week_ago = today - timedelta(days=7)

            return {
                "total_tenants": Tenant.objects.filter(is_active=True).count(),
                "total_users": CustomUser.objects.count(),
                "total_appointments_today": Appointment.objects.filter(
                    slot__start_time__date=today
                ).count(),
                "total_appointments_week": Appointment.objects.filter(
                    slot__start_time__date__gte=week_ago
                ).count(),
                "active_subscriptions": Subscription.objects.filter(
                    status="active"
                ).count(),
                "notifications_sent_today": NotificationLog.objects.filter(
                    sent_at__date=today, status="sent"
                ).count(),
            }
        except Exception as e:
            # Em caso de erro, retornar estatísticas vazias
            return {
                "total_tenants": 0,
                "total_users": 0,
                "total_appointments_today": 0,
                "total_appointments_week": 0,
                "active_subscriptions": 0,
                "notifications_sent_today": 0,
            }

    def _get_top_tenants(self):
        """Retorna top 5 tenants por atividade."""
        try:
            week_ago = datetime.now().date() - timedelta(days=7)

            return (
                Tenant.objects.annotate(
                    appointments_count=Count(
                        "appointments",
                        filter=Q(appointments__slot__start_time__date__gte=week_ago),
                    ),
                    users_count=Count("users"),
                )
                .filter(is_active=True)
                .order_by("-appointments_count")[:5]
            )
        except Exception as e:
            return Tenant.objects.none()

    def _get_recent_activity(self):
        """Retorna atividade recente do sistema."""
        activities = []

        # Novos tenants (últimos 7 dias)
        week_ago = datetime.now() - timedelta(days=7)
        new_tenants = Tenant.objects.filter(created_at__gte=week_ago).order_by(
            "-created_at"
        )[:3]

        for tenant in new_tenants:
            activities.append(
                {
                    "type": "new_tenant",
                    "message": f"Novo tenant: {tenant.name}",
                    "timestamp": tenant.created_at,
                    "url": reverse("admin:users_tenant_change", args=[tenant.pk]),
                }
            )

        # Agendamentos recentes
        recent_appointments = Appointment.objects.select_related(
            "tenant", "client", "service"
        ).order_by("-created_at")[:3]

        for appointment in recent_appointments:
            activities.append(
                {
                    "type": "appointment",
                    "message": f"Agendamento: {appointment.client.username} - {appointment.service.name}",
                    "timestamp": appointment.created_at,
                    "url": reverse(
                        "admin:core_appointment_change", args=[appointment.pk]
                    ),
                }
            )

        return sorted(activities, key=lambda x: x["timestamp"], reverse=True)[:5]

    def _get_system_alerts(self):
        """Retorna alertas do sistema."""
        alerts = []

        # Tenants sem assinatura ativa
        tenants_no_subscription = (
            Tenant.objects.filter(is_active=True, users__subscriptions__isnull=True)
            .distinct()
            .count()
        )

        if tenants_no_subscription > 0:
            alerts.append(
                {
                    "type": "warning",
                    "message": f"{tenants_no_subscription} tenant(s) sem assinatura ativa",
                    "url": reverse("admin:users_tenant_changelist")
                    + "?subscriptions__isnull=True",
                }
            )

        # Notificações falhadas (último dia)
        yesterday = datetime.now() - timedelta(days=1)
        failed_notifications = NotificationLog.objects.filter(
            status="failed", sent_at__gte=yesterday
        ).count()

        if failed_notifications > 0:
            alerts.append(
                {
                    "type": "error",
                    "message": f"{failed_notifications} notificação(ões) falharam nas últimas 24h",
                    "url": reverse("admin:notifications_notificationlog_changelist")
                    + "?status=failed",
                }
            )

        return alerts

    def _get_detailed_stats(self):
        """Estatísticas detalhadas para dashboard."""
        # Implementar estatísticas mais detalhadas aqui
        return {}

    def _get_charts_data(self):
        """Dados para gráficos do dashboard."""
        # Implementar dados para gráficos aqui
        return {}


# Instância personalizada do admin
admin_site = SalonixAdminSite(name="salonix_admin")

# Registrar todos os modelos no admin personalizado
from users.admin import TenantAdmin, CustomUserAdmin, UserFeatureFlagsAdmin
from core.admin import (
    ServiceAdmin,
    ProfessionalAdmin,
    ScheduleSlotAdmin,
    AppointmentAdmin,
)
from payments.admin import PaymentCustomerAdmin, SubscriptionAdmin
from notifications.admin import (
    NotificationAdmin,
    NotificationDeviceAdmin,
    NotificationLogAdmin,
)

# Registrar modelos
from users.models import UserFeatureFlags

admin_site.register(Tenant, TenantAdmin)
admin_site.register(CustomUser, CustomUserAdmin)
admin_site.register(UserFeatureFlags, UserFeatureFlagsAdmin)

from core.models import Service, Professional, ScheduleSlot, Appointment

admin_site.register(Service, ServiceAdmin)
admin_site.register(Professional, ProfessionalAdmin)
admin_site.register(ScheduleSlot, ScheduleSlotAdmin)
admin_site.register(Appointment, AppointmentAdmin)

from payments.models import PaymentCustomer, Subscription

admin_site.register(PaymentCustomer, PaymentCustomerAdmin)
admin_site.register(Subscription, SubscriptionAdmin)

from notifications.models import Notification, NotificationDevice, NotificationLog

admin_site.register(Notification, NotificationAdmin)
admin_site.register(NotificationDevice, NotificationDeviceAdmin)
admin_site.register(NotificationLog, NotificationLogAdmin)
