import os
import sys
from datetime import timedelta

from pathlib import Path
from configparser import ConfigParser

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# ---- Loader com prioridade: ENV > .env > settings.ini ----
try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*args, **kwargs) -> bool:
        return False


# Carrega .env (sem sobreescrever env já setado)
load_dotenv(BASE_DIR / ".env", override=False)


def _read_ini():
    ini_path = BASE_DIR / "settings.ini"

    if not ini_path.exists():
        return {}

    parser = ConfigParser(interpolation=None)
    parser.read(ini_path)
    data = {}

    # Mantem compatibilidade com suas seções atuais (dev/uat/prod)
    for section in parser.sections():
        for k, v in parser.items(section):
            data.setdefault(section, {})
            data[section][k.upper()] = v
    return data


INI_ALL = _read_ini()


# Helper para ler configs: pega de ENV, senão .env (já carregado), senão INI[ENV]


def env_get(name: str, default=None):
    val = os.getenv(name)
    if val is not None:
        return val
    section = os.getenv("DJANGO_ENV", "dev")
    return (INI_ALL.get(section, {}) or {}).get(name.upper(), default)


def env_int(name: str, default: int) -> int:
    v = env_get(name, default)
    try:
        return int(str(v))
    except Exception:
        return default


def env_str(name: str, default: str) -> str:
    return str(env_get(name, default))


# Define qual ambiente está sendo usado
ENV = os.getenv("DJANGO_ENV", "dev")  # dev, uat, prod

# Credencial padrão usada por seeds/smokes (configurável via env)
SMOKE_USER_PASSWORD = env_str("SMOKE_USER_PASSWORD", "Smoke@123")

# Segurança / básico
SECRET_KEY = env_get("SECRET_KEY", "dev-secret-key-change-me")
DEBUG = str(env_get("DEBUG", "false")).lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [
    h.strip()
    for h in str(env_get("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0")).split(",")
    if h.strip()
]

# Add testserver for tests
if "test" in sys.argv or "pytest" in sys.modules:
    ALLOWED_HOSTS.append("testserver")

# Captcha (Turnstile/hCaptcha)
CAPTCHA_ENABLED = str(env_get("CAPTCHA_ENABLED", "false")).lower() == "true"
CAPTCHA_SECRET_KEY = env_str("CAPTCHA_SECRET_KEY", "")
CAPTCHA_VERIFY_URL = env_str(
    "CAPTCHA_VERIFY_URL", "https://challenges.cloudflare.com/turnstile/v0/siteverify"
)
CAPTCHA_BYPASS_TOKEN = env_str("CAPTCHA_BYPASS_TOKEN", "")  # Para testes automatizados

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "django_prometheus",
    # Celery results (para admin panel - BE-ACCOUNT-CANCEL #396)
    "django_celery_results",
    # Celery beat (agendamento de tasks via Django Admin)
    "django_celery_beat",
    # APPS
    "salonix_backend",
    "core.apps.CoreConfig",
    "users",
    "ops.apps.OpsConfig",
    "notifications.apps.NotificationsConfig",
    "payments",
    "reports",
    "captcha",
    "cms",
]

# Silenciar warnings de URLField default em Django 6
FORMS_URLFIELD_ASSUME_HTTPS = True

# PWA Cliente: TTLs de token e sessão
CLIENT_PWA_INVITE_TTL_SECONDS = int(env_get("CLIENT_PWA_INVITE_TTL_SECONDS", 15 * 60))
CLIENT_PWA_SESSION_TTL_SECONDS = int(
    env_get("CLIENT_PWA_SESSION_TTL_SECONDS", 45 * 24 * 3600)
)

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "salonix_backend.middleware.RequestLoggingMiddleware",  # Logging com X-Request-ID
    "salonix_backend.middleware.SecurityHeadersMiddleware",  # Headers de segurança
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "salonix_backend.middleware.ScopeAccessMiddleware",  # Isolamento de escopos Ops/Tenant
    "core.middleware.TenantMiddleware",  # Adicionar tenant ao request
    "core.middleware.TenantIsolationMiddleware",  # Validar tenant
    "salonix_backend.middleware.LanguageNegotiationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# CORS: seguro por padrão — wildcard desativado; use CORS_ALLOWED_ORIGINS para configurar em prod
