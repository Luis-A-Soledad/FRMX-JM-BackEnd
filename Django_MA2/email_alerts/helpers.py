"""Normalizacion de columnas y mapeo al contrato de respuesta de alertas."""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any


# ---------------------------------------------------------------------------
# Mapa de aliases conocidos -> nombre canónico (camelCase del frontend)
# ---------------------------------------------------------------------------
# Cada clave es una variante normalizada (lowercase, sin tildes, sin espacios
# extras). El valor es el nombre canónico que espera el frontend.

_ALIAS_MAP: dict[str, str] = {
    # ── id ──
    "id_alerta": "id",
    "alert_id2": "id",
    "alertid2": "id",
    # ── locomotora (asset_id en Databricks) ──
    "asset_id": "locomotora",
    "locomotora": "locomotora",
    # ── ultimaAlerta (titulo en Databricks) ──
    "titulo": "ultimaAlerta",
    "ultima alerta": "ultimaAlerta",
    "ultima_alerta": "ultimaAlerta",
    "ultimaalerta": "ultimaAlerta",
    # ── descripcion (existe directamente en Databricks) ──
    "descripcion": "descripcion",
    # ── region (detail_location_at_start en Databricks) ──
    "detail_location_at_start": "region",
    "region": "region",
    # ── distrito (detail_location_at_end en Databricks) ──
    "detail_location_at_end": "distrito",
    "distrito": "distrito",
    # ── pkInicio (detail_mile_post_at_start en Databricks) ──
    "detail_mile_post_at_start": "pkInicio",
    "pk inicio": "pkInicio",
    "pk_inicio": "pkInicio",
    "pkinicio": "pkInicio",
    # ── pkFin (detail_mile_post_at_end en Databricks) ──
    "detail_mile_post_at_end": "pkFin",
    "pk fin": "pkFin",
    "pk_fin": "pkFin",
    "pkfin": "pkFin",
    # ── tipoAlerta ──
    "tipo_alerta": "tipoAlerta",
    # ── horaActualizacion ──
    "hora actualizacion": "horaActualizacion",
    "hora_actualizacion": "horaActualizacion",
    "horaactualizacion": "horaActualizacion",
    # ── alertasActivas (no existe en tabla actual, se mantiene para emails) ──
    "# alertas activas": "alertasActivas",
    "alertas activas": "alertasActivas",
    "alertas_activas": "alertasActivas",
    "alertasactivas": "alertasActivas",
    "alert_count": "alertasActivas",
    # ── maquinista (no existe en tabla actual, se mantiene para emails) ──
    "crew_eng_name": "maquinista",
    "maquinista": "maquinista",
    # ── prioridad ──
    "prioridad": "prioridad",
}

# Campos principales del contrato (excluyendo 'extras')
_KNOWN_CANONICAL: set[str] = {
    "id",
    "titulo",
    "descripcion",
    "estado",
    "fechaCreacion",
    "alertasActivas",
    "locomotora",
    "maquinista",
    "region",
    "distrito",
    "pkInicio",
    "pkFin",
    "ultimaAlerta",
    "horaActualizacion",
    "tipoAlerta",
    "prioridad",
}


