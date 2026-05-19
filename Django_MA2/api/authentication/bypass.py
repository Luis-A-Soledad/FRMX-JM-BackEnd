"""Email bypass authentication for development/staging environments.

Allows authenticating via the ``X-Bypass-Email`` request header when
``settings.EMAIL_BYPASS_ENABLED`` is ``True``.  This class MUST NOT be
enabled in production (``DEBUG=False``); ``core/settings.py`` raises
``ImproperlyConfigured`` if that configuration is attempted.
"""

from __future__ import annotations

import logging
import re

from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework.authentication import BaseAuthentication

from accounts.models import Role, UserProfile

logger = logging.getLogger(__name__)

User = get_user_model()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailBypassAuthentication(BaseAuthentication):
    """Authenticate via ``X-Bypass-Email`` header (dev/staging only).

    Returns ``None`` (pass to next authenticator) when:
    - ``EMAIL_BYPASS_ENABLED`` is ``False``.
    - The header is absent.
    - The email format is invalid.
    - The email is not present in ``EMAIL_BYPASS_MAP``.

    On success, returns ``(user, {"bypass": True, "email": email, "role": role_name})``.
    The user is created on first login (``username=bypass_<email>``) with an unusable
    password, and a ``UserProfile`` linking to the mapped ``Role`` is also created.
    """

    def authenticate(self, request):
        if not getattr(settings, "EMAIL_BYPASS_ENABLED", False):
            return None

        raw_header = request.META.get("HTTP_X_BYPASS_EMAIL", "").strip()
        if not raw_header:
            return None

        email = raw_header.lower()
        if not _EMAIL_RE.match(email):
            return None

        bypass_map: dict[str, str] = getattr(settings, "EMAIL_BYPASS_MAP", {})
        role_name = bypass_map.get(email)
        if role_name is None:
            return None

        user = self._get_or_create_user(email, role_name)

        logger.warning(
            "EMAIL_BYPASS: authenticated %s as role=%s (dev-only)",
            email,
            role_name,
        )
        return (user, {"bypass": True, "email": email, "role": role_name})

    def authenticate_header(self, request) -> str:
        return 'Bearer realm="dev-bypass"'

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _get_or_create_user(email: str, role_name: str):
        username = f"bypass_{email}"
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email},
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])

        # Ensure UserProfile exists with the correct role
        try:
            role = Role.objects.get(name=role_name.upper())
        except Role.DoesNotExist:
            logger.error(
                "EMAIL_BYPASS: role '%s' not found in database — cannot authenticate %s",
                role_name,
                email,
            )
            return user

        UserProfile.objects.get_or_create(user=user, defaults={"role": role})

        return user