# Dev/test: fallback para lista explícita de origins locais (ver bloco abaixo)
CORS_ALLOW_ALL_ORIGINS = str(env_get("CORS_ALLOW_ALL_ORIGINS", "false")).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
origins_raw = str(env_get("CORS_ALLOWED_ORIGINS", "")).strip()
if origins_raw:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in origins_raw.split(",") if o.strip()]

try:
    from corsheaders.defaults import default_headers

    CORS_ALLOW_HEADERS = list(default_headers) + [
        "x-tenant-slug",
        "x-captcha-token",
        "x-ics-token",
    ]
except Exception:
    # Fallback seguro caso pacote mude API; permitir header custom
    CORS_ALLOW_HEADERS = [
        "x-tenant-slug",
        "x-captcha-token",
        "x-ics-token",
        "accept",
        "accept-encoding",
        "authorization",
        "content-type",
        "dnt",
        "origin",
        "user-agent",
        "x-csrftoken",
        "x-requested-with",
    ]

CORS_ALLOW_CREDENTIALS = True
# Security: wildcard + credentials viola CORS spec e pode vazar tokens
if CORS_ALLOW_CREDENTIALS and CORS_ALLOW_ALL_ORIGINS:
    CORS_ALLOW_ALL_ORIGINS = False
# Sempre definir allowlist explícita quando wildcard está desligado e nenhum env foi configurado
if not CORS_ALLOW_ALL_ORIGINS and not origins_raw:
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://salonix-frontend-web.vercel.app",
    ]
    CORS_ALLOWED_ORIGIN_REGEXES = [
        r"^https://salonix-frontend-web-.*\.vercel\.app$",
    ]

# Frontend URL para construção de links em emails (BE-ACCOUNT-CANCEL #396)
FRONTEND_URL = env_get(
    "FRONTEND_URL",
    "https://salonix-frontend-web.vercel.app" if not DEBUG else "http://localhost:5173",
)

# CSRF
csrf_origins_raw = str(env_get("CSRF_TRUSTED_ORIGINS", "")).strip()
CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_origins_raw.split(",") if o.strip()]

if not CSRF_TRUSTED_ORIGINS:
    if DEBUG:
        CSRF_TRUSTED_ORIGINS = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "https://*.ngrok-free.app",
            "https://salonix-frontend-web.vercel.app",
        ]
    elif ENV in ("staging", "uat"):
        # Fallback for staging/uat to allow main vercel app
        CSRF_TRUSTED_ORIGINS = [
            "https://salonix-frontend-web.vercel.app",
        ]

# Cookies & Security (Staging/Prod)
# Para comunicação cross-site (FE Vercel <-> BE PythonAnywhere), precisamos de SameSite=None e Secure=True
SECURE_SSL_REDIRECT = str(env_get("SECURE_SSL_REDIRECT", "false")).lower() == "true"
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT or (ENV != "dev")
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT or (ENV != "dev")

# Permitir override manual do SameSite, mas defaultar para None em Prod/UAT se for cross-site
_samesite_env = env_get("SESSION_COOKIE_SAMESITE", None)
if _samesite_env:
    SESSION_COOKIE_SAMESITE = _samesite_env
    CSRF_COOKIE_SAMESITE = _samesite_env
else:
    # Em staging/prod com domínios diferentes, precisamos de 'None'
    if ENV in ("prod", "uat", "staging"):
        SESSION_COOKIE_SAMESITE = "None"
        CSRF_COOKIE_SAMESITE = "None"
    else:
        SESSION_COOKIE_SAMESITE = "Lax"
        CSRF_COOKIE_SAMESITE = "Lax"

# Django SecurityMiddleware — flags explícitos (BE-SEC-04)
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
# CSRF_COOKIE_HTTPONLY deve ficar False — JS precisa ler o token
CSRF_COOKIE_HTTPONLY = False

