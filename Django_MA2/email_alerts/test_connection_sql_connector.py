"""
test_connection_sql_connector.py - Prueba minima de conectividad con Databricks SQL Connector.

Uso:
    .\\.venv\\Scripts\\python.exe email_alerts\\test_connection_sql_connector.py

Notas:
- Este script valida conexion SQL directa (no usa REST statements API).
- Se autentica exclusivamente con Service Principal (AZURE_TENANT_ID / CLIENT_ID / CLIENT_SECRET).
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache

import requests


# Cargar variables desde .env si python-dotenv esta instalado.
try:
    from dotenv import find_dotenv, load_dotenv

    _env = find_dotenv()
    if _env:
        load_dotenv(_env)
        print(f"[.env cargado desde: {_env}]")
except ImportError:
    pass


def _normalize_host(raw_host: str) -> str:
    """Convierte host con/ sin esquema a solo hostname."""
    return raw_host.strip().replace("https://", "").replace("http://", "").rstrip("/")


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
    """Obtiene un secreto desde Key Vault; devuelve vacio si no esta disponible."""
    if not secret_name:
        return ""

    client = _get_secret_client()
    if client is None:
        return ""

    try:
        value = client.get_secret(secret_name).value
        return (value or "").strip()
    except Exception:
        return ""


def _get_env_or_kv(env_names: list[str], kv_secret_names: list[str]) -> str:
    """Resuelve valor desde variables de entorno y luego Key Vault."""
    for env_name in env_names:
        value = os.getenv(env_name, "").strip()
        if value and value != "placeholder":
            return value

    for secret_name in kv_secret_names:
        value = _read_secret_from_key_vault(secret_name)
        if value and value != "placeholder":
            print(f"  Valor obtenido desde Key Vault: {secret_name}")
            return value

    return ""


def _build_http_path_from_warehouse_id(warehouse_id: str) -> str:
    """Construye HTTP Path a partir de warehouse_id."""
    return f"/sql/1.0/warehouses/{warehouse_id}"


def _build_http_path() -> str:
    """Obtiene HTTP Path desde env o lo construye con warehouse_id."""
    http_path = _get_env_or_kv(
        env_names=["DATABRICKS_SQL_HTTP_PATH"],
        kv_secret_names=[
            os.getenv("DATABRICKS_SQL_HTTP_PATH_SECRET_NAME", "").strip(),
            "DATABRICKS-SQL-HTTP-PATH",
        ],
    )
    if http_path:
        return http_path

    warehouse_id = _get_env_or_kv(
        env_names=["EMAIL_ALERTS_DATABRICKS_WAREHOUSE_ID", "DATABRICKS_WAREHOUSE_ID"],
        kv_secret_names=[
            os.getenv("DATABRICKS_WAREHOUSE_ID_SECRET_NAME", "").strip(),
            "DATABRICKS-WAREHOUSE-ID",
        ],
    )
    if not warehouse_id or warehouse_id == "placeholder":
        return ""
    return _build_http_path_from_warehouse_id(warehouse_id)


def _get_access_token() -> str:
    """Obtiene token AAD para Databricks usando el Service Principal."""
    databricks_scope = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default"
    print("  Autenticando con Service Principal...")
    token = _get_sp_credential().get_token(databricks_scope).token
    print("  Token obtenido via Service Principal")
    return token


def _discover_warehouse_id(host: str, token: str) -> str:
    """Descubre automaticamente un warehouse utilizable (RUNNING preferido)."""
    url = f"https://{host}/api/2.0/sql/warehouses"
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    if response.status_code == 401:
        raise RuntimeError("401 Unauthorized al listar warehouses.")
    if response.status_code == 403:
        raise RuntimeError("403 Forbidden al listar warehouses (sin permisos).")
    response.raise_for_status()

    warehouses = response.json().get("warehouses", [])
    if not warehouses:
        raise RuntimeError("No se encontraron SQL Warehouses en el workspace.")

    running = [w for w in warehouses if w.get("state") == "RUNNING"]
    chosen = running[0] if running else warehouses[0]
    chosen_id = chosen.get("id", "")
    if not chosen_id:
        raise RuntimeError("No se pudo determinar el id del warehouse seleccionado.")

    print(
        "  Warehouse seleccionado automaticamente: "
        f"{chosen.get('name', '?')} ({chosen_id}) estado={chosen.get('state', '?')}"
    )
    return chosen_id


def _truncate(value: object, max_len: int = 120) -> str:
    """Recorta valores largos para una salida de terminal legible."""
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def main() -> None:
    """Ejecuta una prueba de conectividad SQL y una consulta a la tabla objetivo."""
    raw_host = _get_env_or_kv(
        env_names=["EMAIL_ALERTS_DATABRICKS_HOST", "DATABRICKS_SQL_HOST"],
        kv_secret_names=[
            os.getenv("DATABRICKS_SQL_HOST_SECRET_NAME", "").strip(),
            "DATABRICKS-SQL-HOST",
        ],
    )
    if not raw_host:
        raw_host = "adb-7405616902649001.1.azuredatabricks.net"

    host = _normalize_host(raw_host)
    http_path = _build_http_path()
    table = _get_env_or_kv(
        env_names=["EMAIL_ALERTS_TABLE"],
        kv_secret_names=[
            os.getenv("EMAIL_ALERTS_TABLE_SECRET_NAME", "").strip(),
            "EMAIL-ALERTS-TABLE",
        ],
    ) or "ey_data_ai_dev.alertas.email_alerts_operational"

    print("\n" + "=" * 65)
    print(" TEST DE CONECTIVIDAD - DATABRICKS SQL CONNECTOR")
    print("=" * 65)
    print(f" Host:      {host}")
    print(f" HTTP Path: {http_path or '[auto]'}")
    print(f" Tabla:     {table}\n")

    print("[1/3] Obteniendo token...")
    token = _get_access_token()
    print("  OK\n")

    if not http_path:
        print("[2/3] DATABRICKS_SQL_HTTP_PATH no definido; descubriendo warehouse automaticamente...")
        discovered_warehouse_id = _discover_warehouse_id(host, token)
        http_path = _build_http_path_from_warehouse_id(discovered_warehouse_id)
        print(f"  HTTP Path resuelto: {http_path}")
        print(f"  Sugerido para .env: DATABRICKS_WAREHOUSE_ID={discovered_warehouse_id}\n")
        step2_title = "[3/4]"
        step3_title = "[4/4]"
    else:
        step2_title = "[2/3]"
        step3_title = "[3/3]"

    print(f"{step2_title} Abriendo conexion con databricks-sql-connector...")
    try:
        from databricks import sql
    except ImportError as exc:
        raise RuntimeError(
            "No se encontro databricks-sql-connector. "
            "Instala con .venv\\Scripts\\pip install databricks-sql-connector"
        ) from exc

    try:
        with sql.connect(
            server_hostname=host,
            http_path=http_path,
            access_token=token,
        ) as connection:
            print("  Conexion OK\n")

            print(f"{step3_title} Ejecutando validaciones SQL...")
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                one_row = cursor.fetchone()
                print(f"  SELECT 1 => {one_row}")

                cursor.execute(f"SELECT * FROM {table} LIMIT 1")
                sample_row = cursor.fetchone()
                columns = [desc[0] for desc in (cursor.description or [])]
                print(f"  Tabla accesible, columnas detectadas: {len(columns)}")

                if sample_row is None:
                    print("  La tabla no devolvio filas en LIMIT 1")
                else:
                    row_dict = {
                        col: sample_row[idx]
                        for idx, col in enumerate(columns)
                        if idx < len(sample_row)
                    }
                    preferred_fields = [
                        "id_alerta",
                        "event_id",
                        "subject",
                        "from_email",
                        "alert_type_detected",
                        "event_time_utc",
                    ]
                    visible_fields = [f for f in preferred_fields if f in row_dict]
                    if not visible_fields:
                        visible_fields = columns[:6]

                    print("  Datos de muestra (campos clave):")
                    for field in visible_fields:
                        print(f"    - {field}: {_truncate(row_dict.get(field))}")

    except Exception as exc:
        print(f"  Error de conexion/consulta: {exc}")
        print("\nSugerencias:")
        print("  1) Verifica host/http_path")
        print("  2) Verifica permisos del usuario/SP sobre SQL Warehouse y tabla")
        print("  3) Verifica que AZURE_TENANT_ID, AZURE_CLIENT_ID y AZURE_CLIENT_SECRET sean correctos")
        raise

    print("\n" + "=" * 65)
    print(" OK - SQL Connector funcionando")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
