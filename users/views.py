from rest_framework import generics
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import UserFeatureFlags

from .serializers import (
    EmailTokenObtainPairSerializer,
    UserRegistrationSerializer,
    UserFeatureFlagsSerializer,
    UserFeatureFlagsUpdateSerializer,
)


class UserRegistrationView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]


class MeFeatureFlagsView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserFeatureFlagsSerializer  # default para GET

    def get_object(self):
        flags, _ = UserFeatureFlags.objects.get_or_create(user=self.request.user)
        return flags

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return UserFeatureFlagsUpdateSerializer
        return UserFeatureFlagsSerializer


class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer
