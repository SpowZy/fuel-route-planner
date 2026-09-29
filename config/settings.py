"""Settings. Everything environment-specific comes from environment variables."""

import importlib.util
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").lower() in {"1", "true", "yes"}


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-key-not-for-production")
if not DEBUG and SECRET_KEY == "dev-only-key-not-for-production":
    raise RuntimeError("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0")
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "stations",
    "api",
    "demo",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

# WhiteNoise serves the collected static files when the "serve" extra is installed (Docker).
if importlib.util.find_spec("whitenoise"):
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
            ]
        },
    }
]

# SQLite out of the box, PostgreSQL with DATABASE_URL=postgres://user:pass@host/db
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=60
    )
}

# Local memory by default, Redis when REDIS_URL is set.
if os.environ.get("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.environ["REDIS_URL"],
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "EXCEPTION_HANDLER": "api.errors.handle",
}

# Vehicle and planning defaults. The assessment fixes range and mpg; every value below can be
# overridden per request except the price strategy, which is applied when stations are loaded.
FUEL = {
    "RANGE_MILES": 500.0,
    "MPG": 10.0,
    "PRICE_STRATEGY": os.environ.get("FUEL_PRICE_STRATEGY", "median"),
    "INCLUDE_CANADA": env_bool("FUEL_INCLUDE_CANADA", True),
    # Stations are placed at their city centroid, so a truck stop on the highway can read a
    # few miles from the route. Inside FREE_OFFSET_MILES a station counts as on the route;
    # beyond it, the round trip (inflated by CIRCUITY for real roads) is priced as fuel.
    "MAX_OFFSET_MILES": 10.0,
    "FREE_OFFSET_MILES": 4.0,
    "CIRCUITY": 1.3,
    # Dollars charged per stop for the driver's time, only to choose between plans. Without
    # it the cheapest plan stops whenever a station is a cent cheaper, and buys 1 gallon.
    "STOP_PENALTY_USD": 10.0,
}

ROUTING = {
    "OSRM_URL": os.environ.get("OSRM_URL", "https://router.project-osrm.org"),
    "VALHALLA_URL": os.environ.get("VALHALLA_URL", "https://valhalla1.openstreetmap.de"),
    "TIMEOUT_SECONDS": 20,
    "MIN_INTERVAL_SECONDS": 1.0,  # the public OSRM demo server asks for at most 1 request/s
    "CACHE_SECONDS": 24 * 3600,
    "USER_AGENT": "fuel-route-planner-assessment/0.1",
    "SNAPSHOT_DIR": BASE_DIR / "data" / "route_snapshots",
}
