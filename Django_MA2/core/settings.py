import os
import logging
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "channels",
    "api",
    "accounts",
    "email_alerts"
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "core.urls"

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

# ── Django Channels — Channel Layer ─────────────────────────
_REDIS_URL = os.getenv("CHANNEL_LAYER_REDIS_URL", "").strip()

if _REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [_REDIS_URL],
            },
        },
    }
else:
    # InMemory para dev local (funciona solo dentro de un mismo proceso)
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }

# ── Alertas Poller ──────────────────────────────────────────
ALERTAS_POLLER_ENABLED = os.getenv("ALERTAS_POLLER_ENABLED", "1").strip() == "1"
ALERTAS_POLL_INTERVAL_SECS = int(os.getenv("ALERTAS_POLL_INTERVAL_SECS", "10"))

# ── Notificaciones WhatsApp (alertas prioritarias A01/A02/A03/A06) ──
# Desactivado por defecto: el envío real espera token/template aprobados por Meta.
# Todo el scaffold puede mergearse y probarse con el flag en 0.
ALERTAS_WHATSAPP_ENABLED = os.getenv("ALERTAS_WHATSAPP_ENABLED", "0").strip() == "1"
# Cargos de silver.administrativo que reciben WhatsApp (CSV).
# Vacío = TODOS los contactos de la tabla reciben (decisión CCO). Override opcional.
WHATSAPP_CARGOS_DESTINO = os.getenv("WHATSAPP_CARGOS_DESTINO", "").strip()
# Credenciales/template de la WhatsApp Business Cloud API (Meta). Pendientes de Meta.
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
WHATSAPP_TEMPLATE_NAME = os.getenv("WHATSAPP_TEMPLATE_NAME", "alerta_prioritaria").strip()
WHATSAPP_TEMPLATE_LANG = os.getenv("WHATSAPP_TEMPLATE_LANG", "es_MX").strip()
WHATSAPP_GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v21.0").strip()
WHATSAPP_REQUEST_TIMEOUT_SECS = int(os.getenv("WHATSAPP_REQUEST_TIMEOUT_SECS", "15"))

# ── Base de datos ────────────────────────────────────────────
# Si DATABASE_URL está definida en el entorno, la usa (PostgreSQL, etc.).
# Si no, usa SQLite local para desarrollo.  db.sqlite3 ya está en .gitignore.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    ),
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


CORS_ALLOW_ALL_ORIGINS = False
_cors_allowed_raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in _cors_allowed_raw.split(",") if origin.strip()
]

CORS_ALLOW_CREDENTIALS = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Tiempo máximo de espera para el agente (segundos)
AGENT_TIMEOUT = int(os.getenv("AGENT_TIMEOUT", "120"))

# ── Microsoft Entra ID (SSO) ───────────────────────────────
ENTRA_AUTH_ENABLED = os.getenv("ENTRA_AUTH_ENABLED", "0").strip() == "1"
ENTRA_TENANT_ID = os.getenv("ENTRA_TENANT_ID", "").strip()
ENTRA_AUDIENCE = os.getenv("ENTRA_AUDIENCE", "").strip()
ENTRA_DISCOVERY_URL = os.getenv("ENTRA_DISCOVERY_URL", "").strip() or None

# ── PKCE / public-client support (frontend reads these via /api/sso/config/) ──
ENTRA_FRONTEND_CLIENT_ID = os.getenv("ENTRA_FRONTEND_CLIENT_ID", "").strip()
ENTRA_FRONTEND_CLIENT_SECRET = os.getenv("ENTRA_FRONTEND_CLIENT_SECRET", "").strip()
ENTRA_API_SCOPE = os.getenv("ENTRA_API_SCOPE", "").strip()
ENTRA_SSO_SCOPES = os.getenv("ENTRA_SSO_SCOPES", "").strip()
ENTRA_AUTHORITY = os.getenv("ENTRA_AUTHORITY", "").strip()
ENTRA_EXPECTED_AUDIENCE = os.getenv("ENTRA_EXPECTED_AUDIENCE", "").strip()
ENTRA_REQUIRED_SCOPE = os.getenv("ENTRA_REQUIRED_SCOPE", "Api.access").strip()

