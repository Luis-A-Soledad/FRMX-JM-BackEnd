"""Custom DRF permission classes for SSO role enforcement."""

from __future__ import annotations

from django.conf import settings
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import BasePermission

from accounts.utils import build_user_context
from role_config import DENIED_SSO_MESSAGE, normalize_role_name


class IsAllowedSSORole(BasePermission):
    """Enforce SSO role whitelist on protected endpoints.

    Behaviour depends on ``settings.ENTRA_SSO_ENFORCE``:

    * **ENFORCE = True** (production):
      - Unauthenticated requests → raise ``NotAuthenticated`` → **HTTP 401**.
      - Authenticated but role NOT in ``ENTRA_SSO_ALLOWED_ROLES`` → **403**.

    * **ENFORCE = False** (dev / local):
      - Unauthenticated requests → **allowed** (anonymous/ANON path).
      - Authenticated but role NOT in allowlist → **403** (still blocked).

    The allowlist is read from ``settings.ENTRA_SSO_ALLOWED_ROLES``
    (a ``frozenset[str]``, all lowercase).  Comparison is case-insensitive.
    """

    message = DENIED_SSO_MESSAGE

    def has_permission(self, request, view) -> bool:
        enforce: bool = getattr(settings, "ENTRA_SSO_ENFORCE", False)

        if not request.user.is_authenticated:
            if enforce:
                # Explicit 401 — not 403 — so the client knows to authenticate.
                raise NotAuthenticated("Authentication required.")
            # Non-enforce mode: anonymous access allowed (dev convenience).
            return True

        # Authenticated: role must be in the allowlist regardless of mode.
        user_context = build_user_context(request.user, request=request)
        if not user_context.get("allowed", False):
            self.message = "Token does not include required API scope."
            return False

        allowed_roles: frozenset[str] = getattr(
            settings, "ENTRA_SSO_ALLOWED_ROLES", frozenset()
        )
        allowed_roles_norm = {str(role).strip().lower() for role in allowed_roles}
        role_norm = normalize_role_name(str(user_context.get("role", ""))).lower()
        return role_norm in allowed_roles_norm


class HasRequiredScope(BasePermission):
    """Allow only requests that include the configured required scope."""

    message = "Token does not include required API scope."

    def has_permission(self, request, view) -> bool:
        auth_claims = getattr(request, "auth", None)
        if not isinstance(auth_claims, dict):
            return False

        required_scope = str(getattr(settings, "ENTRA_REQUIRED_SCOPE", "Api.access")).strip()
        if not required_scope:
            return True

        scp_raw = str(auth_claims.get("scp") or "").strip()
        scopes = scp_raw.split() if scp_raw else []
        return required_scope.lower() in {scope.lower() for scope in scopes}