# HSTS: ativar apenas em ambientes HTTPS para não quebrar dev
if ENV in ("prod", "staging", "uat"):
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)  # 1 ano
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# opcional: flag ligada por padrão
OBSERVABILITY_ENABLED = str(env_get("OBSERVABILITY_ENABLED", "true")).lower() == "true"

ROOT_URLCONF = "salonix_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "salonix_backend" / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "salonix_backend.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
DATABASE_URL = env_get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
try:
    import dj_database_url  # type: ignore

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=60)}
except Exception:
    if str(DATABASE_URL).startswith("sqlite:///"):
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(DATABASE_URL).replace("sqlite:///", ""),
            }
        }
    else:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(BASE_DIR / "db.sqlite3"),
            }
        }

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"
LANGUAGES = [
    ("pt-PT", "Português"),
    ("en", "English"),
]

TIME_ZONE = "Europe/Lisbon"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Media files (User uploads)
MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", os.path.join(BASE_DIR, "media"))

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Throttle configurável para relatórios ---
REPORTS_THROTTLE_REPORTS = env_get("REPORTS_THROTTLE_REPORTS", "60/min")
REPORTS_THROTTLE_EXPORT_CSV = env_get("REPORTS_THROTTLE_EXPORT_CSV", "5/min")
OPS_AUTH_THROTTLE_LOGIN = env_get("OPS_AUTH_THROTTLE_LOGIN", "10/min")
OPS_AUTH_THROTTLE_REFRESH = env_get("OPS_AUTH_THROTTLE_REFRESH", "60/min")

# --- Throttle de mutations de payments ---
PAYMENTS_CHECKOUT_RATE = env_get("PAYMENTS_CHECKOUT_RATE", "5/hour")
PAYMENTS_PORTAL_RATE = env_get("PAYMENTS_PORTAL_RATE", "10/hour")
PAYMENTS_CREDIT_PURCHASE_RATE = env_get("PAYMENTS_CREDIT_PURCHASE_RATE", "10/hour")
PAYMENTS_SUBSCRIPTION_ACTION_RATE = env_get(
    "PAYMENTS_SUBSCRIPTION_ACTION_RATE", "10/hour"
)
OPS_ACTION_THROTTLE_RATE = env_get("OPS_ACTION_THROTTLE_RATE", "60/min")

