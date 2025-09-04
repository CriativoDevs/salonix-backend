from django.contrib import admin
from django.contrib.admin import AdminSite
from users.models import Tenant, CustomUser, UserFeatureFlags
from core.models import Service, Professional, ScheduleSlot, Appointment
from payments.models import PaymentCustomer, Subscription
from notifications.models import Notification, NotificationDevice, NotificationLog

# Importar as classes admin personalizadas
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


class SimpleAdminSite(AdminSite):
    """
    Site Admin simples mas com ModelAdmin personalizados.
    """

    site_title = "Salonix Admin"
    site_header = "🏢 Salonix - Gestão de Salões"
    index_title = "Dashboard de Administração"


# Instância simples do admin
simple_admin_site = SimpleAdminSite(name="simple_admin")

# Registrar modelos com suas classes admin personalizadas
simple_admin_site.register(Tenant, TenantAdmin)
simple_admin_site.register(CustomUser, CustomUserAdmin)
simple_admin_site.register(UserFeatureFlags, UserFeatureFlagsAdmin)
simple_admin_site.register(Service, ServiceAdmin)
simple_admin_site.register(Professional, ProfessionalAdmin)
simple_admin_site.register(ScheduleSlot, ScheduleSlotAdmin)
simple_admin_site.register(Appointment, AppointmentAdmin)
simple_admin_site.register(PaymentCustomer, PaymentCustomerAdmin)
simple_admin_site.register(Subscription, SubscriptionAdmin)
simple_admin_site.register(Notification, NotificationAdmin)
simple_admin_site.register(NotificationDevice, NotificationDeviceAdmin)
simple_admin_site.register(NotificationLog, NotificationLogAdmin)
