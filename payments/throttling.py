from users.throttling import _BaseUsersThrottle


class PaymentsCheckoutThrottle(_BaseUsersThrottle):
    """Throttle para criação de checkout sessions (assinatura)."""

    scope = "payments_checkout"


class PaymentsPortalThrottle(_BaseUsersThrottle):
    """Throttle para abertura de portal de billing."""

    scope = "payments_portal"


class PaymentsCreditPurchaseThrottle(_BaseUsersThrottle):
    """Throttle para criação de payment intents / checkout sessions de crédito."""

    scope = "payments_credit_purchase"


class PaymentsSubscriptionActionThrottle(_BaseUsersThrottle):
    """Throttle para ações de assinatura (cancelar/reativar) e updates de settings."""

    scope = "payments_subscription_action"
