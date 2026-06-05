"""
databricks_client_resumenes.py
------------------------------
Cliente para consumir el Serving Endpoint del AGENTE DE RESUMENES en Databricks.

Es una copia independiente de databricks_client.py (que sirve al multiagente),
para que ambos agentes coexistan sin afectarse. Apunta al endpoint
'multiagente_resumen' en lugar de 'multiagente-ferromex'.

El agente de resumenes vive en Databricks y se expone como un endpoint HTTP.
Django solo envia el request y devuelve la respuesta.

Autenticacion: Service Principal de Azure (igual que el multiagente).
"""
from __future__ import annotations

import json
import uuid
import requests
import os
from typing import Any
from config import get_settings

# ─── Settings ────────────────────────────────────────────────────────────────
settings = get_settings()

# Scope fijo de Databricks en Azure — siempre es este
_DATABRICKS_SCOPE = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default"


class DatabricksResumenesClient:
    """
    Cliente para consumir el Serving Endpoint del Agente de Resumenes en Databricks.
    Maneja sesiones en memoria y llama al endpoint con el formato correcto.
    Soporta autenticacion via Service Principal de Azure.
    """

    def __init__(self):
        self.endpoint_url = os.getenv(
            "DATABRICKS_RESUMEN_ENDPOINT_URL",
            f"{settings.databricks_host.rstrip('/')}/serving-endpoints/multiagente_resumen/invocations"
        )
        self._sessions: dict[str, str] = {}

    def _get_token(self) -> str:
        # Opción 1: Service Principal
        tenant_id = os.getenv("AZURE_TENANT_ID")
        client_id = os.getenv("AZURE_CLIENT_ID")
        client_secret = os.getenv("AZURE_CLIENT_SECRET")

        if tenant_id and client_id and client_secret:
            try:
                from azure.identity import ClientSecretCredential
                credential = ClientSecretCredential(
                    tenant_id=tenant_id,
                    client_id=client_id,
                    client_secret=client_secret,
                )
                token = credential.get_token(_DATABRICKS_SCOPE)
                print("[DATABRICKS_RESUMENES] Token obtenido via Service Principal")
                return token.token
            except Exception as e:
                print(f"[DATABRICKS_RESUMENES] Service Principal falló: {e}")

        # Opción 2: Databricks CLI (fallback local)
        try:
            import subprocess, json
            result = subprocess.run(
                [r"c:\Users\FP923HG\.vscode\extensions\databricks.databricks-2.10.6-win32-x64\bin\databricks.exe",
                "auth", "token", "--profile", "multiagente_ferromex"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                token_data = json.loads(result.stdout)
                print("[DATABRICKS_RESUMENES] Token obtenido via Databricks CLI")
                return token_data.get("access_token", "")
        except Exception as e:
            print(f"[DATABRICKS_RESUMENES] CLI falló: {e}")

        raise RuntimeError("No se encontró autenticación disponible.")

    # ─── Sesion helpers ───────────────────────────────────────────────────────
    def get_or_create_session(self, session_id: str | None) -> str:
        """Retorna session_id existente o crea uno nuevo."""
        if session_id and session_id in self._sessions:
            return session_id
        new_id = session_id or str(uuid.uuid4())
        self._sessions[new_id] = new_id
        return new_id

    def delete_session(self, session_id: str) -> bool:
        """Elimina una sesión. Retorna True si existía."""
        return self._sessions.pop(session_id, None) is not None

    # ─── Cliente del endpoint ─────────────────────────────────────────────────
    def run_agent(
        self,
        question: str | None = None,
        session_id: str = "",
        role: str = "ANON",
        region: str | None = None,
        view: str | None = None,
        filters: dict | None = None,
        user_email: str | None = None,
        data: list | None = None,
    ) -> dict[str, Any]:
        """
        Llama al Serving Endpoint del Agente de Resumenes y retorna la respuesta.

        Args:
            question: Pregunta libre (modo alternativo, opcional si se envia view)
            session_id: ID de sesión
            role: Rol del usuario (jefe_maquinistas, cco, otro)
            region: Región del usuario (opcional)
            view: Id de la vista a resumir (modo principal)
            filters: Filtros de la vista (dict). Se envia como JSON string.
            user_email: Identidad del usuario (para resolver region del jefe en Databricks)

        Returns:
            dict con la respuesta del agente de resumenes
        """
        token = self._get_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # 'filters' y 'data' viajan como JSON string para encajar en la signature del modelo.
        filters_json = json.dumps(filters or {}, ensure_ascii=False)
        # data=None  -> ""  (no se proveyo data; el agente usara Genie)
        # data=[...] -> JSON (incluso [] fuerza el data-path SIN Genie)
        data_json = json.dumps(data, ensure_ascii=False) if data is not None else ""

        payload = {
            "dataframe_records": [
                {
                    "question": question or "",
                    "session_id": session_id,
                    "role": role,
                    "region": region,
                    "view": view or "",
                    "filters": filters_json,
                    "user_email": user_email or "",
                    "data": data_json,
                }
            ]
        }

        print(f"[DATABRICKS_RESUMENES] Llamando endpoint: {self.endpoint_url}")
        print(f"[DATABRICKS_RESUMENES] role: {role}, region: {region}")

        try:
            response = requests.post(
                self.endpoint_url,
                headers=headers,
                json=payload,
                timeout=120,
            )

            if response.status_code != 200:
                print(f"[DATABRICKS_RESUMENES] Error HTTP {response.status_code}: {response.text}")
                return {
                    "answer": f"Error al llamar al agente: HTTP {response.status_code}",
                    "decision": "error",
                    "orchestrator_reason": "",
                    "last_db_table": None,
                    "last_calificador_table": None,
                    "last_error": response.text[:2000],
                    "session_id": session_id,
                    "role": role,
                    "region": region,
                }

            data = response.json()
            predictions = data.get("predictions", {})

            print(f"[DATABRICKS_RESUMENES] Respuesta recibida: decision={predictions.get('decision')}")

            return {
                "answer": predictions.get("answer", "No se obtuvo respuesta."),
                "decision": predictions.get("decision", "unknown"),
                "orchestrator_reason": predictions.get("orchestrator_reason", ""),
                "last_db_table": predictions.get("last_db_table"),
                "last_calificador_table": predictions.get("last_calificador_table"),
                "last_error": predictions.get("last_error", ""),
                "session_id": predictions.get("session_id", session_id),
                "role": predictions.get("role", role),
                "region": predictions.get("region", region),
            }

        except requests.exceptions.Timeout:
            print("[DATABRICKS_RESUMENES] Timeout al llamar al endpoint")
            return {
                "answer": "El agente tardó demasiado en responder. Por favor intenta de nuevo.",
                "decision": "error",
                "orchestrator_reason": "",
                "last_db_table": None,
                "last_calificador_table": None,
                "last_error": "Timeout",
                "session_id": session_id,
                "role": role,
                "region": region,
            }

        except Exception as e:
            print(f"[DATABRICKS_RESUMENES] Error: {e}")
            return {
                "answer": f"Error inesperado: {str(e)}",
                "decision": "error",
                "orchestrator_reason": "",
                "last_db_table": None,
                "last_calificador_table": None,
                "last_error": str(e),
                "session_id": session_id,
                "role": role,
                "region": region,
            }


# ─── Singleton ────────────────────────────────────────────────────────────────
_client = DatabricksResumenesClient()


# ─── Funciones públicas ───────────────────────────────────────────────────────
def get_or_create_session(session_id: str | None) -> str:
    return _client.get_or_create_session(session_id)


def delete_session(session_id: str) -> bool:
    return _client.delete_session(session_id)


def run_agent(
    question: str | None = None,
    session_id: str = "",
    role: str = "ANON",
    region: str | None = None,
    view: str | None = None,
    filters: dict | None = None,
    user_email: str | None = None,
    data: list | None = None,
) -> dict[str, Any]:
    return _client.run_agent(
        question=question,
        session_id=session_id,
        role=role,
        region=region,
        view=view,
        filters=filters,
        user_email=user_email,
        data=data,
    )
