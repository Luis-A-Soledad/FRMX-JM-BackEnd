"""Custom DRF permission classes for SSO role enforcement."""

from __future__ import annotations

from django.conf import settings
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import BasePermission

from accounts.utils import build_user_context
from role_config import DENIED_SSO_MESSAGE


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
        user_context = build_user_context(request.user)
        allowed_roles: frozenset[str] = getattr(
            settings, "ENTRA_SSO_ALLOWED_ROLES", frozenset()
        )
        return user_context["role"].lower() in allowed_roles
