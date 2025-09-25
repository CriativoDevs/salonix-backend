from rest_framework import serializers


class CheckoutSessionRequestSerializer(serializers.Serializer):
    plan = serializers.ChoiceField(
        choices=["basic", "standard", "pro", "enterprise"],
        required=False,
        help_text="Plano desejado",
    )


class CheckoutSessionResponseSerializer(serializers.Serializer):
    checkout_url = serializers.URLField()


class PortalSessionResponseSerializer(serializers.Serializer):
    portal_url = serializers.URLField()
