"""Poller híbrido de alertas.

En cada iteración emite dos tipos de eventos:
1) ``snapshot_alertas`` con el estado agrupado por tren (formato idéntico
    a GET /api/alertas/alertas-por-loco-principal).
2) ``snapshot_alertas_list`` con todas las alertas del contrato de
    GET /api/alertas/ (consolidado en un solo payload).
3) ``delta_alertas`` con alertas nuevas detectadas desde el último timestamp.

Se inicia automáticamente cuando ALERTAS_POLLER_ENABLED=1 (default)
desde EmailAlertsConfig.ready().
"""

from __future__ import annotations

import logging
import math
import os
import threading
from collections import deque
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .helpers import build_alerta_response, normalize_columns
from .group_names import safe_train_group_name
from .service import (
    fetch_alertas_count,
    fetch_alertas_page,
    fetch_alertas_since,
    fetch_email_alerts_operational_rows,
)

logger = logging.getLogger(__name__)

_scheduler_started = False
_lock = threading.Lock()
_last_delta_timestamp: str | None = None
_recent_delta_history: deque[dict] = deque(maxlen=500)
_DEFAULT_ALERTAS_LIST_PAGE = 1
_DEFAULT_ALERTAS_LIST_SIZE = 20


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def _row_to_operational_contract(row: dict[str, Any]) -> dict[str, Any]:
    """Convierte una fila incremental al contrato del endpoint principal."""
    return {
        "train_id": _safe_str(row.get("train_id")),
        "asset_id": _safe_str(row.get("asset_id")),
        "last_event": _safe_str(row.get("last_event") or row.get("receivedDateTime")),
        "id_alerta": _safe_str(row.get("id_alerta")),
        "titulo": _safe_str(row.get("titulo") or row.get("alert_type_detected")),
        "descripcion": _safe_str(row.get("descripcion") or row.get("subject")),
        "region": _safe_str(
            row.get("region")
            or row.get("detail_location_at_start")
            or row.get("detail_location_current")
        ),
        "distrito": _safe_str(
            row.get("distrito")
            or row.get("detail_location_at_end")
            or row.get("detail_location_current")
            or row.get("detail_location_at_start")
        ),
        "maquinista": _safe_str(row.get("maquinista") or row.get("crew_eng_name")),
        "detail_mile_post_at_start": _safe_str(
            row.get("detail_mile_post_at_start") or row.get("detail_mile_post_current")
        ),
        "detail_mile_post_at_end": _safe_str(
            row.get("detail_mile_post_at_end")
            or row.get("detail_mile_post_current")
            or row.get("detail_mile_post_at_start")
        ),
        "alert_count": 1,
    }


def _broadcast_snapshot(channel_layer, rows: list[dict]):
    """Envía snapshot global y por tren con formato del endpoint principal."""
    async_to_sync(channel_layer.group_send)(
        "alertas_all",
        {
            "type": "alerta.nueva",
            "data": {
                "event": "snapshot_alertas",
                "data": rows,
                "count": len(rows),
            },
        },
    )

    for row in rows:
        train_id = row.get("train_id")
        if not train_id:
            continue
        group_name = safe_train_group_name(train_id)
        if not group_name:
            continue
        try:
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": "alerta.nueva",
                    "data": {
                        "event": "snapshot_alertas",
                        "train_id": str(train_id),
                        "data": [row],
                        "count": 1,
                    },
                },
            )
        except Exception:
            logger.warning(
                "No se pudo enviar snapshot al grupo de train_id=%r (group=%s)",
                train_id,
                group_name,
                exc_info=True,
            )


def _build_alertas_list_payload() -> dict[str, Any]:
    """Construye snapshot_alertas_list con la misma lógica de /api/alertas."""
    ts_col = os.getenv("ALERTAS_TIMESTAMP_COL", "receivedDateTime")
    page = _DEFAULT_ALERTAS_LIST_PAGE
    size = _DEFAULT_ALERTAS_LIST_SIZE
    base_path = "/api/alertas/"

    rows = fetch_alertas_page(page, size, timestamp_col=ts_col)
    total_items = fetch_alertas_count()

    total_pages = math.ceil(total_items / size) if total_items > 0 else 1
    has_next = page < total_pages
    has_prev = page > 1

    data = [
        build_alerta_response(normalize_columns(row), timestamp_col=ts_col)
        for row in rows
    ]

    return {
        "event": "snapshot_alertas_list",
        "data": data,
        "count": len(data),
        "pagination": {
            "page": page,
            "size": size,
            "totalItems": total_items,
            "totalPages": total_pages,
            "hasNext": has_next,
            "hasPrev": has_prev,
        },
        "links": {
            "self": f"{base_path}?page={page}&size={size}",
            "next": f"{base_path}?page={page + 1}&size={size}" if has_next else None,
            "prev": f"{base_path}?page={page - 1}&size={size}" if has_prev else None,
        },
    }


