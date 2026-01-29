from django.urls import path, include

from rest_framework.routers import DefaultRouter

from core.views import (
    AppointmentCancelView,
    AppointmentCreateView,
    AppointmentDetailView,
    AppointmentICSDownloadView,
    AppointmentICSDownloadPublicView,
    AppointmentSeriesOccurrenceCancelView,
    BulkAppointmentCreateView,
    MixedBulkAppointmentCreateView,
    MyAppointmentsListView,
    AppointmentSeriesCreateView,
    AppointmentSeriesDetailView,
    ProfessionalViewSet,
    PublicServiceListView,
    PublicProfessionalListView,
    PublicSlotListView,
    SalonAppointmentViewSet,
    SalonCustomerViewSet,
    ServiceViewSet,
    ScheduleSlotViewSet,
    ClientAccessLinkView,
    ClientAccessAcceptView,
    ClientLoginView,
    ClientSetPasswordView,
    PublicClientAccessLinkView,
    ClientsMeAppointmentsUpcomingView,
    ClientsMeAppointmentsHistoryView,
    ClientsMeAppointmentCreateView,
    ClientsMeProfileView,
    ClientAppointmentCancelView,
    FeedbackListCreateView,
    FeedbackDetailView,
    FeedbackExportView,
    FeedbackPurgeByCustomerView,
    FeedbackRetentionEnforceView,
    ImportCustomersCSVView,
    ImportServicesCSVView,
    ImportStaffCSVView,
    ImportAppointmentsCSVView,
    ImportTemplateCSVView,
    ExportCustomersCSVView,
    ExportServicesCSVView,
    ExportStaffCSVView,
)

router = DefaultRouter()
router.register("services", ServiceViewSet, basename="service")
router.register("professionals", ProfessionalViewSet, basename="professional")
router.register("slots", ScheduleSlotViewSet, basename="slot")
router.register(
    "salon/appointments", SalonAppointmentViewSet, basename="salon-appointments"
)
router.register("salon/customers", SalonCustomerViewSet, basename="salon-customers")

urlpatterns = [
    path("", include(router.urls)),
    path("auth/", include("users.urls")),
    path(
        "clients/access-link/",
        ClientAccessLinkView.as_view(),
        name="clients_access_link",
    ),
    path(
        "clients/access-accept/",
        ClientAccessAcceptView.as_view(),
        name="clients_access_accept",
    ),
    path(
        "clients/login/",
        ClientLoginView.as_view(),
        name="clients_login",
    ),
    path(
        "clients/set-password/",
        ClientSetPasswordView.as_view(),
        name="clients_set_password",
    ),
    # Cliente autenticado via cookie de sessão
    path(
        "clients/me/appointments/upcoming/",
        ClientsMeAppointmentsUpcomingView.as_view(),
        name="clients_me_appointments_upcoming",
    ),
    path(
        "clients/me/appointments/history/",
        ClientsMeAppointmentsHistoryView.as_view(),
        name="clients_me_appointments_history",
    ),
    path(
        "clients/me/appointments/",
        ClientsMeAppointmentCreateView.as_view(),
        name="clients_me_appointments_create",
    ),
    path(
        "clients/me/profile/",
        ClientsMeProfileView.as_view(),
        name="clients_me_profile",
    ),
    path(
        "clients/me/appointments/<int:pk>/cancel/",
        ClientAppointmentCancelView.as_view(),
        name="clients_me_appointment_cancel",
    ),
    # Public routes
    path(
        "public/clients/access-link/",
        PublicClientAccessLinkView.as_view(),
        name="public_clients_access_link",
    ),
    path("public/services/", PublicServiceListView.as_view()),
    path("public/professionals/", PublicProfessionalListView.as_view()),
    path("public/slots/", PublicSlotListView.as_view()),
    path(
        "public/appointments/<int:pk>/ics/",
        AppointmentICSDownloadPublicView.as_view(),
        name="appointment-ics-download-public",
    ),
    path("appointments/", AppointmentCreateView.as_view(), name="appointment-create"),
    path(
        "appointments/bulk/",
        BulkAppointmentCreateView.as_view(),
        name="appointment-bulk-create",
    ),
    path(
        "appointments/bulk/mixed/",
        MixedBulkAppointmentCreateView.as_view(),
        name="appointment-mixed-bulk-create",
    ),
    path(
        "appointments/series/",
        AppointmentSeriesCreateView.as_view(),
        name="appointment-series-create",
    ),
    path(
        "appointments/series/<int:pk>/",
        AppointmentSeriesDetailView.as_view(),
        name="appointment-series-detail",
    ),
    path(
        "appointments/series/<int:series_id>/occurrence/<int:occurrence_id>/cancel/",
        AppointmentSeriesOccurrenceCancelView.as_view(),
        name="appointment-series-occurrence-cancel",
    ),
    path(
        "appointments/<int:pk>/cancel/",
        AppointmentCancelView.as_view(),
        name="appointment-cancel",
    ),
    # meu histórico como cliente
    path("me/appointments/", MyAppointmentsListView.as_view(), name="my-appointments"),
    path(
        "appointments/<int:pk>/",
        AppointmentDetailView.as_view(),
        name="appointment-detail",
    ),
    # Download .ics calendar file
    path(
        "appointments/<int:pk>/ics/",
        AppointmentICSDownloadView.as_view(),
        name="appointment-ics-download",
    ),
    # Feedback
    path("feedbacks/", FeedbackListCreateView.as_view(), name="feedback-list-create"),
    path("feedbacks/<int:pk>/", FeedbackDetailView.as_view(), name="feedback-detail"),
    path("feedbacks/export/", FeedbackExportView.as_view(), name="feedback-export"),
    path(
        "feedbacks/purge/<int:customer_id>/",
        FeedbackPurgeByCustomerView.as_view(),
        name="feedback-purge-by-customer",
    ),
    path(
        "feedbacks/retention/enforce/",
        FeedbackRetentionEnforceView.as_view(),
        name="feedback-retention-enforce",
    ),
    path(
        "import/customers/", ImportCustomersCSVView.as_view(), name="import-customers"
    ),
    path("import/services/", ImportServicesCSVView.as_view(), name="import-services"),
    path("import/staff/", ImportStaffCSVView.as_view(), name="import-staff"),
    path(
        "import/appointments/",
        ImportAppointmentsCSVView.as_view(),
        name="import-appointments",
    ),
    path(
        "import/templates/<str:entity>.csv",
        ImportTemplateCSVView.as_view(),
        name="import-template",
    ),
    # Export CSV
    path(
        "export/customers.csv",
        ExportCustomersCSVView.as_view(),
        name="export-customers",
    ),
    path(
        "export/services.csv", ExportServicesCSVView.as_view(), name="export-services"
    ),
    path("export/staff.csv", ExportStaffCSVView.as_view(), name="export-staff"),
]
