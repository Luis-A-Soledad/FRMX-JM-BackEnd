"""Acceso dinamico a tabla de alertas operacionales en Databricks.

Este modulo evita esquemas rigidos: cada fila se devuelve como dict con las
columnas reales que retorne Databricks en tiempo de ejecucion.

Utiliza Databricks REST API en lugar del conector SQL para evitar 
dependencias compiladas como thrift en Windows.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

import requests

from config import (
    DATABRICKS_AZURE_AD_SCOPE,
    EMAIL_ALERTS_DEFAULT_DATABRICKS_HOST,
    EMAIL_ALERTS_DEFAULT_TABLE_NAME,
    EMAIL_ALERTS_REQUEST_TIMEOUT_SECS,
)

DEFAULT_DATABRICKS_HOST = EMAIL_ALERTS_DEFAULT_DATABRICKS_HOST
DEFAULT_TABLE_NAME = EMAIL_ALERTS_DEFAULT_TABLE_NAME
REQUEST_TIMEOUT_SECS = EMAIL_ALERTS_REQUEST_TIMEOUT_SECS


def _get_required_env(*keys: str) -> str:
    """Retorna el primer env var no vacio de la lista de claves."""
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    keys_csv = ", ".join(keys)
    raise RuntimeError(f"Falta variable de entorno requerida: {keys_csv}")


@lru_cache(maxsize=1)
def _get_sp_credential():
    """Construye credencial de Service Principal desde variables de entorno."""
    tenant_id = os.environ.get("AZURE_TENANT_ID", "").strip()
    client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AZURE_CLIENT_SECRET", "").strip()
    if not all([tenant_id, client_id, client_secret]):
        raise RuntimeError(
            "Se requieren AZURE_TENANT_ID, AZURE_CLIENT_ID y AZURE_CLIENT_SECRET "
            "para autenticarse con el Service Principal."
        )
    from azure.identity import ClientSecretCredential
    return ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )


@lru_cache(maxsize=1)
def _get_secret_client():
    """Crea cliente de Key Vault con Service Principal, solo si KEY_VAULT_URL existe."""
    key_vault_url = os.getenv("KEY_VAULT_URL", "").strip()
    if not key_vault_url:
        return None

    try:
        from azure.keyvault.secrets import SecretClient
    except ImportError:
        return None

    return SecretClient(vault_url=key_vault_url, credential=_get_sp_credential())


def _read_secret_from_key_vault(secret_name: str) -> str:
    """Lee secreto de Key Vault; devuelve cadena vacia si no se puede leer."""
    if not secret_name:
        return ""

    client = _get_secret_client()
    if client is None:
        return ""

    try:
        return (client.get_secret(secret_name).value or "").strip()
    except Exception:
        return ""


def _get_env_or_kv(env_names: list[str], kv_secret_names: list[str]) -> str:
    """Resuelve primero env y luego Key Vault usando nombres configurables."""
    for env_name in env_names:
        value = os.getenv(env_name, "").strip()
        if value and value != "placeholder":
            return value

    for secret_name in kv_secret_names:
        value = _read_secret_from_key_vault(secret_name)
        if value and value != "placeholder":
            return value

    return ""


def _get_access_token() -> str:
    """Obtiene token AAD para Databricks usando el Service Principal."""
    return _get_sp_credential().get_token(DATABRICKS_AZURE_AD_SCOPE).token


def _discover_warehouse_id(host: str, token: str) -> str:
    """Descubre automaticamente un warehouse utilizable (RUNNING preferido)."""
    url = f"https://{host}/api/2.0/sql/warehouses"
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECS,
    )
    response.raise_for_status()
    warehouses = response.json().get("warehouses", [])
    if not warehouses:
        raise RuntimeError("No se encontraron SQL Warehouses en Databricks.")

    running = [w for w in warehouses if w.get("state") == "RUNNING"]
    chosen = running[0] if running else warehouses[0]
    chosen_id = chosen.get("id", "").strip()
    if not chosen_id:
        raise RuntimeError("No se pudo determinar warehouse_id automaticamente.")
    return chosen_id


def _serialize_dynamic_value(value: Any) -> Any:
    """Convierte tipos no JSON nativos manteniendo estructura dinamica."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    # Intenta parsear strings JSON (arrays u objetos)
    if isinstance(value, str):
        stripped = value.strip()
        if (stripped.startswith('[') and stripped.endswith(']')) or \
           (stripped.startswith('{') and stripped.endswith('}')):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                # Si no es JSON válido, retorna el string original
                return value
    return value