# REST_FRAMEWORK config
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "users.authentication.JWTVersionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # taxa geral por usuário (ajuste se quiser)
        "user": "10000/day",  # CHange back to 5000/day when go to prod
        # escopo específico para exportação CSV
        "anon": "1000/day",  # Padrão para anônimos (captcha)
        "export_csv": REPORTS_THROTTLE_EXPORT_CSV,
        # BE-RGPD-01: exportacao de dados pessoais (operacao pesada e rara)
        "data_export": env_get(
            "DATA_EXPORT_RATE",
            (
                "1000/min"
                if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
                else "5/hour"
            ),
        ),
        # escopo específico para reports
        "reports": REPORTS_THROTTLE_REPORTS,
        # password reset self-service
        "users_password_reset": env_get(
            "USERS_PASSWORD_RESET_RATE",
            (
                "20/hour"
                if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
                else "5/hour"
            ),
        ),
        # auth self-service (users) - em dev/test, deixamos alto por padrão
        "auth_login": env_get(
            "USERS_AUTH_THROTTLE_LOGIN",
            (
                "100/min"
                if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
                else "10/min"
            ),
        ),
        "auth_register": env_get(
            "USERS_AUTH_THROTTLE_REGISTER",
            (
                "100/min"
                if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
                else "5/min"
            ),
        ),
        "tenant_meta_public": env_get(
            "USERS_TENANT_META_PUBLIC",
            (
                "1000/min"
                if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
                else "1000/min"
            ),
        ),
        # staff convites e reenvio
        "users_staff_invite": env_get(
            "USERS_STAFF_INVITE_RATE",
            (
                "50/hour"
                if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
                else "10/hour"
            ),
        ),
        "users_staff_resend": env_get(
            "USERS_STAFF_RESEND_RATE",
            (
                "50/hour"
                if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
                else "10/hour"
            ),
        ),
        "clients_access_link": env_get(
            "CLIENTS_ACCESS_LINK_RATE",
            (
                "50/hour"
                if (
                    "test" in sys.argv
                    or "pytest" in sys.modules
                    or ENV in ("dev", "staging", "uat")
                )
                else "10/hour"
            ),
        ),
        "clients_me_appointments_create": env_get(
            "CLIENTS_ME_APPOINTMENTS_CREATE_RATE",
            (
                "100/hour"
                if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
                else "20/hour"
            ),
        ),
        # feedback: criação com proteção anti-spam
        "feedback_create": env_get(
            "FEEDBACK_CREATE_RATE",
            (
                "100/hour"
                if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
                else "20/hour"
            ),
        ),
        # console Ops
        "ops_auth_login": OPS_AUTH_THROTTLE_LOGIN,
        "ops_auth_refresh": OPS_AUTH_THROTTLE_REFRESH,
        # ops mutations (block/unblock tenant, reset owner, update plan)
        "ops_action": OPS_ACTION_THROTTLE_RATE,
        # payments mutations
        "payments_checkout": (
            "100/hour"
            if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
            else PAYMENTS_CHECKOUT_RATE
        ),
        "payments_portal": (
            "100/hour"
            if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
            else PAYMENTS_PORTAL_RATE
        ),
        "payments_credit_purchase": (
            "100/hour"
            if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
            else PAYMENTS_CREDIT_PURCHASE_RATE
        ),
        "payments_subscription_action": (
            "100/hour"
            if ("test" in sys.argv or "pytest" in sys.modules or ENV == "dev")
            else PAYMENTS_SUBSCRIPTION_ACTION_RATE
        ),
    },
}

REST_FRAMEWORK.setdefault("DEFAULT_SCHEMA_CLASS", "drf_spectacular.openapi.AutoSchema")
REST_FRAMEWORK["EXCEPTION_HANDLER"] = (
    "salonix_backend.error_handling.custom_exception_handler"
)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_MIN", 60)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_DAYS", 7)),
    "AUTH_HEADER_TYPES": ("Bearer",),
    # Sessao deslizante: cada refresh devolve um novo refresh com a janela de
    # REFRESH_TOKEN_LIFETIME renovada, para que um utilizador ativo nao seja
    # forcado a re-login ao fim de 7 dias do login. Afeta o refresh de staff
    # (EmailTokenRefreshSerializer -> super().validate()). O refresh de client
    # (ClientTokenRefreshView) e o de Ops fazem rotacao propria e nao dependem
    # desta flag. BLACKLIST_AFTER_ROTATION fica off (o app token_blacklist nao
    # esta instalado); invalidar refresh antigos seria um hardening separado.
    "ROTATE_REFRESH_TOKENS": True,
}

AUTH_USER_MODEL = "users.CustomUser"


# Email
# Email configuration
EMAIL_DISABLE_OUTBOUND = env_get("EMAIL_DISABLE_OUTBOUND", "false").lower() == "true"
EMAIL_BACKEND = env_get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)

# Mailgun / Anymail configuration
ANYMAIL = {
    "MAILGUN_API_KEY": env_get("MAILGUN_API_KEY", ""),
    "MAILGUN_SENDER_DOMAIN": env_get("MAILGUN_SENDER_DOMAIN", ""),
    "MAILGUN_API_URL": env_get("MAILGUN_API_URL", "https://api.mailgun.net/v3"),
}

EMAIL_HOST = env_get("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_USE_TLS = str(env_get("EMAIL_USE_TLS", "false")).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EMAIL_USE_SSL = str(env_get("EMAIL_USE_SSL", "false")).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EMAIL_HOST_USER = env_get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env_get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = env_get(
    "DEFAULT_FROM_EMAIL", "TimelyOne <timelyone@timelyone.today>"
)
# Endereço de resposta dos emails (no-reply respondível). Mailbox já existe.
EMAIL_REPLY_TO = env_get("EMAIL_REPLY_TO", "support@timelyone.today")

