"""Envío de alertas prioritarias por WhatsApp Business Cloud API (Meta).

Alcance: alertas A01/A02/A03/A06 (Velocidad, Diferencia, Reducción, Forma A),
que son las prioritarias acordadas con CCO. El mensaje usa una plantilla
pre-aprobada por Meta con 4 parámetros:

    Alerta: {{1}} en el {{2}} ocurrido {{3}} en la {{4}}
            nombre    tren     fecha/hora     PK

Este módulo contiene lógica pura (normalización de teléfono, mapeo de región,
armado de payload) testeable sin red, más el emisor HTTP. El envío real sólo se
dispara si ``settings.ALERTAS_WHATSAPP_ENABLED`` está activo y existen las
credenciales de Meta (token + phone_number_id), que aún están pendientes.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import requests
from django.conf import settings

from .helpers import _strip_accents

logger = logging.getLogger(__name__)

try:  # zoneinfo está en stdlib (3.9+); fallback defensivo
    from zoneinfo import ZoneInfo

    _MX_TZ = ZoneInfo("America/Mexico_City")
except Exception:  # pragma: no cover - entornos sin tzdata
    _MX_TZ = None


# ---------------------------------------------------------------------------
# Normalización de región (alerta -> bucket de silver.administrativo)
# ---------------------------------------------------------------------------
# Las dos tablas no comparten la misma codificación de región. La tabla de
# alertas usa CENTRO MEXICO / NORTE / PACIFICO / Desconocido / SIN_CATALOGO,
# mientras administrativo usa Centro / Norte / Pacifico / Ferrosur /
# "Centro y Ferrosur" / "Todo el sistema".  Reducimos ambos lados a un conjunto
# canónico y resolvemos por pertenencia.

# Catch-all: este bucket de administrativo recibe TODAS las alertas.
_REGION_BUCKET_TODO = "TODO EL SISTEMA"

# Alias normalizado (upper, sin acentos) de la región de la ALERTA -> canónica.
_ALERT_REGION_TO_CANON: dict[str, str] = {
    "NORTE": "NORTE",
    "CENTRO": "CENTRO",
    "CENTRO MEXICO": "CENTRO",
    "PACIFICO": "PACIFICO",
    "FERROSUR": "FERROSUR",
}

# Región del CONTACTO (administrativo) -> conjunto de regiones canónicas cubiertas.
_ADMIN_REGION_COVERAGE: dict[str, set[str]] = {
    "NORTE": {"NORTE"},
    "CENTRO": {"CENTRO"},
    "PACIFICO": {"PACIFICO"},
    "FERROSUR": {"FERROSUR"},
    "CENTRO Y FERROSUR": {"CENTRO", "FERROSUR"},
}


def _norm_region(value: Any) -> str:
    """Normaliza una región a UPPER sin acentos ni espacios extra."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", _strip_accents(str(value)).upper()).strip()


def alert_region_to_canon(region: Any) -> str | None:
    """Mapea la región de una alerta a su región canónica, o None si no aplica.

    Devuelve None para Desconocido/SIN_CATALOGO/vacío: esas alertas sólo
    alcanzan a contactos del bucket "Todo el sistema".
    """
    return _ALERT_REGION_TO_CANON.get(_norm_region(region))


def contacto_cubre_region(contacto_region: Any, alert_canon: str | None) -> bool:
    """Indica si un contacto debe recibir la alerta según su bucket de región."""
    bucket = _norm_region(contacto_region)
    if bucket == _REGION_BUCKET_TODO:
        return True  # catch-all: recibe todo, incluso región desconocida
    if alert_canon is None:
        return False
    return alert_canon in _ADMIN_REGION_COVERAGE.get(bucket, set())


# ---------------------------------------------------------------------------
# Normalización de teléfono a E.164 (México)
# ---------------------------------------------------------------------------

def to_e164_mx(raw: Any) -> str | None:
    """Convierte un teléfono crudo a E.164 mexicano (52 + 10 dígitos).

    silver.administrativo guarda números sin lada de país (10 dígitos) y
    Meta exige E.164 sin '+'.  Reglas:
      - Se conservan sólo dígitos.
      - Si ya trae 52/521 + 10 dígitos, se normaliza a 52 + 10.
      - 10 dígitos -> se antepone 52.
      - Menos de 10 dígitos -> inválido (None); se descarta y se loguea aguas
        arriba (hay registros de 9 dígitos mal capturados en la fuente).
    """
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    # Quitar prefijo de país si viene incluido (52 ó 521 del formato viejo).
    if len(digits) > 10:
        if digits.startswith("521"):
            digits = digits[3:]
        elif digits.startswith("52"):
            digits = digits[2:]
        else:
            digits = digits[-10:]
    if len(digits) != 10:
        return None
    return "52" + digits


