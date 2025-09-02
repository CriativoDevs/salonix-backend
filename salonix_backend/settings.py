import os

from pathlib import Path
from configparser import ConfigParser

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# ---- Loader com prioridade: ENV > .env > settings.ini ----
try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*args, **kwargs):
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


# Define qual ambiente está sendo usado
ENV = os.getenv("DJANGO_ENV", "dev")  # dev, uat, prod

# Segurança / básico
SECRET_KEY = env_get("SECRET_KEY", "dev-secret-key-change-me")
DEBUG = str(env_get("DEBUG", "false")).lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [
    h.strip()
    for h in str(env_get("ALLOWED_HOSTS", "localhost,127.0.0.1")).split(",")
    if h.strip()
]

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
    # APPS
    "core.apps.CoreConfig",
    "users",
    "payments",
    "reports",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "salonix_backend.middleware.RequestIDMiddleware",
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.TenantMiddleware",  # Adicionar tenant ao request
    "core.middleware.TenantIsolationMiddleware",  # Validar tenant
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CORS_ALLOW_ALL_ORIGINS = True

# opcional: flag ligada por padrão
OBSERVABILITY_ENABLED = str(env_get("OBSERVABILITY_ENABLED", "true")).lower() == "true"

ROOT_URLCONF = "salonix_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
DATABASE_URL = env_get("DATABASE_URL", f"sqlite:///{BASE_DIR/'db.sqlite3'}")
try:
    import dj_database_url  # type: ignore

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
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

TIME_ZONE = "Europe/Lisbon"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = os.path.join(BASE_DIR, "static")

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Throttle configurável para relatórios ---
REPORTS_THROTTLE_REPORTS = env_get("REPORTS_THROTTLE_REPORTS", "60/min")
REPORTS_THROTTLE_EXPORT_CSV = env_get("REPORTS_THROTTLE_EXPORT_CSV", "5/min")

# REST_FRAMEWORK config
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
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
        "user": "1000/day",
        # escopo específico para exportação CSV
        "export_csv": REPORTS_THROTTLE_EXPORT_CSV,
        # escopo específico para reports
        "reports": REPORTS_THROTTLE_REPORTS,
    },
}

REST_FRAMEWORK.setdefault("DEFAULT_SCHEMA_CLASS", "drf_spectacular.openapi.AutoSchema")

from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env_get("JWT_ACCESS_MIN", 60))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(env_get("JWT_REFRESH_DAYS", 7))),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

AUTH_USER_MODEL = "users.CustomUser"


# Email
# Email configuration
EMAIL_BACKEND = env_get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = env_get("EMAIL_HOST", "")
EMAIL_PORT = int(env_get("EMAIL_PORT", "25"))
EMAIL_USE_TLS = str(env_get("EMAIL_USE_TLS", "false")).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EMAIL_HOST_USER = env_get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env_get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = env_get("DEFAULT_FROM_EMAIL", "no-reply@localhost")

# Stripe
STRIPE_API_KEY = env_get("STRIPE_API_KEY", "")
STRIPE_WEBHOOK_SECRET = env_get("STRIPE_WEBHOOK_SECRET", "")

# Prices (você já criou no Stripe; cole aqui)
STRIPE_PRICE_MONTHLY_ID = env_get("STRIPE_PRICE_MONTHLY_ID", "")
STRIPE_PRICE_YEARLY_ID = env_get("STRIPE_PRICE_YEARLY_ID", "")

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
    "DEFAULT_LIMIT": int(env_get("REPORTS_DEFAULT_LIMIT", "50")),
    "MAX_LIMIT": int(env_get("REPORTS_MAX_LIMIT", "500")),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Salonix API",
    "DESCRIPTION": "Documentação dos relatórios e demais endpoints.",
    "VERSION": "1.0.0",
    # opcional:
    # "SERVERS": [{"url": "http://localhost:8000", "description": "Local"}],
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/",
}

LOG_LEVEL = env_get("LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "kv": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s"
            "msg=%(message)s request_id=%(request_id)s endpoint=%(endpoint)s "
            "user_id=%(user_id)s is_pro=%(is_pro)s"
        },
    },
    "filters": {
        "request_context": {
            "()": "django.utils.log.CallbackFilter",
            "callback": lambda record: True,  # manter simples
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "kv",
            "filters": ["request_context"],
        },
    },
    "loggers": {
        "reports": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}

# --- Cache backend (CACHE_URL: locmem:// ou redis://host:port/db) ---
CACHE_URL = env_get("CACHE_URL", "locmem://")
if CACHE_URL.startswith("redis://"):
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": CACHE_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
            "KEY_PREFIX": "salonix",
            "TIMEOUT": None,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "salonix-cache",
            "TIMEOUT": None,
        }
    }

# --- TTLs de cache por endpoint (em segundos) ---
REPORTS_CACHE_TTL = {
    "overview_json": int(env_get("TTL_OVERVIEW_JSON", "30")),
    "top_services_json": int(env_get("TTL_TOP_SERVICES_JSON", "30")),
    "revenue_json": int(env_get("TTL_REVENUE_JSON", "30")),
    "overview_csv": int(env_get("TTL_OVERVIEW_CSV", "60")),
    "top_services_csv": int(env_get("TTL_TOP_SERVICES_CSV", "60")),
    "revenue_csv": int(env_get("TTL_REVENUE_CSV", "60")),
}