# Base para geração de links públicos de download de ICS
# Ex.: http://api.timelyone.com
ICS_BASE_URL = env_get("ICS_BASE_URL", "")

# Frontend URL (para redirects Stripe e links em e-mails)
FRONTEND_BASE_URL = env_get("FRONTEND_BASE_URL", "http://localhost:5173")

# Links das stores (app nativa TimelyOne) — usados nos emails. Override por env.
STORE_IOS_URL = env_get("STORE_IOS_URL", "https://apps.apple.com/app/id6760429848")
STORE_ANDROID_URL = env_get(
    "STORE_ANDROID_URL",
    "https://play.google.com/store/apps/details?id=com.timelyone.app",
)
# Base publica (absoluta) dos PNG dos badges, servidos pelos estaticos do BE (WhiteNoise).
# Em producao: https://salonix-backend-production.up.railway.app/static/email/badges
STORE_BADGES_BASE_URL = env_get(
    "STORE_BADGES_BASE_URL", "http://localhost:8000/static/email/badges"
)

# Stripe
STRIPE_API_KEY = env_get("STRIPE_API_KEY", "")
STRIPE_WEBHOOK_SECRET = env_get("STRIPE_WEBHOOK_SECRET", "")

# Prices (você já criou no Stripe; cole aqui)
STRIPE_PRICE_BASIC_MONTHLY_ID = env_get("STRIPE_PRICE_BASIC_MONTHLY_ID", "")
STRIPE_PRICE_PRO_MONTHLY_ID = env_get("STRIPE_PRICE_PRO_MONTHLY_ID", "")
STRIPE_PRICE_FOUNDER_MONTHLY_ID = env_get("STRIPE_PRICE_FOUNDER_MONTHLY_ID", "")
STRIPE_PRICE_ENTERPRISE_MONTHLY_ID = env_get("STRIPE_PRICE_ENTERPRISE_MONTHLY_ID", "")

STRIPE_PRICE_BASIC_YEARLY_ID = env_get("STRIPE_PRICE_BASIC_YEARLY_ID", "")
STRIPE_PRICE_PRO_YEARLY_ID = env_get("STRIPE_PRICE_PRO_YEARLY_ID", "")
STRIPE_PRICE_FOUNDER_YEARLY_ID = env_get("STRIPE_PRICE_FOUNDER_YEARLY_ID", "")

# ============================================
# Celery Configuration (BE-ACCOUNT-CANCEL #396)
# ============================================
CELERY_BROKER_URL = env_get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = "django-db"  # Usa django_celery_results
CELERY_RESULT_EXTENDED = True  # Armazena metadados extras (args, kwargs, etc.)
CELERY_CACHE_BACKEND = "default"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "America/Sao_Paulo"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutos max por task

# Celery Beat Schedule (Agendamento de Tasks Periódicas)
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "send-appointment-reminders-hourly": {
        "task": "notifications.tasks.send_appointment_reminders",
        "schedule": crontab(minute=0),  # Executar a cada hora cheia
    },
    "cleanup-expired-export-jobs-daily": {
        "task": "reports.cleanup_expired_export_jobs",
        "schedule": crontab(hour=3, minute=0),  # 3:00 AM diário
    },
    "update-daily-report-aggregates": {
        "task": "reports.update_daily_aggregates",
        "schedule": crontab(hour=2, minute=0),  # 2:00 AM diário
    },
    # BE-RGPD-01 / Art. 17: purga dos backups de tenant antigos (PII)
    "purge-old-tenant-backups-daily": {
        "task": "core.purge_old_tenant_backups",
        "schedule": crontab(hour=4, minute=0),  # 4:00 AM diário
    },
}

# Diretório para backups locais de tenants (BE-ACCOUNT-CANCEL #396)
# Production (Railway): /data (montado como Volume)
# Staging (PythonAnywhere): /home/username/backups
# Dev: BASE_DIR / "backups"
BACKUP_ROOT = Path(env_get("BACKUP_ROOT", str(BASE_DIR / "backups")))