def _broadcast_alertas_list_snapshot(channel_layer):
    """Envía snapshot completo con contrato de /api/alertas."""
    try:
        payload = _build_alertas_list_payload()
    except Exception:
        logger.exception("Error construyendo snapshot para /api/alertas")
        return

    total_items = payload.get("pagination", {}).get("totalItems", 0)
    if total_items == 0:
        return

    async_to_sync(channel_layer.group_send)(
        "alertas_all",
        {
            "type": "alerta.nueva",
            "data": payload,
        },
    )


def _broadcast_delta(channel_layer, alertas_nuevas: list[dict]):
    """Envía deltas globales y por tren (solo nuevas alertas)."""
    async_to_sync(channel_layer.group_send)(
        "alertas_all",
        {
            "type": "alerta.nueva",
            "data": {
                "event": "delta_alertas",
                "data": alertas_nuevas,
                "count": len(alertas_nuevas),
            },
        },
    )

    trains_seen: dict[str, list[dict]] = {}
    for alerta in alertas_nuevas:
        train_id = alerta.get("train_id")
        if train_id:
            trains_seen.setdefault(str(train_id), []).append(alerta)

    for train_id, train_alertas in trains_seen.items():
        group_name = safe_train_group_name(train_id)
        if not group_name:
            continue
        try:
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": "alerta.nueva",
                    "data": {
                        "event": "delta_alertas",
                        "train_id": train_id,
                        "data": train_alertas,
                        "count": len(train_alertas),
                    },
                },
            )
        except Exception:
            logger.warning(
                "No se pudo enviar delta al grupo de train_id=%r (group=%s)",
                train_id,
                group_name,
                exc_info=True,
            )


def _poll_and_broadcast():
    """Ejecuta una iteración híbrida del polling.

    1. Snapshot agrupado por tren (endpoint principal)
    2. Snapshot completo de /api/alertas (todas las alertas)
    3. Delta incremental por timestamp (solo nuevas alertas)
    """
    global _last_delta_timestamp

    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning("Channel layer no disponible, saltando broadcast")
        return

    # 1) Snapshot agrupado por tren
    try:
        rows = fetch_email_alerts_operational_rows(only_today=False)
    except Exception:
        logger.exception("Error consultando Databricks en el poller")
        rows = []

    if rows:
        _broadcast_snapshot(channel_layer, rows)
        _broadcast_alertas_list_snapshot(channel_layer)
        logger.info("Poller: snapshot broadcast — %d trenes", len(rows))

    # 2) Delta incremental de alertas nuevas
    try:
        rows_delta = fetch_alertas_since(_last_delta_timestamp)
    except Exception:
        logger.exception("Error consultando delta incremental en el poller")
        return

    if not rows_delta:
        return

    max_ts = _last_delta_timestamp
    changed_train_ids: set[str] = set()
    latest_delta_per_train: dict[str, dict[str, Any]] = {}
    for row in rows_delta:
        train_id = row.get("train_id")
        if train_id:
            train_key = str(train_id)
            changed_train_ids.add(train_key)
            prev = latest_delta_per_train.get(train_key)
            prev_ts = str(prev.get("last_event") or prev.get("receivedDateTime") or "") if prev else ""
            curr_ts = str(row.get("last_event") or row.get("receivedDateTime") or "")
            if prev is None or curr_ts >= prev_ts:
                latest_delta_per_train[train_key] = row

        row_ts = row.get("last_event") or row.get("receivedDateTime")
        if row_ts and (max_ts is None or str(row_ts) > str(max_ts)):
            max_ts = str(row_ts)

    _last_delta_timestamp = max_ts

    if not changed_train_ids:
        return

    # Delta con mismo contrato del endpoint principal.
    # Si el snapshot ya trae el tren, reutilizamos esa fila; si no, usamos fallback.
    rows_by_train: dict[str, dict[str, Any]] = {
        str(row.get("train_id")): row for row in rows if row.get("train_id")
    }
    alertas_nuevas: list[dict] = []
    for train_id in changed_train_ids:
        row = rows_by_train.get(train_id)
        if row is None:
            fallback = latest_delta_per_train.get(train_id)
            if fallback is None:
                continue
            row = _row_to_operational_contract(fallback)
        alertas_nuevas.append(row)
        _recent_delta_history.append(row)

    if not alertas_nuevas:
        return

    _broadcast_delta(channel_layer, alertas_nuevas)
    logger.info(
        "Poller: delta broadcast — %d alertas nuevas (hist=%d)",
        len(alertas_nuevas),
        len(_recent_delta_history),
    )


def start_poller():
    """Arranca APScheduler con el job de polling en un hilo daemon.

    Guarded para ejecutarse solo una vez por proceso.
    """
    global _scheduler_started

    with _lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    from django.conf import settings

    interval = getattr(settings, "ALERTAS_POLL_INTERVAL_SECS", 10)

    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _poll_and_broadcast,
        "interval",
        seconds=interval,
        id="alertas_databricks_poller",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Poller de alertas iniciado (cada %ds)", interval)
