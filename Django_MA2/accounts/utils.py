from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest

from role_config import resolve_access_level

logger = logging.getLogger(__name__)

ROLE_ANON: str = "ANON"
ROLE_UNKNOWN: str = "UNKNOWN"


def _apply_temporary_role_bypass(
    user_context: dict[str, Any],
    request: HttpRequest | None,
) -> dict[str, Any]:
    """Apply DEBUG-only role override for authenticated UNKNOWN users.

    Expected request header (configurable): ``X-Bypass-Role``.
    The requested role must belong to ``settings.ENTRA_SSO_ALLOWED_ROLES``.
    """
    if request is None:
        return user_context
    if not getattr(settings, "SSO_ROLE_BYPASS_ENABLED", False):
        return user_context
    if not getattr(settings, "DEBUG", False):
        return user_context
    if user_context.get("role") != ROLE_UNKNOWN:
        return user_context

    # 1) Preferred path: identity map from settings (email/username/oid-user -> role)
    identities: list[str] = []

    def _add_identity(value: Any) -> None:
        val = str(value or "").strip().lower()
        if val and val not in identities:
            identities.append(val)

    _add_identity(user_context.get("email"))
    try:
        _add_identity(request.user.get_username())  # type: ignore[union-attr]
    except Exception:
        pass

    # Include useful claim-based candidates (DRF auth payload from Entra auth class)
    auth_claims = getattr(request, "auth", None)
    if isinstance(auth_claims, dict):
        _add_identity(auth_claims.get("preferred_username"))
        _add_identity(auth_claims.get("upn"))
        _add_identity(auth_claims.get("email"))
        oid = str(auth_claims.get("oid") or "").strip().lower()
        if oid:
            _add_identity(f"entra_{oid}")

    bypass_map: dict[str, str] = getattr(settings, "SSO_ROLE_BYPASS_MAP", {})
    mapped_role = ""
    matched_identity = ""
    for identity in identities:
        candidate = str(bypass_map.get(identity, "")).strip().lower()
        if candidate:
            mapped_role = candidate
            matched_identity = identity
            break

    allowed_roles: frozenset[str] = getattr(settings, "ENTRA_SSO_ALLOWED_ROLES", frozenset())
    if mapped_role:
        if mapped_role in allowed_roles:
            user_context["role"] = mapped_role.upper()
            user_context["bypass_role"] = mapped_role.upper()
            user_context["bypass_source"] = "map"
            user_context["bypass_identity"] = matched_identity
            return user_context

        logger.warning(
            "SSO_ROLE_BYPASS ignored: mapped role '%s' for '%s' is not in ENTRA_SSO_ALLOWED_ROLES",
            mapped_role,
            matched_identity,
        )
        return user_context

    header_name = str(getattr(settings, "SSO_ROLE_BYPASS_HEADER", "X-Bypass-Role")).strip()
    header_meta_key = f"HTTP_{header_name.upper().replace('-', '_')}"

    requested_role = ""
    # DRF Request exposes normalized headers here.
    headers = getattr(request, "headers", None)
    if headers is not None:
        requested_role = str(headers.get(header_name, "")).strip().lower()

    if not requested_role:
        meta = getattr(request, "META", {})
        requested_role = str(meta.get(header_meta_key, "")).strip().lower()
    if not requested_role:
        return user_context

    if requested_role not in allowed_roles:
        logger.warning(
            "SSO_ROLE_BYPASS ignored: requested role '%s' is not in ENTRA_SSO_ALLOWED_ROLES",
            requested_role,
        )
        return user_context

    user_context["role"] = requested_role.upper()
    user_context["bypass_role"] = requested_role.upper()
    user_context["bypass_source"] = "header"
    return user_context


def parse_roles(_roles):
    roles = []

    if isinstance(_roles, str):
        roles: list[str] = [_roles] if _roles.strip() else []
    elif isinstance(_roles, list):
        roles = [str(r).strip() for r in _roles if str(r).strip()]
    else:
        roles = []

    return roles

