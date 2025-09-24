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
)

urlpatterns = [
    path("register/", UserRegistrationView.as_view(), name="register"),
    path("me/features/", MeFeatureFlagsView.as_view(), name="me_feature_flags"),
    path("me/tenant/", MeTenantView.as_view(), name="me_tenant"),
    path("tenant/meta/", TenantMetaView.as_view(), name="tenant_meta"),
    path("token/", EmailTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