def _poll_until_done(
    api_url: str,
    statement_id: str,
    headers: dict,
    poll_interval: float = 1.5,
    max_wait: float = 55.0,
) -> dict:
    """Espera hasta que Databricks termine de ejecutar el statement."""
    elapsed = 0.0
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval
        resp = requests.get(
            f"{api_url}/{statement_id}",
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECS,
        )
        resp.raise_for_status()
        data = resp.json()
        state = data.get("status", {}).get("state", "")
        if state == "SUCCEEDED":
            return data
        if state in ("FAILED", "CANCELED", "CLOSED"):
            error = data.get("status", {}).get("error", {})
            raise RuntimeError(
                f"Databricks statement {state}: {error.get('message', data)}"
            )
    raise RuntimeError("Timeout esperando resultado de Databricks.")


def _resolve_connection() -> tuple[str, str, str, str]:
    """Resuelve host, warehouse_id, token y table_name para Databricks."""
    host = _get_env_or_kv(
        env_names=["EMAIL_ALERTS_DATABRICKS_HOST", "DATABRICKS_SQL_HOST"],
        kv_secret_names=[
            os.getenv("DATABRICKS_SQL_HOST_SECRET_NAME", "").strip(),
            "DATABRICKS-SQL-HOST",
        ],
    ) or DEFAULT_DATABRICKS_HOST
    host = host.replace("https://", "").replace("http://", "").rstrip("/")

    warehouse_id = _get_env_or_kv(
        env_names=["EMAIL_ALERTS_DATABRICKS_WAREHOUSE_ID", "DATABRICKS_WAREHOUSE_ID"],
        kv_secret_names=[
            os.getenv("DATABRICKS_WAREHOUSE_ID_SECRET_NAME", "").strip(),
            "DATABRICKS-WAREHOUSE-ID",
        ],
    )
    token = _get_access_token()
    table_name = _get_env_or_kv(
        env_names=["EMAIL_ALERTS_TABLE"],
        kv_secret_names=[
            os.getenv("EMAIL_ALERTS_TABLE_SECRET_NAME", "").strip(),
            "EMAIL-ALERTS-TABLE",
        ],
    ) or DEFAULT_TABLE_NAME

    if not warehouse_id:
        warehouse_id = _discover_warehouse_id(host=host, token=token)

    return host, warehouse_id, token, table_name