def _strip_accents(text: str) -> str:
    """Elimina tildes/diacríticos de un string."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.category(ch).startswith("M"))


def _normalize_key(raw: str) -> str:
    """Convierte un nombre de columna crudo a forma normalizada para lookup."""
    lowered = raw.strip().lower()
    return _strip_accents(lowered)


def normalize_columns(row: dict[str, Any]) -> dict[str, Any]:
    """Toma un dict con columnas crudas de Databricks y retorna uno con keys canónicas.

    Las columnas reconocidas se mapean a su nombre canónico.
    Las no reconocidas se dejan con su key original (irán a ``extras``).
    """
    result: dict[str, Any] = {}
    for raw_key, value in row.items():
        norm = _normalize_key(raw_key)
        canonical = _ALIAS_MAP.get(norm)
        if canonical:
            result[canonical] = value
        else:
            result[raw_key] = value
    return result


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _safe_number(value: Any, default: int | float = 0) -> int | float:
    if value is None:
        return default
    try:
        num = float(value)
        return int(num) if num == int(num) else num
    except (TypeError, ValueError):
        return default


def _normalize_alert_id(value: Any) -> int | float | str:
    """Normaliza el id de alerta sin perder IDs alfanuméricos.

    - Si viene numérico (o string numérico), retorna número.
    - Si viene string no numérico (UUID/código), retorna string limpio.
    - Si no viene valor, retorna 0 para compatibilidad hacia atrás.
    """
    if value is None:
        return 0
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return 0
        try:
            num = float(raw)
            return int(num) if num == int(num) else num
        except ValueError:
            return raw
    try:
        num = float(value)
        return int(num) if num == int(num) else num
    except (TypeError, ValueError):
        return str(value)


def _prioridad_label(value: Any) -> str | None:
    """Convierte el número de prioridad a etiqueta: Alta, Media o Baja.

    Rango 1-13 donde menor número = mayor urgencia:
      1-4  → Alta
      5-9  → Media
      10-13 → Baja
    """
    if value is None:
        return None
    try:
        num = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    if num <= 4:
        return "Alta"
    if num <= 9:
        return "Media"
    return "Baja"


def _compose_descripcion(row: dict[str, Any]) -> str:
    """Genera descripcion a partir de campos del row normalizado."""
    loco = _safe_str(row.get("locomotora"), "?")
    reg = _safe_str(row.get("region"), "?")
    dist = _safe_str(row.get("distrito"), "?")
    pk_ini = _safe_str(row.get("pkInicio"), "?")
    pk_fin = _safe_str(row.get("pkFin"), "?")
    return f"Locomotora {loco}, Región {reg}, Distrito {dist}, PK {pk_ini}–{pk_fin}."


def _derive_estado(row: dict[str, Any]) -> str:
    """Calcula estado: ACTIVA si alertasActivas > 0, sino INACTIVA."""
    if "estado" in row and row["estado"] is not None:
        return str(row["estado"])
    activas = _safe_number(row.get("alertasActivas"), 0)
    return "ACTIVA" if activas > 0 else "INACTIVA"


def _format_iso_timestamp(value: Any) -> str | None:
    """Convierte un valor timestamp a ISO-8601 con Z si no tiene tz."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Si ya termina en Z o tiene offset (+/-), devolver tal cual
    if s.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", s):
        return s
    # Reemplazar espacio por T si es formato "YYYY-MM-DD HH:MM:SS..."
    s = s.replace(" ", "T", 1)
    return s + "Z"


_TIPO_ALERTA_TO_TYPE: dict[str, str] = {
    "Alerta_01": "Velocidad",
    "Alerta_02": "Diferencia",
    "Alerta_03": "Reduccion",
    "Alerta_06": "Forma A",
}


def _resolve_type(tipo_alerta: Any) -> str | None:
    """Mapea tipo_alerta (ej. Alerta_01) a su etiqueta de type."""
    if tipo_alerta is None:
        return None
    return _TIPO_ALERTA_TO_TYPE.get(str(tipo_alerta).strip(), str(tipo_alerta))


def build_alerta_response(
    normalized: dict[str, Any],
    timestamp_col: str | None = None,
) -> dict[str, Any]:
    """Produce el contrato de respuesta de alertas para REST/WS."""
    ts_candidates = [
        timestamp_col,
        "last_event",
        "event_time_utc",
        "receivedDateTime",
        "horaActualizacion",
        "created_at",
        "createdAt",
    ]
    ts_raw = None
    for cand in ts_candidates:
        if cand and normalized.get(cand) is not None:
            ts_raw = normalized.get(cand)
            break
    fecha_creacion = _format_iso_timestamp(ts_raw)

    id_val = _normalize_alert_id(normalized.get("id"))

    titulo = _safe_str(normalized.get("titulo") or normalized.get("ultimaAlerta"), "")
    ultima_alerta = _safe_str(normalized.get("ultimaAlerta") or normalized.get("titulo"), "")

    alerta = {
        "id": id_val,
        "titulo": titulo,
        "type": _resolve_type(normalized.get("tipoAlerta") or normalized.get("tipo_alerta")),
        "nombre_alerta": normalized.get("nombre_alerta"),
        "train_id": normalized.get("train_id"),
        "descripcion": _safe_str(normalized.get("descripcion"), "") or _compose_descripcion(normalized),
        "estado": _derive_estado(normalized),
        "fechaCreacion": fecha_creacion,
        "alertasActivas": _safe_number(normalized.get("alertasActivas"), 0),
        "locomotora": _safe_str(normalized.get("locomotora"), ""),
        "maquinista": _safe_str(normalized.get("maquinista"), ""),
        "region": _safe_str(normalized.get("region"), ""),
        "distrito": _safe_str(normalized.get("distrito"), ""),
        "pkInicio": normalized.get("pkInicio"),
        "pkFin": normalized.get("pkFin"),
        "ultimaAlerta": ultima_alerta,
        "prioridad": _prioridad_label(normalized.get("prioridad")),
        "last_event": _format_iso_timestamp(normalized.get("last_event")),
        "detail_max_speed": normalized.get("detail_max_speed"),
        "detail_speed_limit": normalized.get("detail_speed_limit"),
        "detail_bp_pres_at_start": normalized.get("detail_bp_pres_at_start"),
        "detail_bp_pres_at_end": normalized.get("detail_bp_pres_at_end"),
    }

    return alerta
