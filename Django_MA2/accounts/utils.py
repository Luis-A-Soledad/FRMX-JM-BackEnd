from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)

ROLE_ANON: str = "ANON"
ROLE_UNKNOWN: str = "UNKNOWN"


def build_user_context(user: AbstractBaseUser | AnonymousUser) -> dict[str, Any]:
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
        return {
            "user_id": None,
            "email": None,
            "role": ROLE_ANON,
            "scopes": {"fleets": [], "regions": []},
        }

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

    return {
        "user_id": user.pk,
        "email": email,
        "role": role,
        "scopes": {"fleets": [], "regions": []},
    }
