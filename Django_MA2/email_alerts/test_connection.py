"""
test_connection.py — Prueba minima de conectividad a Databricks.

Uso:
    .\.venv\Scripts\python.exe email_alerts\test_connection.py

No necesita PAT token: usa DefaultAzureCredential (az login o VS Code login).
"""

from __future__ import annotations

import os
import sys

# Cargar .env si existe
try:
    from dotenv import load_dotenv, find_dotenv
    _env = find_dotenv()
    if _env:
        load_dotenv(_env)
        print(f"[.env cargado desde: {_env}]")
    else:
        print("[AVISO] .env no encontrado, usando variables del entorno del sistema]")
except ImportError:
    pass

import json
import sys
import requests

# Forzar UTF-8 en la salida de consola Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = os.getenv(
    "EMAIL_ALERTS_DATABRICKS_HOST",
    os.getenv("DATABRICKS_SQL_HOST", "adb-7405616902649001.1.azuredatabricks.net"),
).strip().replace("https://", "").replace("http://", "").rstrip("/")

# Scope de Azure AD para Databricks (fijo para toda instancia Azure Databricks)
DATABRICKS_AZURE_AD_SCOPE = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default"


# ── Paso 1: obtener token ──────────────────────────────────────────────────────

def get_token() -> str:
    """Intenta obtener token en este orden:
    1. Variable de entorno DATABRICKS_SQL_TOKEN (PAT)
    2. DefaultAzureCredential (az login, VS Code, Managed Identity)
    """
    # 1. PAT desde .env
    pat = os.getenv("DATABRICKS_SQL_TOKEN", "").strip()
    if pat and pat != "placeholder":
        print("  Usando PAT token desde DATABRICKS_SQL_TOKEN")
        return pat

    # 2. Azure AD via DefaultAzureCredential
    try:
        from azure.identity import DefaultAzureCredential
        print("  PAT no configurado — intentando DefaultAzureCredential (az login)...")
        cred = DefaultAzureCredential()
        token_obj = cred.get_token(DATABRICKS_AZURE_AD_SCOPE)
        print("  DefaultAzureCredential OK")
        return token_obj.token
    except ImportError:
        raise RuntimeError(
            "azure-identity no instalado. Ejecuta:\n"
            "  .venv\\Scripts\\pip install azure-identity"
        )
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo obtener token Azure AD: {exc}\n\n"
            "Soluciones:\n"
            "  1. Ejecuta 'az login' en esta terminal y reintenta\n"
            "  2. O pon DATABRICKS_SQL_TOKEN=dapi... en el .env"
        )


# ── Paso 2: listar warehouses disponibles ─────────────────────────────────────

def list_warehouses(token: str) -> list[dict]:
    """Lista los SQL Warehouses del workspace."""
    url = f"https://{HOST}/api/2.0/sql/warehouses"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if resp.status_code == 401:
        raise RuntimeError("401 Unauthorized — token inválido o sin permisos en Databricks.")
    if resp.status_code == 403:
        raise RuntimeError("403 Forbidden — tu cuenta no tiene acceso al workspace.")
    resp.raise_for_status()
    return resp.json().get("warehouses", [])


# ── Paso 3: SELECT 1 contra un warehouse ──────────────────────────────────────

def run_select_1(token: str, warehouse_id: str) -> bool:
    """Ejecuta SELECT 1 para confirmar que la consulta funciona."""
    url = f"https://{HOST}/api/2.0/sql/statements"
    payload = {
        "statement": "SELECT 1 AS ok",
        "warehouse_id": warehouse_id,
        "wait_timeout": "20s",
        "format": "JSON_ARRAY",
        "disposition": "INLINE",
    }
    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    state = data.get("status", {}).get("state", "UNKNOWN")
    return state == "SUCCEEDED"


# ── Paso 4: verificar acceso a la tabla target ────────────────────────────────