# ---------------------------------------------------------------------------
# Formato de los parámetros del template
# ---------------------------------------------------------------------------

def format_fecha(last_event: Any) -> str:
    """Da formato legible (hora local MX) al timestamp de la alerta."""
    if last_event is None:
        return "—"
    s = str(last_event).strip()
    if not s:
        return "—"
    iso = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return s  # no parseable: devolver crudo en vez de fallar
    if _MX_TZ is not None and dt.tzinfo is not None:
        dt = dt.astimezone(_MX_TZ)
    return dt.strftime("%d/%m/%Y %H:%M")


def _clean_param(value: Any, default: str = "—") -> str:
    """Sanea un parámetro de template: nunca vacío, sin saltos de línea.

    Meta rechaza parámetros con newlines, tabs o más de 4 espacios seguidos.
    """
    if value is None:
        return default
    text = re.sub(r"[\n\r\t]+", " ", str(value)).strip()
    text = re.sub(r" {5,}", "    ", text)
    return text or default


_TIPO_ALERTA_TO_NOMBRE = {
    "Alerta_01": "Velocidad",
    "Alerta_02": "Diferencia",
    "Alerta_03": "Reduccion",
    "Alerta_06": "Forma A",
}


def build_template_params(row: dict[str, Any]) -> list[str]:
    """Extrae los 4 parámetros del template desde una fila de alerta.

    Orden: [nombre_alerta, train_id, fecha/hora, PK].
    """
    nombre = (
        row.get("nombre_alerta")
        or row.get("titulo")
        or _TIPO_ALERTA_TO_NOMBRE.get(str(row.get("tipo_alerta") or ""))
    )
    pk = row.get("detail_mile_post_at_start") or row.get("pkInicio")
    return [
        _clean_param(nombre),
        _clean_param(row.get("train_id")),
        _clean_param(format_fecha(row.get("last_event") or row.get("receivedDateTime"))),
        _clean_param(pk),
    ]


def build_template_payload(to_e164: str, params: list[str]) -> dict[str, Any]:
    """Arma el payload de mensaje de plantilla para la Cloud API de Meta."""
    return {
        "messaging_product": "whatsapp",
        "to": to_e164,
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_TEMPLATE_NAME,
            "language": {"code": settings.WHATSAPP_TEMPLATE_LANG},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in params],
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# Resolución de destinatarios
# ---------------------------------------------------------------------------

def resolve_destinatarios(
    alert_region: Any,
    contactos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filtra contactos por región y normaliza su teléfono a E.164.

    Devuelve una lista de dicts {nombre, telefono(E164), region, cargo} sin
    duplicados de teléfono. Descarta (logueando) teléfonos inválidos.
    """
    canon = alert_region_to_canon(alert_region)
    seen: set[str] = set()
    destinatarios: list[dict[str, Any]] = []
    for c in contactos:
        if not contacto_cubre_region(c.get("region"), canon):
            continue
        tel = to_e164_mx(c.get("telefono"))
        if tel is None:
            logger.warning(
                "Teléfono inválido en administrativo, se omite: nombre=%r region=%r",
                c.get("nombre"),
                c.get("region"),
            )
            continue
        if tel in seen:
            continue
        seen.add(tel)
        destinatarios.append(
            {
                "nombre": c.get("nombre"),
                "telefono": tel,
                "region": c.get("region"),
                "cargo": c.get("cargo"),
            }
        )
    return destinatarios


# ---------------------------------------------------------------------------
# Emisor HTTP
# ---------------------------------------------------------------------------

def _get_token() -> str:
    """Obtiene el token de la Cloud API desde env o Key Vault."""
    # Reutiliza el resolvedor env->KeyVault del servicio de Databricks.
    from .service import _get_env_or_kv

    return _get_env_or_kv(
        env_names=["WHATSAPP_TOKEN"],
        kv_secret_names=["WHATSAPP-TOKEN"],
    )


def send_template_message(to_e164: str, params: list[str]) -> dict[str, Any]:
    """Envía un mensaje de plantilla. Lanza RuntimeError si falla.

    Retorna la respuesta JSON de Meta (incluye el message id) en éxito.
    """
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    token = _get_token()
    if not phone_number_id or not token:
        raise RuntimeError(
            "WhatsApp no configurado: faltan WHATSAPP_PHONE_NUMBER_ID y/o WHATSAPP_TOKEN."
        )

    url = (
        f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}"
        f"/{phone_number_id}/messages"
    )
    payload = build_template_payload(to_e164, params)
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=settings.WHATSAPP_REQUEST_TIMEOUT_SECS,
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        body = e.response.text if e.response is not None else str(e)
        status_code = e.response.status_code if e.response is not None else "?"
        raise RuntimeError(f"WhatsApp API HTTP {status_code}: {body}") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error conectando a WhatsApp Cloud API: {e}") from e

    return resp.json()