def _execute_statement(
    query: str,
    *,
    parameters: list[dict[str, str]] | None = None,
) -> tuple[list[str], list[list]]:
    """Ejecuta un SQL statement en Databricks y retorna (columns, rows).

    Reutiliza toda la logica de conexion, submit y polling.
    ``parameters`` se pasa directo al payload de Databricks Statement API
    para prevenir SQL injection en clausulas WHERE.
    """
    host, warehouse_id, token, _table = _resolve_connection()

    api_url = f"https://{host}/api/2.0/sql/statements"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "statement": query,
        "warehouse_id": warehouse_id,
        "wait_timeout": "30s",
        "format": "JSON_ARRAY",
        "disposition": "INLINE",
    }
    if parameters:
        payload["parameters"] = parameters

    try:
        response = requests.post(
            api_url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECS
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        body = e.response.text if e.response is not None else str(e)
        raise RuntimeError(f"Databricks API HTTP error: {e.response.status_code} — {body}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error conectando a Databricks REST API: {e}")

    data = response.json()
    state = data.get("status", {}).get("state", "")

    if state in ("PENDING", "RUNNING"):
        statement_id = data.get("statement_id")
        if not statement_id:
            raise RuntimeError("Databricks no devolvió statement_id para polling.")
        data = _poll_until_done(api_url, statement_id, headers)

    if data.get("status", {}).get("state") != "SUCCEEDED":
        error = data.get("status", {}).get("error", {})
        raise RuntimeError(
            f"Databricks query falló: {error.get('message', data)}"
        )

    columns: list[str] = [
        col["name"]
        for col in data.get("manifest", {})
        .get("schema", {})
        .get("columns", [])
    ]
    rows_raw: list[list] = data.get("result", {}).get("data_array") or []

    return columns, rows_raw


def _rows_to_dicts(columns: list[str], rows: list[list]) -> list[dict[str, Any]]:
    """Convierte columnas + filas raw en lista de dicts serializables."""
    if not columns or not rows:
        return []
    num_cols = len(columns)
    return [
        {
            col: _serialize_dynamic_value(row[i] if i < len(row) else None)
            for i, col in enumerate(columns)
        }
        for row in rows
    ]


@lru_cache(maxsize=8)
def _get_table_columns(table_name: str) -> set[str]:
    """Obtiene el esquema de la tabla para armar queries tolerantes a cambios."""
    cols, _rows = _execute_statement(f"SELECT * FROM {table_name} LIMIT 1")
    return set(cols)


def _first_existing(available: set[str], *candidates: str) -> str | None:
    """Retorna la primera columna existente en el esquema disponible."""
    for cand in candidates:
        if cand in available:
            return cand
    return None


def _resolve_timestamp_col(table_name: str, preferred: str) -> str:
    """Resuelve columna timestamp real con fallback razonable."""
    available = _get_table_columns(table_name)
    if preferred in available:
        return preferred

    fallback = _first_existing(
        available,
        "receivedDateTime",
        "last_event",
        "event_time_utc",
        "event_time",
        "event_timestamp",
        "created_at",
        "createdAt",
    )
    if fallback:
        return fallback
    raise RuntimeError(
        f"No se encontró columna timestamp válida en la tabla {table_name}."
    )


def _select_expr(alias: str, available: set[str], *candidates: str) -> str:
    """Construye expresión SELECT con alias y fallback a NULL."""
    chosen = _first_existing(available, *candidates)
    if chosen:
        return f"{chosen} AS {alias}"
    return f"CAST(NULL AS STRING) AS {alias}"


def _select_expr_end(
    alias: str,
    available: set[str],
    end_candidates: tuple[str, ...],
    fallback_candidates: tuple[str, ...],
) -> str:
    """Construye expresión de fin con COALESCE si hay columnas disponibles."""
    end_col = _first_existing(available, *end_candidates)
    fallback_col = _first_existing(available, *fallback_candidates)
    if end_col and fallback_col:
        return f"COALESCE(NULLIF({end_col}, ''), {fallback_col}) AS {alias}"
    if end_col:
        return f"{end_col} AS {alias}"
    if fallback_col:
        return f"{fallback_col} AS {alias}"
    return f"CAST(NULL AS STRING) AS {alias}"


def fetch_email_alerts_operational_rows(
    limit: int | None = None,
    only_today: bool = False,
    train_id: str | None = None,
) -> list[dict[str, Any]]:
    """Obtiene alertas agrupadas por train_id.

    Cada fila muestra la informacion de la alerta mas reciente de ese
    tren junto con el conteo total de alertas.
    Ordenado por last_event DESC.
    """
    _host, _wid, _tok, table_name = _resolve_connection()
    available = _get_table_columns(table_name)
    ts_col = _resolve_timestamp_col(
        table_name,
        os.getenv("ALERTAS_TIMESTAMP_COL", "receivedDateTime"),
    )

    loc_start_col = _first_existing(
        available,
        "region",
        "detail_location_at_start",
        "detail_location_current",
    )
    loc_end_col = _first_existing(available, "distrito", "detail_location_at_end")
    loc_end_fallback = _first_existing(
        available,
        "region",
        "detail_location_current",
        "detail_location_at_start",
    )
    mile_start_col = _first_existing(available, "detail_mile_post_at_start", "detail_mile_post_current")
    mile_end_col = _first_existing(available, "detail_mile_post_at_end")
    mile_end_fallback = _first_existing(available, "detail_mile_post_current", "detail_mile_post_at_start")

    loc_start_expr = (
        f"FIRST_VALUE({loc_start_col}) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS region"
        if loc_start_col
        else "CAST(NULL AS STRING) AS region"
    )
    loc_end_expr = (
        f"COALESCE(NULLIF(FIRST_VALUE({loc_end_col}) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC), ''), "
        f"FIRST_VALUE({loc_end_fallback}) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC)) AS distrito"
        if loc_end_col and loc_end_fallback
        else (
            f"FIRST_VALUE({loc_end_col}) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS distrito"
            if loc_end_col
            else (
                f"FIRST_VALUE({loc_end_fallback}) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS distrito"
                if loc_end_fallback
                else "CAST(NULL AS STRING) AS distrito"
            )
        )
    )
    mile_start_expr = (
        f"FIRST_VALUE({mile_start_col}) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS detail_mile_post_at_start"
        if mile_start_col
        else "CAST(NULL AS STRING) AS detail_mile_post_at_start"
    )
    mile_end_expr = (
        f"COALESCE(NULLIF(FIRST_VALUE({mile_end_col}) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC), ''), "
        f"FIRST_VALUE({mile_end_fallback}) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC)) AS detail_mile_post_at_end"
        if mile_end_col and mile_end_fallback
        else (
            f"FIRST_VALUE({mile_end_col}) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS detail_mile_post_at_end"
            if mile_end_col
            else (
                f"FIRST_VALUE({mile_end_fallback}) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS detail_mile_post_at_end"
                if mile_end_fallback
                else "CAST(NULL AS STRING) AS detail_mile_post_at_end"
            )
        )
    )
    crew_expr = _select_expr(
        "maquinista",
        available,
        "crew_eng_name",
        "maquinista",
    )

    conditions: list[str] = []
    params: list[dict[str, str]] = []
    if only_today:
        conditions.append(f"CAST({ts_col} AS DATE) = CURRENT_DATE()")
    if train_id:
        conditions.append("train_id = :train_id_param")
        params.append({"name": "train_id_param", "value": train_id, "type": "STRING"})
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = (
        f"SELECT "
        f"train_id, "
        f"MAX({ts_col}) OVER (PARTITION BY train_id) AS last_event, "
        f"FIRST_VALUE(asset_id) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS asset_id, "
        f"FIRST_VALUE(id_alerta) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS id_alerta, "
        f"FIRST_VALUE(alert_type_detected) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS titulo, "
        f"FIRST_VALUE(subject) OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS descripcion, "
        f"{loc_start_expr}, "
        f"{loc_end_expr}, "
        f"{mile_start_expr}, "
        f"{mile_end_expr}, "
        f"{crew_expr}, "
        f"COUNT(*) OVER (PARTITION BY train_id) AS alert_count, "
        f"ROW_NUMBER() OVER (PARTITION BY train_id ORDER BY {ts_col} DESC) AS rn "
        f"FROM {table_name} "
        f"{where_clause}"
    )
    # Keep only one row per train_id (the latest)
    query = (
        f"SELECT train_id, asset_id, last_event, id_alerta, titulo, "
        f"descripcion, region, distrito, maquinista, "
        f"detail_mile_post_at_start, detail_mile_post_at_end, alert_count "
        f"FROM ({query}) sub "
        f"WHERE rn = 1 "
        f"ORDER BY last_event DESC"
    )
    if limit is not None:
        query = f"{query} LIMIT {int(limit)}"

    columns, rows = _execute_statement(query, parameters=params or None)
    return _rows_to_dicts(columns, rows)


def get_alertas_table_name() -> str:
    """Retorna el nombre de la tabla de alertas configurada."""
    _host, _wid, _tok, table_name = _resolve_connection()
    return table_name


def fetch_alertas_page(
    page: int,
    size: int,
    timestamp_col: str | None = None,
    train_id: str | None = None,
    fecha: str | None = None,
) -> list[dict[str, Any]]:
    """Obtiene una pagina de alertas con ORDER BY timestamp DESC.

    Si se indica train_id filtra por ese tren, sino muestra todas.
    Si se indica fecha (YYYY-MM-DD) filtra alertas de ese dia.
    Retorna cada alerta individual (sin agrupar).
    """
    table_name = get_alertas_table_name()
    available = _get_table_columns(table_name)
    preferred_ts = timestamp_col or os.getenv("ALERTAS_TIMESTAMP_COL", "receivedDateTime")
    ts_col = _resolve_timestamp_col(table_name, preferred_ts)
    offset = (page - 1) * size

    conditions = []
    params = []
    if train_id:
        conditions.append("train_id = :train_id_param")
        params.append({"name": "train_id_param", "value": train_id, "type": "STRING"})
    if fecha:
        conditions.append(f"CAST({ts_col} AS DATE) = :fecha_param")
        params.append({"name": "fecha_param", "value": fecha, "type": "STRING"})

    train_filter = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    if not params:
        params = None

    loc_start_expr = _select_expr(
        "detail_location_at_start",
        available,
        "region",
        "detail_location_at_start",
        "detail_location_current",
    )
    loc_end_expr = _select_expr_end(
        "detail_location_at_end",
        available,
        ("distrito", "detail_location_at_end"),
        ("region", "detail_location_current", "detail_location_at_start"),
    )
    mile_start_expr = _select_expr(
        "detail_mile_post_at_start",
        available,
        "detail_mile_post_at_start",
        "detail_mile_post_current",
    )
    mile_end_expr = _select_expr_end(
        "detail_mile_post_at_end",
        available,
        ("detail_mile_post_at_end",),
        ("detail_mile_post_current", "detail_mile_post_at_start"),
    )

    crew_expr = _select_expr(
        "maquinista",
        available,
        "crew_eng_name",
        "maquinista",
    )

    query = (
        f"SELECT "
        f"id_alerta, "
        f"train_id, "
        f"asset_id, "
        f"alert_type_detected AS titulo, "
        f"subject AS descripcion, "
        f"{ts_col} AS last_event, "
        f"{loc_start_expr}, "
        f"{loc_end_expr}, "
        f"{mile_start_expr}, "
        f"{mile_end_expr}, "
        f"{crew_expr}, "
        f"detail_speed_at_start, "
        f"detail_speed_at_end, "
        f"detail_speed_current, "
        f"detail_speed_limit, "
        f"detail_max_speed, "
        f"detail_bp_pres_at_start, "
        f"detail_bp_pres_at_end, "
        f"prioridad "
        f"FROM {table_name} "
        f"{train_filter} "
        f"ORDER BY {ts_col} DESC "
        f"LIMIT {int(size)} OFFSET {int(offset)}"
    )

    columns, rows = _execute_statement(query, parameters=params)
    return _rows_to_dicts(columns, rows)


def fetch_alertas_count(train_id: str | None = None, fecha: str | None = None) -> int:
    """Retorna el total de alertas. Filtra por train_id y/o fecha si se indican."""
    table_name = get_alertas_table_name()
    ts_col = _resolve_timestamp_col(
        table_name,
        os.getenv("ALERTAS_TIMESTAMP_COL", "receivedDateTime"),
    )
    conditions = []
    params = []
    if train_id:
        conditions.append("train_id = :train_id_param")
        params.append({"name": "train_id_param", "value": train_id, "type": "STRING"})
    if fecha:
        conditions.append(f"CAST({ts_col} AS DATE) = :fecha_param")
        params.append({"name": "fecha_param", "value": fecha, "type": "STRING"})

    train_filter = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    if not params:
        params = None
    query = (
        f"SELECT COUNT(*) AS total "
        f"FROM {table_name} "
        f"{train_filter}"
    )
    columns, rows = _execute_statement(query, parameters=params)
    if rows and rows[0]:
        return int(rows[0][0])
    return 0


def fetch_alerta_by_id(alert_id: int) -> dict[str, Any] | None:
    """Obtiene una alerta por id_alerta. Retorna None si no existe."""
    table_name = get_alertas_table_name()
    query = f"SELECT * FROM {table_name} WHERE id_alerta = :alert_id LIMIT 1"
    parameters = [{"name": "alert_id", "value": str(alert_id), "type": "INT"}]
    columns, rows = _execute_statement(query, parameters=parameters)
    dicts = _rows_to_dicts(columns, rows)
    return dicts[0] if dicts else None


def fetch_alertas_since(since_timestamp: str | None = None) -> list[dict[str, Any]]:
    """Obtiene alertas nuevas posteriores a *since_timestamp*.

    Si *since_timestamp* es None (primera ejecución), devuelve las últimas
    50 alertas para establecer el estado inicial.

    Retorna cada alerta como dict crudo (sin normalizar).
    """
    table_name = get_alertas_table_name()
    available = _get_table_columns(table_name)
    ts_col = _resolve_timestamp_col(
        table_name,
        os.getenv("ALERTAS_TIMESTAMP_COL", "receivedDateTime"),
    )

    loc_start_expr = _select_expr(
        "detail_location_at_start",
        available,
        "region",
        "detail_location_at_start",
        "detail_location_current",
    )
    loc_end_expr = _select_expr_end(
        "detail_location_at_end",
        available,
        ("distrito", "detail_location_at_end"),
        ("region", "detail_location_current", "detail_location_at_start"),
    )
    mile_start_expr = _select_expr(
        "region",
        available,
        "region",
        "detail_mile_post_at_start",
        "detail_mile_post_current",
    )
    mile_end_expr = _select_expr_end(
        "distrito",
        available,
        ("distrito", "detail_location_at_end"),
        ("detail_mile_post_current", "detail_mile_post_at_start"),
    )

    crew_expr = _select_expr(
        "maquinista",
        available,
        "crew_eng_name",
        "maquinista",
    )

    if since_timestamp is None:
        query = (
            f"SELECT "
            f"id_alerta, train_id, asset_id, "
            f"alert_type_detected AS titulo, "
            f"subject AS descripcion, "
            f"{ts_col} AS last_event, "
            f"{loc_start_expr}, "
            f"{loc_end_expr}, "
            f"{mile_start_expr}, "
            f"{mile_end_expr}, "
            f"{crew_expr}, "
            f"prioridad "
            f"FROM {table_name} "
            f"ORDER BY {ts_col} DESC "
            f"LIMIT 50"
        )
        columns, rows = _execute_statement(query)
    else:
        query = (
            f"SELECT "
            f"id_alerta, train_id, asset_id, "
            f"alert_type_detected AS titulo, "
            f"subject AS descripcion, "
            f"{ts_col} AS last_event, "
            f"{loc_start_expr}, "
            f"{loc_end_expr}, "
            f"{mile_start_expr}, "
            f"{mile_end_expr}, "
            f"{crew_expr}, "
            f"prioridad "
            f"FROM {table_name} "
            f"WHERE {ts_col} > :since_ts "
            f"ORDER BY {ts_col} DESC "
            f"LIMIT 200"
        )
        parameters = [
            {"name": "since_ts", "value": since_timestamp, "type": "STRING"},
        ]
        columns, rows = _execute_statement(query, parameters=parameters)

    return _rows_to_dicts(columns, rows)


# ---------------------------------------------------------------------------
# TVF: Calificaciones de maquinistas
# ---------------------------------------------------------------------------

def fetch_calificaciones_maquinista(
    jefe_maquinista: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> list[dict[str, Any]]:
    """Llama a fn_calificaciones_maquinista(p_jefe_maquinista, p_fecha_inicio, p_fecha_fin).

    Retorna lista de dicts con: id_maquinista, nombre_maquinista,
    Score_Promedio, Alertas_Acumuladas, Frecuencia_Evento, Alerta_Comun.
    """
    query = (
        "SELECT * FROM ey_data_ai_dev.gold.fn_calificaciones_maquinista("
        ":p_fecha_inicio, :p_fecha_fin, :p_jefe_maquinista)"
    )
    parameters = [
        {"name": "p_fecha_inicio", "value": fecha_inicio, "type": "DATE"},
        {"name": "p_fecha_fin", "value": fecha_fin, "type": "DATE"},
        {"name": "p_jefe_maquinista", "value": jefe_maquinista, "type": "STRING"},
    ]
    columns, rows = _execute_statement(query, parameters=parameters)
    return _rows_to_dicts(columns, rows)


def fetch_frecuencia_alertas_maquinista(
    id_maquinista: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> list[dict[str, Any]]:
    """Llama a fn_frecuencia_alertas_maquinista(p_id_maquinista, p_fecha_inicio, p_fecha_fin).

    Retorna lista de dicts con: Prioridad, Alerta, Frecuencia.
    """
    query = (
        "SELECT * FROM ey_data_ai_dev.gold.fn_frecuencia_alertas_maquinista("
        ":p_id_maquinista, :p_fecha_inicio, :p_fecha_fin)"
    )
    parameters = [
        {"name": "p_id_maquinista", "value": id_maquinista, "type": "STRING"},
        {"name": "p_fecha_inicio", "value": fecha_inicio, "type": "DATE"},
        {"name": "p_fecha_fin", "value": fecha_fin, "type": "DATE"},
    ]
    columns, rows = _execute_statement(query, parameters=parameters)
    return _rows_to_dicts(columns, rows)


def fetch_resumen_semanal_maquinista(
    id_maquinista: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> list[dict[str, Any]]:
    """Llama a fn_resumen_semanal_maquinista(p_id_maquinista, p_fecha_inicio, p_fecha_fin).

    Retorna lista de dicts con: Score, Total_Alertas, Distrito, Fecha.
    """
    query = (
        "SELECT * FROM ey_data_ai_dev.gold.fn_resumen_semanal_maquinista("
        ":p_id_maquinista, :p_fecha_inicio, :p_fecha_fin)"
    )
    parameters = [
        {"name": "p_id_maquinista", "value": id_maquinista, "type": "STRING"},
        {"name": "p_fecha_inicio", "value": fecha_inicio, "type": "DATE"},
        {"name": "p_fecha_fin", "value": fecha_fin, "type": "DATE"},
    ]
    columns, rows = _execute_statement(query, parameters=parameters)
    return _rows_to_dicts(columns, rows)


def fetch_viajes_maquinista(
    id_maquinista: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> list[dict[str, Any]]:
    """Llama a fn_viajes_maquinista(p_id_maquinista, p_fecha_inicio, p_fecha_fin).

    Retorna lista de dicts con: train_id, ponderation, event_count, date,
    region, district, alerts (array de structs con priority, message, count).
    """
    query = (
        "SELECT * FROM ey_data_ai_dev.gold.fn_viajes_maquinista("
        ":p_id_maquinista, :p_fecha_inicio, :p_fecha_fin)"
    )
    parameters = [
        {"name": "p_id_maquinista", "value": id_maquinista, "type": "STRING"},
        {"name": "p_fecha_inicio", "value": fecha_inicio, "type": "DATE"},
        {"name": "p_fecha_fin", "value": fecha_fin, "type": "DATE"},
    ]
    columns, rows = _execute_statement(query, parameters=parameters)
    return _rows_to_dicts(columns, rows)


def fetch_to_maquinista(
    id_maquinista: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> list[dict[str, Any]]:
    """Llama a fn_to_maquinista(p_id_maquinista, p_fecha_inicio, p_fecha_fin).

    Retorna lista de dicts con: train_id, date, improper,
    to_data (array de structs con to_value, pk_inicio, pk_fin, distrito, region, hora).
    """
    query = (
        "SELECT * FROM ey_data_ai_dev.gold.fn_to_maquinista("
        ":p_id_maquinista, :p_fecha_inicio, :p_fecha_fin)"
    )
    parameters = [
        {"name": "p_id_maquinista", "value": id_maquinista, "type": "STRING"},
        {"name": "p_fecha_inicio", "value": fecha_inicio, "type": "DATE"},
        {"name": "p_fecha_fin", "value": fecha_fin, "type": "DATE"},
    ]
    columns, rows = _execute_statement(query, parameters=parameters)
    return _rows_to_dicts(columns, rows)