# ── Server-side OAuth callback flow (Option B) ──
# URL del backend donde Azure redirige después del login (registrar en Azure Portal)
ENTRA_BACKEND_CALLBACK_URI = os.getenv("ENTRA_BACKEND_CALLBACK_URI", "").strip()
# URL del frontend donde el backend redirige con el token después del exchange
ENTRA_FRONTEND_CALLBACK_URL = os.getenv("ENTRA_FRONTEND_CALLBACK_URL", "").strip()

# Si =1, /api/chat y /api/session requieren Bearer Entra + rol permitido.
# Si =0 (default), se permite acceso anónimo (dev local), pero usuarios SSO
# con rol no autorizado siguen bloqueados con 403.
ENTRA_SSO_ENFORCE = os.getenv("ENTRA_SSO_ENFORCE", "0").strip() == "1"

# Roles SSO autorizados (case-insensitive, comma-separated).
# Default: cco,jefe_maquinistas.
_raw_allowed = os.getenv("ENTRA_SSO_ALLOWED_ROLES", "cco,jefe_maquinistas")
ENTRA_SSO_ALLOWED_ROLES: frozenset[str] = frozenset(
    r.strip().lower() for r in _raw_allowed.split(",") if r.strip()
)

# ── Temporary SSO role bypass for local/dev debugging ───────────────
# Allows overriding UNKNOWN role via request header (X-Bypass-Role by default)
# while keeping Entra authentication enabled.
SSO_ROLE_BYPASS_ENABLED = os.getenv("SSO_ROLE_BYPASS_ENABLED", "0").strip() == "1"
SSO_ROLE_BYPASS_HEADER = os.getenv("SSO_ROLE_BYPASS_HEADER", "X-Bypass-Role").strip()

# Optional map for temporary role assignment of authenticated UNKNOWN users.
# Format: "camila.vera@cl.ey.com:CCO,entra_oid_username:JEFE_MAQUINISTAS"
_raw_role_bypass_map = os.getenv("SSO_ROLE_BYPASS_MAP", "").strip()
SSO_ROLE_BYPASS_MAP: dict[str, str] = {}
if _raw_role_bypass_map:
    for _entry in _raw_role_bypass_map.split(","):
        _entry = _entry.strip()
        if ":" in _entry:
            _id_part, _role_part = _entry.split(":", 1)
            SSO_ROLE_BYPASS_MAP[_id_part.strip().lower()] = _role_part.strip().upper()

# Guardrail: role bypass is never allowed in production
if SSO_ROLE_BYPASS_ENABLED and not DEBUG:
    from django.core.exceptions import ImproperlyConfigured as _IC
    raise _IC(
        "SSO_ROLE_BYPASS_ENABLED=1 is not allowed when DEBUG=False. "
        "This mechanism is for local/dev debugging only."
    )

# ── Guardrail: ENFORCE=1 sin autenticador Entra es configuración inválida ──
if ENTRA_SSO_ENFORCE and not ENTRA_AUTH_ENABLED:
    _settings_logger = logging.getLogger("core.settings")
    _msg = (
        "ENTRA_SSO_ENFORCE=1 but ENTRA_AUTH_ENABLED=0.  "
        "SSO enforcement requires Entra authentication to be enabled.  "
        "All requests will be rejected as unauthenticated until you set "
        "ENTRA_AUTH_ENABLED=1."
    )
    if DEBUG:
        _settings_logger.warning("⚠️  %s", _msg)
    else:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(_msg)

_auth_classes = []
if ENTRA_AUTH_ENABLED:
    _auth_classes.append("api.authentication.entra.EntraBearerAuthentication")
_auth_classes.append("api.authentication.stateless_jwt.StatelessJWTAuthentication")

from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "USER_ID_FIELD": "email",
    "USER_ID_CLAIM": "email",

}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": _auth_classes,
    "DEFAULT_PERMISSION_CLASSES": [],       # No tocar: /api/chat debe seguir anónimo
}