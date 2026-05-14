from rest_framework import serializers
from accounts.models import Role
from accounts.utils import ROLE_ANON, ROLE_UNKNOWN

# Valores canónicos de role que puede devolver el servidor.
# Incluye los roles de BD + los sintéticos generados por build_user_context.
_ROLE_VALUES = [*Role.RoleChoices.values, ROLE_ANON, ROLE_UNKNOWN]


def _default_scopes() -> dict:
    """Factory para evitar default mutable compartido entre instancias."""
    return {"fleets": [], "regions": []}


class ChatRequestSerializer(serializers.Serializer):
    question = serializers.CharField(
        required=True,
        max_length=2000,
        help_text="Pregunta para el multiagente",
    )
    session_id = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="ID de sesión existente. Si no se envía, se crea una nueva.",
    )
    # DEPRECATED: role is derived server-side from UserProfile.
    # Kept for backward compatibility with existing clients.
    role = serializers.ChoiceField(
        choices=Role.RoleChoices.values,
        required=False,
        allow_null=True,
        default=None,
        help_text="DEPRECATED — El rol se obtiene del perfil del usuario en el servidor.",
    )


class ChatResponseSerializer(serializers.Serializer):
    answer = serializers.CharField()
    decision = serializers.CharField()
    orchestrator_reason = serializers.CharField()
    session_id = serializers.CharField()
    last_db_table = serializers.DictField(required=False, allow_null=True)
    last_error = serializers.CharField(allow_blank=True)
    # Legacy — se mantiene por compatibilidad con clientes existentes.
    role = serializers.ChoiceField(
        choices=Role.RoleChoices.values,
        required=False,
        allow_null=True,
        default=None,
    )
    # Nuevos campos derivados de build_user_context
    role = serializers.ChoiceField(
        choices=_ROLE_VALUES,
        required=False,
        allow_null=True,
        default=None,
        help_text="Rol canónico: CCO, JEFE_MAQUINISTAS, OPERADOR, ANON, UNKNOWN",
    )
    scopes = serializers.DictField(
        required=False,
        default=_default_scopes,
        help_text='Alcances del usuario: {"fleets": [], "regions": []}',
    )
