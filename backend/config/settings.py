import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-key")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
ON_DEMAND_SYNC_ENABLED = env_bool("ON_DEMAND_SYNC_ENABLED", True)
ON_DEMAND_SYNC_MIN_INTERVAL_SECONDS = int(os.getenv("ON_DEMAND_SYNC_MIN_INTERVAL_SECONDS", "60"))

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.analytics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "login"

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

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "panorama_analytics"),
        "USER": os.getenv("POSTGRES_USER", "panorama"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "change-me"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Minsk"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = PROJECT_ROOT / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
APPEND_SLASH = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "bitrix24-incremental-sync-every-10-minutes": {
        "task": "apps.analytics.tasks.sync_bitrix24_incremental",
        "schedule": 10 * 60,
    },
}

BITRIX24 = {
    "BASE_URL": os.getenv("BITRIX24_BASE_URL", "").rstrip("/"),
    "WEBHOOK_URL": os.getenv("BITRIX24_WEBHOOK_URL", "").rstrip("/") + "/" if os.getenv("BITRIX24_WEBHOOK_URL") else "",
    "TIMEOUT_SECONDS": int(os.getenv("BITRIX24_TIMEOUT_SECONDS", "30")),
    "PANORAMA_PIPELINE_ID": os.getenv("PANORAMA_PIPELINE_ID", ""),
    "RO_PIPELINE_ID": os.getenv("RO_PIPELINE_ID", ""),
    "B2B_PIPELINE_ID": os.getenv("B2B_PIPELINE_ID", ""),
    "PANORAMA_ZZ_STAGE_ID": os.getenv("PANORAMA_ZZ_STAGE_ID", ""),
    "RO_ZZ_STAGE_ID": os.getenv("RO_ZZ_STAGE_ID", ""),
    "B2B_ZZ_STAGE_ID": os.getenv("B2B_ZZ_STAGE_ID", ""),
    "PANORAMA_ZN_STAGE_ID": os.getenv("PANORAMA_ZN_STAGE_ID", ""),
    "RO_ZN_STAGE_ID": os.getenv("RO_ZN_STAGE_ID", ""),
    "B2B_ZN_STAGE_ID": os.getenv("B2B_ZN_STAGE_ID", ""),
    "LEAD_DIRECTION_FIELD": os.getenv("LEAD_DIRECTION_FIELD", ""),
    "LEAD_PANORAMA_DIRECTION_VALUES": [
        value.strip().lower() for value in os.getenv("LEAD_PANORAMA_DIRECTION_VALUES", "Панорама,panorama").split(",") if value.strip()
    ],
    "LEAD_RO_DIRECTION_VALUES": [
        value.strip().lower() for value in os.getenv("LEAD_RO_DIRECTION_VALUES", "Русские окна,РО,ro").split(",") if value.strip()
    ],
    "DEAL_CONTRACT_DATE_FIELD": os.getenv("DEAL_CONTRACT_DATE_FIELD", ""),
    "DEAL_CONTRACT_AMOUNT_FIELD": os.getenv("DEAL_CONTRACT_AMOUNT_FIELD", "OPPORTUNITY"),
}

JAZZMIN_SETTINGS = {
    "site_title": "Панорама Analytics",
    "site_header": "Окна Панорама",
    "site_brand": "Analytics Admin",
    "welcome_sign": "Администрирование дашборда",
    "copyright": "JS Global",
    "search_model": ["auth.User", "analytics.CrmUser"],
    "topmenu_links": [
        {"name": "Дашборд", "url": "/", "new_window": False},
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "order_with_respect_to": ["analytics", "auth"],
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.group": "fas fa-users",
        "analytics.CrmDeal": "fas fa-handshake",
        "analytics.CrmLead": "fas fa-inbox",
        "analytics.ManagerDailyMetric": "fas fa-chart-bar",
        "analytics.SyncRun": "fas fa-sync",
    },
    "language_chooser": False,
}

JAZZMIN_UI_TWEAKS = {
    "theme": "flatly",
    "dark_mode_theme": "darkly",
    "navbar": "navbar-white navbar-light",
    "sidebar": "sidebar-dark-primary",
    "brand_colour": "navbar-primary",
}