def build_user_context(
    user: AbstractBaseUser | AnonymousUser,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """Construye el diccionario de contexto del usuario para el agente.

    Parameters
    ----------
    user:
        Instancia de usuario de Django (autenticado o ``AnonymousUser``).

    Returns
    -------
    dict con las claves ``user_id``, ``email``, ``role`` y ``scopes``.
    """
    required_scope = str(getattr(settings, "ENTRA_REQUIRED_SCOPE", "Api.access")).strip()
    required_scope_norm = required_scope.lower()

    auth_claims = getattr(request, "auth", None)
    if isinstance(auth_claims, dict):
        normalized_claims = auth_claims
    elif hasattr(auth_claims, "payload"):
        normalized_claims = getattr(auth_claims, "payload", {}) or {}
    else:
        normalized_claims = {}

    if not isinstance(normalized_claims, dict):
        normalized_claims = {}

    auth_claims = normalized_claims
    has_claims_context = bool(auth_claims)
    backend_token = bool(
        auth_claims
        and auth_claims.get("role")
        and auth_claims.get("capabilities") is not None
    )

    if not user.is_authenticated:
        context = {
            "user_id": None,
            "email": auth_claims.get("email") or None,
            "name": auth_claims.get("name") or None,
            "oid": auth_claims.get("oid"),
            "roles": [],
            "scp": [],
            "access_level": 0,
            "capabilities": ["VIEW_BASIC"],
            "allowed": bool(backend_token),
            "role": ROLE_ANON,
            "scopes": {"fleets": [], "regions": []},
        }
        if backend_token:
            context["role"] = str(auth_claims.get("role")).upper()
            context["roles"] = parse_roles([str(auth_claims.get("role"))])
            context["capabilities"] = list(auth_claims.get("capabilities") or ["VIEW_BASIC"])
            context["allowed"] = True
            if auth_claims.get("scp"):
                context["scp"] = str(auth_claims.get("scp")).split()
        return _apply_temporary_role_bypass(context, request)

    claims_roles = auth_claims.get("roles") or []
    if not claims_roles and auth_claims.get("role"):
        claims_roles = [auth_claims.get("role")]
    roles = parse_roles(claims_roles)

    scp_raw = str(auth_claims.get("scp") or "").strip()
    scp_list = scp_raw.split() if scp_raw else []
    scp_norm = [s.lower() for s in scp_list]
    access_level, capabilities, effective_role = resolve_access_level(roles)

    # Compatibilidad con el flujo previo para usuarios autenticados sin claims roles.
    role = effective_role or getattr(user, "role", None) or auth_claims.get("role")
    if not role:
        profile = getattr(user, "profile", None)
        if profile is not None:
            try:
                role = str(profile.role.name)
            except ObjectDoesNotExist:
                role = ROLE_UNKNOWN
        else:
            role = ROLE_UNKNOWN

    email = getattr(user, "email", None) or user.get_username()  # type: ignore[union-attr]
    name = auth_claims.get("name") or getattr(user, "name", "") or getattr(user, "first_name", "") or None
    oid = auth_claims.get("oid")
    if backend_token:
        allowed = True
        if auth_claims.get("scp"):
            scp_list = str(auth_claims.get("scp")).split()
            scp_norm = [s.lower() for s in scp_list]
    elif required_scope and has_claims_context:
        allowed = required_scope_norm in scp_norm
    else:
        allowed = True

    if backend_token and not roles and auth_claims.get("role"):
        roles = [str(auth_claims.get("role"))]
        access_level, capabilities, role = resolve_access_level(roles)

    context = {
        "user_id": getattr(user, "pk", None),
        "email": email,
        "name": name,
        "oid": oid,
        "roles": roles,
        "scp": scp_list,
        "access_level": access_level,
        "capabilities": auth_claims.get("capabilities") or capabilities,
        "allowed": allowed,
        "role": role,
        "scopes": {"fleets": [], "regions": []},
    }
    context = _apply_temporary_role_bypass(context, request)

    if context.get("bypass_role"):
        bypass_role = str(context["bypass_role"]).strip()
        context["roles"] = [bypass_role]
        access_level, capabilities, _ = resolve_access_level(context["roles"])
        context["access_level"] = access_level
        context["capabilities"] = capabilities

    return context
