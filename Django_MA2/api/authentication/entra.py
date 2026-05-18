"""Microsoft Entra ID (Azure AD) Bearer token authentication for DRF."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import urlparse

import jwt
import requests as http_requests
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)

# ── Module-level cache for OIDC discovery & JWKS client ────────────────
_discovery_cache: dict[str, Any] = {}
_discovery_lock = threading.Lock()
_CACHE_TTL = 3600  # 1 hour

_jwk_client: jwt.PyJWKClient | None = None
_jwk_client_lock = threading.Lock()


def _normalize_issuer(value: str) -> str:
    """Normalize issuer URLs for tolerant string comparison."""
    return value.strip().rstrip("/").lower()


def _allowed_issuers(tenant_id: str, discovery_issuer: str) -> set[str]:
    """Build accepted issuer values for Entra v2 and v1 tokens."""
    tid = tenant_id.strip()
    v2_issuer = discovery_issuer.strip()
    v1_issuer = f"https://sts.windows.net/{tid}/"

    candidates = {v2_issuer, v1_issuer}
    return {_normalize_issuer(c) for c in candidates if c}


def _is_allowed_issuer(token_issuer: str, tenant_id: str, discovery_issuer: str) -> bool:
    """Validate issuer for the configured tenant across Entra v1/v2 variants."""
    normalized_token_issuer = _normalize_issuer(token_issuer)
    if not normalized_token_issuer:
        return False

    # Fast path for known exact issuers.
    if normalized_token_issuer in _allowed_issuers(tenant_id, discovery_issuer):
        return True

    # Fallback: accept equivalent Microsoft issuer variants for the same tenant.
    parsed = urlparse(normalized_token_issuer)
    if parsed.scheme != "https":
        return False

    discovery_host = urlparse(_normalize_issuer(discovery_issuer)).hostname or ""
    allowed_hosts = {
        discovery_host,
        "sts.windows.net",
        "login.windows.net",
        "login.microsoftonline.com",
    }

    if parsed.hostname not in allowed_hosts:
        return False

    # Path must start with /<tenant_id> and may optionally include /v2.0
    tid = tenant_id.strip().lower()
    token_path = parsed.path.rstrip("/")
    return token_path in {f"/{tid}", f"/{tid}/v2.0"}


def _get_discovery(tenant_id: str, discovery_url: str | None) -> dict[str, str]:
    """Return cached OIDC discovery document (jwks_uri, issuer).

    Thread-safe; fetches at most once per TTL window.
    """
    now = time.time()
    cached = _discovery_cache.get("doc")
    if cached and now - _discovery_cache.get("ts", 0) < _CACHE_TTL:
        return cached

    with _discovery_lock:
        # Double-check after acquiring lock
        cached = _discovery_cache.get("doc")
        if cached and now - _discovery_cache.get("ts", 0) < _CACHE_TTL:
            return cached

        url = discovery_url or (
            f"https://login.microsoftonline.com/{tenant_id}/v2.0/"
            ".well-known/openid-configuration"
        )
        resp = http_requests.get(url, timeout=10)
        resp.raise_for_status()
        doc = resp.json()

        result = {
            "jwks_uri": doc["jwks_uri"],
            "issuer": doc["issuer"],
        }
        _discovery_cache["doc"] = result
        _discovery_cache["ts"] = time.time()
        return result


def _get_jwk_client(jwks_uri: str) -> jwt.PyJWKClient:
    """Return a singleton PyJWKClient, (re-)created if the jwks_uri changes."""
    global _jwk_client

    if _jwk_client is not None:
        return _jwk_client

    with _jwk_client_lock:
        if _jwk_client is not None:
            return _jwk_client
        _jwk_client = jwt.PyJWKClient(jwks_uri, lifespan=_CACHE_TTL)
        return _jwk_client


class EntraBearerAuthentication(BaseAuthentication):
    """Authenticate requests bearing a Microsoft Entra ID access token.

    Behaviour:
    - No ``Authorization`` header or not ``Bearer …`` → ``None`` (let next
      authenticator try, e.g. ``JWTAuthentication``).
    - Token is structurally a JWT **but** the kid is not in the Entra JWKS
      → ``None`` (not an Entra token; fallback).
        - Token IS an Entra JWT but validation fails (expired, bad audience,
            wrong issuer, invalid signature) → ``AuthenticationFailed`` (HTTP 401).

        Issuer compatibility:
        - Accepts Entra v2 issuer from discovery
            (``https://login.microsoftonline.com/<tenant>/v2.0``).
        - Also accepts Entra v1 issuer for the same tenant
            (``https://sts.windows.net/<tenant>/``).
    """

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]  # strip "Bearer "
        if not token:
            return None

        tenant_id: str = getattr(settings, "ENTRA_TENANT_ID", "")
        audience: str = getattr(settings, "ENTRA_AUDIENCE", "")
        discovery_url: str | None = getattr(settings, "ENTRA_DISCOVERY_URL", None)

        if not tenant_id or not audience:
            logger.error("ENTRA_TENANT_ID or ENTRA_AUDIENCE not configured.")
            return None

        # 1. Fetch OIDC discovery (cached)
        try:
            discovery = _get_discovery(tenant_id, discovery_url)
        except Exception:
            logger.exception("Failed to fetch Entra OIDC discovery document.")
            raise AuthenticationFailed("SSO configuration error.")

        jwks_uri = discovery["jwks_uri"]
        issuer = discovery["issuer"]
        accepted_issuers = _allowed_issuers(tenant_id, issuer)

        # 2. Resolve signing key
        jwk_client = _get_jwk_client(jwks_uri)
        try:
            signing_key = jwk_client.get_signing_key_from_jwt(token)
        except (jwt.exceptions.DecodeError, jwt.exceptions.InvalidTokenError):
            # Not a valid JWT or kid not in Entra JWKS → fallback
            return None
        except Exception:
            # kid not found, network error retrieving JWKS, etc. → fallback
            return None

        # 3. Decode & validate token — failures here are hard 401s
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=["RS256"],
                audience=audience,
                options={"verify_iss": False},
            )

            token_issuer_raw = str(claims.get("iss", ""))
            if not _is_allowed_issuer(token_issuer_raw, tenant_id, issuer):
                raise jwt.InvalidIssuerError(
                    f"Issuer '{token_issuer_raw}' is not accepted for tenant '{tenant_id}'."
                )
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Entra token has expired.")
        except jwt.InvalidAudienceError:
            raise AuthenticationFailed("Entra token audience mismatch.")
        except jwt.InvalidIssuerError:
            raise AuthenticationFailed("Entra token issuer mismatch.")
        except jwt.InvalidTokenError as exc:
            raise AuthenticationFailed(f"Invalid Entra token: {exc}")

        # 4. Provision / update local Django user
        user = self._provision_user(claims)

        # 5. Build auth dict with key claims
        auth = {
            "oid": claims.get("oid"),
            "tid": claims.get("tid"),
            "preferred_username": (
                claims.get("preferred_username")
                or claims.get("upn")
                or claims.get("email")
            ),
            "name": claims.get("name") or claims.get("given_name") or "",
            "scp": claims.get("scp"),
            "roles": claims.get("roles") or [],
            "aud": claims.get("aud"),
            "iss": claims.get("iss"),
        }

        return (user, auth)

    def authenticate_header(self, request):
        return "Bearer"

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _provision_user(claims: dict[str, Any]):
        """Get-or-create a local Django user keyed by Entra ``oid``."""
        User = get_user_model()
        oid = claims.get("oid", "")
        username = f"entra_{oid}"[:150]

        email = (
            claims.get("preferred_username")
            or claims.get("upn")
            or claims.get("email")
            or ""
        )

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email},
        )

        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            logger.info("Provisioned new Entra user: %s (oid=%s)", username, oid)
        elif email and user.email != email:
            user.email = email
            user.save(update_fields=["email"])

        return user