def check_table_access(token: str, warehouse_id: str, table: str) -> dict:
    """Ejecuta SELECT * LIMIT 1 para confirmar acceso a la tabla real."""
    url = f"https://{HOST}/api/2.0/sql/statements"
    payload = {
        "statement": f"SELECT * FROM {table} LIMIT 1",
        "warehouse_id": warehouse_id,
        "wait_timeout": "20s",
        "format": "JSON_ARRAY",
        "disposition": "INLINE",
    }
    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    target_table = os.getenv(
        "EMAIL_ALERTS_TABLE",
        "ey_data_ai_dev.alertas.email_alerts_operational",
    )

    print()
    print("=" * 55)
    print("  TEST DE CONECTIVIDAD DATABRICKS")
    print("=" * 55)
    print(f"  Host:   {HOST}")
    print(f"  Tabla:  {target_table}")
    print()

    # ── Token ──
    print("[1/4] Obteniendo token...")
    try:
        token = get_token()
        print("  ✓ Token obtenido\n")
    except RuntimeError as e:
        print(f"  ✗ {e}")
        sys.exit(1)

    # ── Warehouses ──
    print("[2/4] Listando SQL Warehouses disponibles...")
    try:
        warehouses = list_warehouses(token)
    except RuntimeError as e:
        print(f"  ✗ {e}")
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"  ✗ HTTP {e.response.status_code}: {e.response.text[:200]}")
        sys.exit(1)

    if not warehouses:
        print("  ✗ No se encontraron warehouses en el workspace.")
        sys.exit(1)

    print(f"  ✓ {len(warehouses)} warehouse(s) encontrado(s):\n")
    for wh in warehouses:
        estado = wh.get("state", "?")
        emoji = "🟢" if estado == "RUNNING" else "🟡" if estado == "STARTING" else "⚪"
        print(f"      {emoji}  ID: {wh['id']}  |  Nombre: {wh.get('name','?')}  |  Estado: {estado}")
    print()

    # Elegir el primer warehouse RUNNING o simplemente el primero
    running = [w for w in warehouses if w.get("state") == "RUNNING"]
    chosen = running[0] if running else warehouses[0]
    warehouse_id = chosen["id"]
    print(f"  → Usando warehouse: {chosen.get('name','?')} ({warehouse_id})\n")

    # Sugerir actualizar .env automáticamente
    current_wh = os.getenv("DATABRICKS_WAREHOUSE_ID", "placeholder")
    if current_wh in ("placeholder", "", None):
        print(f"  💡 Copia este warehouse_id en tu .env:")
        print(f"     DATABRICKS_WAREHOUSE_ID={warehouse_id}\n")

    # ── SELECT 1 ──
    print("[3/4] Probando ejecución de query (SELECT 1)...")
    try:
        ok = run_select_1(token, warehouse_id)
        if ok:
            print("  ✓ SELECT 1 → SUCCEEDED\n")
        else:
            print("  ✗ SELECT 1 no devolvió SUCCEEDED")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Error en SELECT 1: {e}")
        sys.exit(1)

    # ── Tabla target ──
    print(f"[4/4] Verificando acceso a tabla: {target_table}")
    try:
        result = check_table_access(token, warehouse_id, target_table)
        state = result.get("status", {}).get("state", "?")
        if state == "SUCCEEDED":
            columns = [
                c["name"]
                for c in result.get("manifest", {}).get("schema", {}).get("columns", [])
            ]
            row_count = len(result.get("result", {}).get("data_array") or [])
            print(f"  ✓ Acceso correcto: {len(columns)} columna(s), {row_count} fila(s) de muestra")
            print(f"  Columnas: {columns}")
        else:
            error = result.get("status", {}).get("error", {})
            print(f"  ✗ Query falló ({state}): {error.get('message', result)}")
            sys.exit(1)
    except requests.HTTPError as e:
        print(f"  ✗ HTTP {e.response.status_code}: {e.response.text[:300]}")
        sys.exit(1)
    except Exception as e:
        print(f"  ✗ Error: {e}")
        sys.exit(1)

    print()
    print("=" * 55)
    print("  ✅ TODO OK — Databricks accesible y tabla disponible")
    print("=" * 55)
    print()
    print(f"  Ahora actualiza tu .env con:")
    print(f"  DATABRICKS_WAREHOUSE_ID={warehouse_id}")
    print()


if __name__ == "__main__":
    main()
