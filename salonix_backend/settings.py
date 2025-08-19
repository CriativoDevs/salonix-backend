import os
import configparser

from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Define qual ambiente está sendo usado
ENV = os.getenv("DJANGO_ENV", "dev")  # Pode ser: dev, uat, prod

# Lê o arquivo settings.ini
ini_path = BASE_DIR / "settings.ini"
parser = configparser.ConfigParser(interpolation=None)
parser.read(ini_path)

# Segurança
SECRET_KEY = parser[ENV]["SECRET_KEY"]
DEBUG = parser.getboolean(ENV, "DEBUG")
ALLOWED_HOSTS = [h.strip() for h in parser[ENV]["ALLOWED_HOSTS"].split(",")]

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
    # APPS
    "core",
    "users",
    "payments",
    "reports",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CORS_ALLOW_ALL_ORIGINS = True


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

DATABASES = {
    "default": {
        "ENGINE": parser[ENV]["DATABASE_ENGINE"],
        "NAME": parser[ENV]["DATABASE_NAME"],
        "USER": parser[ENV].get("DATABASE_USER", ""),
        "PASSWORD": parser[ENV].get("DATABASE_PASSWORD", ""),
        "HOST": parser[ENV].get("DATABASE_HOST", ""),
        "PORT": parser[ENV].get("DATABASE_PORT", ""),
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
REPORTS_THROTTLE_REPORTS = parser[ENV].get("REPORTS_THROTTLE_REPORTS", "60/min")
REPORTS_THROTTLE_EXPORT_CSV = parser[ENV].get("REPORTS_THROTTLE_EXPORT_CSV", "5/min")

# REST_FRAMEWORK config
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
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
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

AUTH_USER_MODEL = "users.CustomUser"


# Email
# Email configuration
EMAIL_BACKEND = parser[ENV]["EMAIL_BACKEND"]
EMAIL_HOST = parser[ENV]["EMAIL_HOST"]
EMAIL_PORT = parser.getint(ENV, "EMAIL_PORT")
EMAIL_USE_TLS = parser.getboolean(ENV, "EMAIL_USE_TLS")
EMAIL_HOST_USER = parser[ENV]["EMAIL_HOST_USER"]
EMAIL_HOST_PASSWORD = parser[ENV]["EMAIL_HOST_PASSWORD"]
DEFAULT_FROM_EMAIL = parser[ENV]["DEFAULT_FROM_EMAIL"]

# Stripe
STRIPE_API_KEY = parser[ENV].get("STRIPE_API_KEY", "")
STRIPE_WEBHOOK_SECRET = parser[ENV].get("STRIPE_WEBHOOK_SECRET", "")

# Prices (você já criou no Stripe; cole aqui)
STRIPE_PRICE_MONTHLY_ID = parser[ENV].get("STRIPE_PRICE_MONTHLY_ID", "")
STRIPE_PRICE_YEARLY_ID = parser[ENV].get("STRIPE_PRICE_YEARLY_ID", "")

# URLs do front para redirecionar após checkout/portal
STRIPE_SUCCESS_URL = parser[ENV].get(
    "STRIPE_SUCCESS_URL",
    "http://localhost:3000/billing/success?session_id={CHECKOUT_SESSION_ID}",
)
STRIPE_CANCEL_URL = parser[ENV].get(
    "STRIPE_CANCEL_URL", "http://localhost:3000/billing/cancel"
)
STRIPE_PORTAL_RETURN_URL = parser[ENV].get(
    "STRIPE_PORTAL_RETURN_URL", "http://localhost:3000/billing"
)
STRIPE_API_VERSION = parser[ENV].get("STRIPE_API_VERSION", "")

# Pagination limits for reports
REPORTS_PAGINATION = {
    "DEFAULT_LIMIT": 50,  # o que usar quando não vier ?limit=
    "MAX_LIMIT": 500,  # teto duro para evitar respostas gigantes
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
