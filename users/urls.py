from django.urls import path
from rest_framework_simplejwt.views import (
    TokenRefreshView,
)
from .views import (
    UserRegistrationView,
    MeFeatureFlagsView,
    EmailTokenObtainPairView,
    TenantMetaView,
    MeTenantView,
    MeProfileView,
    TenantStaffView,
    TenantStaffResendInviteView,
    TenantStaffAccessLinkView,
    TenantStaffContactUpdateView,
    TenantStaffAcceptInviteView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    CreditBalanceView,
    CreditHistoryView,
    ConsumeCreditsView,
    PurchaseCreditsView,
    RealtimeCreditsSSEView,
    TenantNotificationsSettingsView,
    TenantModulesSettingsView,
)

urlpatterns = [
    path("register/", UserRegistrationView.as_view(), name="register"),
    path("me/profile/", MeProfileView.as_view(), name="me_profile"),
    path("staff/", TenantStaffView.as_view(), name="tenant_staff"),
    path(
        "staff/resend/",
        TenantStaffResendInviteView.as_view(),
        name="tenant_staff_resend",
    ),
    path(
        "staff/access-link/",
        TenantStaffAccessLinkView.as_view(),
        name="tenant_staff_access_link",
    ),
    path(
        "staff/contact/",
        TenantStaffContactUpdateView.as_view(),
        name="tenant_staff_contact_update",
    ),
    path(
        "staff/accept/",
        TenantStaffAcceptInviteView.as_view(),
        name="tenant_staff_accept",
    ),
    path("me/features/", MeFeatureFlagsView.as_view(), name="me_feature_flags"),
    path("me/tenant/", MeTenantView.as_view(), name="me_tenant"),
    path("tenant/meta/", TenantMetaView.as_view(), name="tenant_meta"),
    path("token/", EmailTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("password/reset/", PasswordResetRequestView.as_view(), name="password_reset"),
    path(
        "password/reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    # Credit management endpoints
    path("credits/balance/", CreditBalanceView.as_view(), name="credit_balance"),
    path("credits/history/", CreditHistoryView.as_view(), name="credit_history"),
    path("credits/consume/", ConsumeCreditsView.as_view(), name="consume_credits"),
    path("credits/purchase/", PurchaseCreditsView.as_view(), name="purchase_credits"),
    # Realtime SSE
    path(
        "realtime/credits/", RealtimeCreditsSSEView.as_view(), name="realtime_credits"
    ),
    path(
        "tenant/notifications/",
        TenantNotificationsSettingsView.as_view(),
        name="tenant_notifications_settings",
    ),
    path(
        "tenant/modules/",
        TenantModulesSettingsView.as_view(),
        name="tenant_modules_settings",
    ),
]
