"""Django settings for the Avia Navigation backend.

This is a straight port of the original FastAPI service. The app serves
files from disk and renders an admin dashboard; it does NOT use the ORM
for any API endpoint. A SQLite database is configured only so that Django's
own machinery (management commands, etc.) has a default connection — no
project code touches it.

Data directories (``data/``, ``downloaded_data/``, ``processed_data/``) and
the ``web_scraper`` package live in the PROJECT ROOT, one level above this
Django project, exactly as in the original layout.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# settings.py -> avia_nav/ -> django_app/ -> <project root = apisaero-transfer>
DJANGO_DIR = Path(__file__).resolve().parent.parent          # django_app/
PROJECT_ROOT = DJANGO_DIR.parent                             # apisaero-transfer/

# Load .env from the project root (same file the FastAPI app / scraper use)
load_dotenv(PROJECT_ROOT / ".env")

# Physical data locations (shared with web_scraper)
DATA_DIR = PROJECT_ROOT / "data"
DOWNLOADED_DIR = PROJECT_ROOT / "downloaded_data"
PROCESSED_DIR = PROJECT_ROOT / "processed_data"

# ---------------------------------------------------------------------------
# Core Django config
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "insecure-dev-key-change-me-in-production-please-0123456789",
)

DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() in {"1", "true", "yes", "on"}

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "api",
]

# No auth/session/CSRF middleware: this is a stateless, token-authenticated
# API. Admin endpoints enforce their own Bearer/Basic token (see api/auth.py).
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "avia_nav.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "avia_nav.wsgi.application"
ASGI_APPLICATION = "avia_nav.asgi.application"

# Unused by any API endpoint — present only for Django's default connection.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DJANGO_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Serve large files without buffering the whole thing in memory.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ---------------------------------------------------------------------------
# Application-specific config
# ---------------------------------------------------------------------------
# Admin token. When empty, admin auth is DISABLED (dev convenience) and a
# warning is logged — mirrors the original app tolerating an unset token.
ADMIN_AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")

# rsync source for diagram/map sync from Server B (a_big / a_small / m_sectional)
RSYNC_SOURCE = os.getenv("RSYNC_SOURCE", "mb@127.0.0.1:/home/mb/faa_vfr")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