# Credit packages
STRIPE_PRICE_CREDITS_5_ID = env_get("STRIPE_PRICE_CREDITS_5_ID", "")
STRIPE_PRICE_CREDITS_10_ID = env_get("STRIPE_PRICE_CREDITS_10_ID", "")
STRIPE_PRICE_CREDITS_25_ID = env_get("STRIPE_PRICE_CREDITS_25_ID", "")
STRIPE_PRICE_CREDITS_50_ID = env_get("STRIPE_PRICE_CREDITS_50_ID", "")
STRIPE_PRICE_CREDITS_100_ID = env_get("STRIPE_PRICE_CREDITS_100_ID", "")


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


STRIPE_TRIAL_PERIOD_DAYS = _safe_int(env_get("STRIPE_TRIAL_DAYS", "14"), default=0)

# URLs do front para redirecionar após checkout/portal
STRIPE_SUCCESS_URL = env_get(
    "STRIPE_SUCCESS_URL",
    "http://localhost:3000/billing/success?session_id={CHECKOUT_SESSION_ID}",
)
STRIPE_CANCEL_URL = env_get("STRIPE_CANCEL_URL", "http://localhost:3000/billing/cancel")
STRIPE_PORTAL_RETURN_URL = env_get(
    "STRIPE_PORTAL_RETURN_URL", "http://localhost:3000/billing"
)
STRIPE_API_VERSION = env_get("STRIPE_API_VERSION", "")

# Pagination limits for reports
REPORTS_PAGINATION = {
    "DEFAULT_LIMIT": env_int("REPORTS_DEFAULT_LIMIT", 50),
    "MAX_LIMIT": env_int("REPORTS_MAX_LIMIT", 500),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "TimelyOne API",
    "DESCRIPTION": "Documentação dos relatórios e demais endpoints.",
    "VERSION": "1.0.0",
    # opcional:
    # "SERVERS": [{"url": "http://localhost:8000", "description": "Local"}],
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/",
    # ENUM_NAME_OVERRIDES desativado para evitar conflitos de nomes
}

# Default tenant slug (fallback)
DEFAULT_TENANT_SLUG = str(env_get("DEFAULT_TENANT_SLUG", "timelyone")).strip().lower()

# Retenção RGPD de feedbacks (em dias)
FEEDBACK_RETENTION_DAYS = env_int("FEEDBACK_RETENTION_DAYS", 365)

# =====================================================
# LOGGING CONFIGURATION
# =====================================================

# Nível de log base
LOG_LEVEL = env_get("LOG_LEVEL", "INFO")

# Formato de log (json para produção, dev para desenvolvimento)
LOG_FORMAT = env_get("LOG_FORMAT", "dev" if DEBUG else "json")

# Arquivo de log (opcional)
LOG_FILE = env_get("LOG_FILE", "")

# Configuração de logging estruturado
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    # Formatadores
    "formatters": {
        "json": {
            "()": "salonix_backend.logging_utils.JSONFormatter",
        },
        "dev": {
            "()": "salonix_backend.logging_utils.DevelopmentFormatter",
        },
        "simple": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    # Filtros
    "filters": {
        "request_context": {
            "()": "salonix_backend.logging_utils.RequestContextFilter",
        },
    },
    # Handlers
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT,
            "filters": ["request_context"],
            "level": LOG_LEVEL,
        },
    },
    # Loggers específicos
    "loggers": {
        # Logger raiz do projeto
        "salonix_backend": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        # Apps específicos
        "core": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "users": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "reports": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "notifications": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "payments": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        # Django internos
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",  # Apenas warnings e erros
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING" if not DEBUG else "DEBUG",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # Bibliotecas externas
        "stripe": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "requests": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
    # Logger raiz (fallback)
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
}

