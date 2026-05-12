"""
agent_runner_mock.py
--------------------
Mock del agent_runner para desarrollo sin credenciales de LLM.
Devuelve respuestas simuladas con la misma interfaz que el real.

Activar con:  MOCK_AGENT=true  en tu .env o variables de entorno.
"""
from __future__ import annotations

import uuid
from typing import Any

# ─── Sesiones en memoria (misma interfaz que el runner real) ─────────────────
_sessions: dict[str, str] = {}


def get_or_create_session(session_id: str | None = None) -> str:
    if session_id and session_id in _sessions:
        return session_id
    new_id = session_id or str(uuid.uuid4())
    _sessions[new_id] = str(uuid.uuid4())
    return new_id


def delete_session(session_id: str) -> bool:
    return _sessions.pop(session_id, None) is not None


def run_agent(question: str, session_id: str, rol: str | None = None, user_context: dict[str, Any] | None = None) -> dict:
    """
    Devuelve una respuesta mock con la misma estructura que el agente real.
    """
    return {
        "answer": (
            f"[MOCK] Recibí tu pregunta: '{question}'. "
            "Este es un entorno de desarrollo sin conexión al LLM."
        ),
        "decision": "mock",
        "orchestrator_reason": "Modo mock activo — sin credenciales de LLM",
        "session_id": session_id,
        "last_db_table": None,
        "last_error": "",
        "rol": (user_context or {}).get("role") or rol,
    }
