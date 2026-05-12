"""
role_config.py
--------------
Define los permisos de acceso por role para el multiagente.

roles disponibles:
- JEFE_MAQUINISTAS: acceso limitado (RAG + db)
- CCO: acceso completo
- ANON: acceso completo (redefinible en el futuro)

Para modificar permisos, solo edita el dict PERMISSIONS.
Para agregar un nuevo role, agrega una entrada nueva en PERMISSIONS.
Para agregar un nuevo agente, agrega la key en cada role que corresponda.
"""
from __future__ import annotations

# ─── Mapa de permisos por role ─────────────────────────────────────────────────
# Cada role tiene una lista de agentes a los que puede acceder.
# Si un agente NO está en la lista, el acceso será denegado
# y se redirigirá al general_agent con un mensaje amable.

PERMISSIONS: dict[str, list[str]] = {
    "JEFE_MAQUINISTAS": [
        "rag",
        "db",
        "general",
    ],
    "CCO": [
        "db",
        "rag",
        "calificador",
        "summary",
        "general",
    ],
    "ANON": [
        "general",
    ],
}

# ─── Mensajes de acceso denegado por agente ───────────────────────────────────
# Mensaje amable que se muestra cuando el role no tiene permiso.
# El general_agent lo usará para responder al usuario.

DENIED_MESSAGES: dict[str, str] = {
    "db": (
        "Lo siento, no tienes permisos para realizar consultas a la base de datos. "
        "Si necesitas información de datos, contacta a tu CCO."
    ),
    "summary": (
        "Lo siento, no tienes permisos para generar resúmenes ejecutivos. "
        "Si necesitas un resumen, contacta a tu CCO."
    ),
    "calificador": (
        "Lo siento, no tienes permisos para acceder al proceso de calificación."
    ),
    "rag": (
        "Lo siento, no tienes permisos para consultar los documentos y reglamentos."
    ),
}

# Mensaje genérico para agentes sin mensaje específico
DEFAULT_DENIED_MESSAGE = (
    "Lo siento, no tienes permisos para acceder a esta funcionalidad. "
    "Contacta a tu administrador si crees que esto es un error."
)


# ─── Funciones públicas ───────────────────────────────────────────────────────

def has_permission(role: str, agent: str) -> bool:
    """
    Verifica si un role tiene permiso para usar un agente.

    Args:
        role: El role del usuario (ej: "JEFE_MAQUINISTAS", "CCO", "ANON")
        agent: El agente al que quiere acceder (ej: "db", "rag", "calificador")

    Returns:
        True si tiene permiso, False si no.
    """
    # Si el role no existe en el mapa, usar permisos de "ANON" como fallback
    allowed = PERMISSIONS.get(role.upper(), PERMISSIONS.get("ANON", []))
    return agent in allowed


def get_denied_message(agent: str) -> str:
    """
    Retorna el mensaje amable de acceso denegado para un agente específico.

    Args:
        agent: El agente al que se intentó acceder sin permiso.

    Returns:
        Mensaje de acceso denegado.
    """
    return DENIED_MESSAGES.get(agent, DEFAULT_DENIED_MESSAGE)


def get_allowed_agents(role: str) -> list[str]:
    """
    Retorna la lista de agentes permitidos para un role.

    Args:
        role: El role del usuario.

    Returns:
        Lista de agentes permitidos.
    """
    return PERMISSIONS.get(role.upper(), PERMISSIONS.get("ANON", []))


# ─── Mapa de regiones y sus distritos ────────────────────────────────────────
# Cada región contiene los distritos (estados/ciudades) que la conforman.
# Esto permite validar que un JEFE_MAQUINISTAS solo consulte su región.

REGION_DISTRITOS: dict[str, list[str]] = {
    "norte": [
        "Chihuahua", "Sonora", "Coahuila", "Nuevo León",
        "Tamaulipas", "Durango", "Sinaloa",
    ],
    "centro": [
        "Ciudad de México", "Estado de México", "Hidalgo",
        "Tlaxcala", "Puebla", "Querétaro", "Guanajuato",
    ],
    "sur": [
        "Oaxaca", "Chiapas", "Veracruz", "Tabasco",
        "Campeche", "Yucatán", "Quintana Roo", "Guerrero",
    ],
    "pacifico": [
        "Jalisco", "Colima", "Michoacán", "Nayarit",
        "Zacatecas", "Aguascalientes", "San Luis Potosí",
    ],
}


def get_distritos_for_region(region: str) -> list[str]:
    """Retorna los distritos de una región."""
    return REGION_DISTRITOS.get(region.lower(), [])


def validate_region_access(question: str, region: str) -> tuple[bool, str]:
    """
    Valida que la pregunta no mencione distritos de otras regiones.

    Returns:
        (True, "") si el acceso es válido
        (False, mensaje) si menciona un distrito de otra región
    """
    if not region:
        return True, ""

    question_lower = question.lower()
    user_region = region.lower()
    user_distritos = [d.lower() for d in REGION_DISTRITOS.get(user_region, [])]

    # Buscar si la pregunta menciona algún distrito de OTRA región
    for other_region, distritos in REGION_DISTRITOS.items():
        if other_region == user_region:
            continue
        for distrito in distritos:
            if distrito.lower() in question_lower:
                return False, (
                    f"El distrito '{distrito}' pertenece a la región '{other_region.capitalize()}'. "
                    f"Tu acceso está limitado a la región '{region.capitalize()}' "
                    f"(distritos: {', '.join(REGION_DISTRITOS[user_region])})."
                )

    return True, ""


# MAQUINISTAS_POR_REGION: dict[str, list[str]] = {
#     "norte": ["M001", "M002", "M003"],
#     "centro": ["M004", "M005"],
#     "sur": ["M006", "M007"],
#     "pacifico": ["M008", "M009", "M010"],
# }


# def validate_maquinista_access(question: str, region: str) -> tuple[bool, str]:
#     """Valida que la pregunta no mencione maquinistas de otras regiones."""
#     ...

# Mensaje para endpoints SSO con role no autorizado
DENIED_SSO_MESSAGE = (
    "No tienes el rol necesario para acceder a este recurso. "
    "Contacta a tu administrador si crees que esto es un error."
)


# --- Roles permitidos via SSO ---
ALLOWED_SSO_ROLES = frozenset({"cco", "jefe_maquinistas"})


def is_sso_role_allowed(role: str) -> bool:
    return role.lower() in ALLOWED_SSO_ROLES
