"""Utilidades para nombres de grupos de Django Channels."""

from __future__ import annotations

import hashlib
import re

_INVALID_GROUP_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
_MAX_GROUP_LEN = 99  # Channels exige longitud < 100


def safe_train_group_name(train_id: object) -> str | None:
    """Convierte train_id a un nombre de grupo válido para Channels.

    Regla de Channels: solo ASCII alfanumérico, '-', '_' o '.' y largo < 100.
    """
    if train_id is None:
        return None

    raw = str(train_id).strip()
    if not raw:
        return None

    safe = _INVALID_GROUP_CHARS.sub("_", raw).strip("._-")
    if not safe:
        safe = "unknown"

    group = f"train_{safe}"
    if len(group) <= _MAX_GROUP_LEN:
        return group

    # Si excede el límite, truncamos y agregamos hash para unicidad estable.
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    max_prefix_len = _MAX_GROUP_LEN - len("train_") - 1 - len(digest)
    prefix = safe[:max_prefix_len]
    return f"train_{prefix}_{digest}"
