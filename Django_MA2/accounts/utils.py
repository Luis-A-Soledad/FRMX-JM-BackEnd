from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest

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
    if not user.is_authenticated:
        context = {
            "user_id": None,
            "email": None,
            "role": ROLE_ANON,
            "scopes": {"fleets": [], "regions": []},
        }
        return _apply_temporary_role_bypass(context, request)

    # Intentar obtener el perfil asociado (OneToOne → related_name="profile")
    try:
        profile = user.profile  # type: ignore[union-attr]
        role: str = profile.role.name
    except ObjectDoesNotExist:
        logger.warning(
            "Usuario autenticado sin UserProfile: pk=%s, username=%s",
            user.pk,
            getattr(user, "username", "?"),
        )
        role = ROLE_UNKNOWN

    email = getattr(user, "email", None) or user.get_username()  # type: ignore[union-attr]

    context = {
        "user_id": user.pk,
        "email": email,
        "role": role,
        "scopes": {"fleets": [], "regions": []},
    }
    return _apply_temporary_role_bypass(context, request)