# Adicionar handler de arquivo se especificado
if LOG_FILE:
    LOGGING["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": LOG_FILE,
        "maxBytes": 10 * 1024 * 1024,  # 10MB
        "backupCount": 5,
        "formatter": "json",
        "filters": ["request_context"],
        "level": LOG_LEVEL,
    }

    # Adicionar file handler a todos os loggers
    for logger_name in LOGGING["loggers"]:
        LOGGING["loggers"][logger_name]["handlers"].append("file")
    LOGGING["root"]["handlers"].append("file")

# =====================================================
# CACHE CONFIGURATION (Redis + Fallbacks)
# =====================================================

# Cache URL: redis://host:port/db ou locmem:// para desenvolvimento
CACHE_URL: str = env_str("CACHE_URL", "locmem://")

# Configuração Redis (produção recomendada)
if CACHE_URL.startswith("redis://"):
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": CACHE_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "CONNECTION_POOL_KWARGS": {
                    "retry_on_timeout": True,
                    "socket_connect_timeout": 5,
                    "socket_timeout": 5,
                    "max_connections": 50,
                },
                "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor",
                "IGNORE_EXCEPTIONS": True,  # Graceful fallback em caso de erro Redis
            },
            "KEY_PREFIX": "salonix",
            "TIMEOUT": 300,  # 5 minutos por padrão
            "VERSION": 1,
        }
    }

    # Cache para sessões (opcional, melhora performance)
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"
    SESSION_CACHE_ALIAS = "default"

# Configuração Local Memory (desenvolvimento/fallback)
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "salonix-cache",
            "TIMEOUT": 300,  # 5 minutos por padrão
            "OPTIONS": {
                "MAX_ENTRIES": 1000,
                "CULL_FREQUENCY": 3,
            },
        }
    }

# --- TTLs de cache por endpoint (em segundos) ---
REPORTS_CACHE_TTL = {
    "overview_json": env_int("TTL_OVERVIEW_JSON", 30),
    "top_services_json": env_int("TTL_TOP_SERVICES_JSON", 30),
    "revenue_json": env_int("TTL_REVENUE_JSON", 30),
    "overview_csv": env_int("TTL_OVERVIEW_CSV", 60),
    "top_services_csv": env_int("TTL_TOP_SERVICES_CSV", 60),
    "revenue_csv": env_int("TTL_REVENUE_CSV", 60),
}

# --- CAPTCHA (self-service) ---
CAPTCHA_ENABLED = str(env_get("CAPTCHA_ENABLED", "false")).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Configurações do django-simple-captcha
CAPTCHA_FONT_SIZE = 30
CAPTCHA_LETTER_ROTATION = (-35, 35)
CAPTCHA_BACKGROUND_COLOR = "#ffffff"
CAPTCHA_FOREGROUND_COLOR = "#001100"
CAPTCHA_CHALLENGE_FUNCT = "captcha.helpers.random_char_challenge"
CAPTCHA_NOISE_FUNCTIONS = (
    "captcha.helpers.noise_arcs",
    "captcha.helpers.noise_dots",
)
CAPTCHA_LENGTH = 5
CAPTCHA_TIMEOUT = 5  # Minutos

# Bypass para dev/smoke: se definido e token igual, considera válido
CAPTCHA_BYPASS_TOKEN = env_get("CAPTCHA_BYPASS_TOKEN", "")

# ============================================
# Celery Configuration (BE-ACCOUNT-CANCEL #396)
# ============================================
CELERY_BROKER_URL = env_get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = "django-db"  # Usa django_celery_results
CELERY_RESULT_EXTENDED = True  # Armazena metadados extras (args, kwargs, etc.)
CELERY_CACHE_BACKEND = "default"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE  # Usa o mesmo timezone do Django
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutos max por task

# django-celery-beat: scheduler no banco de dados
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"


# Twilio (SMS)
TWILIO_ACCOUNT_SID = env_get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = env_get("TWILIO_AUTH_TOKEN", "")
TWILIO_MESSAGING_SERVICE_SID = env_get("TWILIO_MESSAGING_SERVICE_SID", "")
SMS_ENABLED = str(env_get("SMS_ENABLED", "false")).lower() == "true"
