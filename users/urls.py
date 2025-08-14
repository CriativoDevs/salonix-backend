from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from .views import UserRegistrationView, MeFeatureFlagsView

urlpatterns = [
    path("register/", UserRegistrationView.as_view(), name="register"),
    path("me/features/", MeFeatureFlagsView.as_view(), name="me_feature_flags"),
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
