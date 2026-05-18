#from rest_framework.views import APIView
#from rest_framework.response import Response
#from rest_framework import status
#
#from .serializers import ChatRequestSerializer, ChatResponseSerializer
#from .agent_runner import run_agent, get_or_create_session, delete_session
#
#
#class ChatView(APIView):
#    """
#    POST /api/chat/
#    Envía una pregunta al multiagente y recibe la respuesta.
#
#    Body JSON:
#    {
#        "question": "dame todas las alertas del maquinista 3",
#        "session_id": "opcional-uuid-de-sesion-previa"
#    }
#
#    Response JSON:
#    {
#        "answer": "Se encontraron 3 alertas...",
#        "decision": "db",
#        "orchestrator_reason": "la consulta requiere datos",
#        "session_id": "uuid-de-sesion",
#        "last_db_table": null,
#        "last_error": ""
#    }
#    """
#
#    def post(self, request):
#        serializer = ChatRequestSerializer(data=request.data)
#        if not serializer.is_valid():
#            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
#
#        question = serializer.validated_data["question"]
#        session_id = serializer.validated_data.get("session_id")
#
#        # Obtener o crear sesión
#        session_id = get_or_create_session(session_id)
#
#        try:
#            result = run_agent(question=question, session_id=session_id)
#        except Exception as e:
#            return Response(
#                {"error": f"Error ejecutando el agente: {str(e)}"},
#                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
#            )
#
#        response_serializer = ChatResponseSerializer(data=result)
#        if response_serializer.is_valid():
#            return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
#
#        # Si el serializer falla, devolver el resultado crudo de todas formas
#        return Response(result, status=status.HTTP_200_OK)
#
#class SessionView(APIView):
#    """
#    DELETE /api/session/
#    Limpia la sesión actual (borra memoria del agente).
#
#    Body JSON:
#    {
#        "session_id": "uuid-de-sesion"
#    }
#    """
#
#    def delete(self, request):
#        session_id = request.data.get("session_id")
#        if not session_id:
#            return Response(
#                {"error": "session_id es requerido"},
#                status=status.HTTP_400_BAD_REQUEST,
#            )
#
#        deleted = delete_session(session_id)
#        if deleted:
#            return Response(
#                {"message": f"Sesión {session_id} eliminada correctamente."},
#                status=status.HTTP_200_OK,
#            )
#        return Response(
#            {"error": f"Sesión {session_id} no encontrada."},
#            status=status.HTTP_404_NOT_FOUND,
#        )
#
#
#

import os

import requests as http_requests
from django.conf import settings as django_settings
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication

from .authentication.entra import EntraBearerAuthentication
from .permissions import IsAllowedSSORole
from .serializers import (
    ChatRequestSerializer,
    ChatResponseSerializer,
    SSOTokenExchangeSerializer,
)
from accounts.utils import build_user_context

# if os.getenv("MOCK_AGENT", "").strip().lower() in ("1", "true", "yes"):
#     from .agent_runner_mock import run_agent, get_or_create_session, delete_session
# else:
#     from .agent_runner import run_agent, get_or_create_session, delete_session

if os.getenv("MOCK_AGENT", "").strip().lower() in ("1", "true", "yes"):
    from .databricks_client import run_agent, get_or_create_session, delete_session
else:
    from .databricks_client import run_agent, get_or_create_session, delete_session


class HealthView(APIView):
    """
    GET /api/health/
    Verifica que el servidor está vivo.
    """

    def get(self, request):
        return Response({"status": "ok", "message": "Multiagente API corriendo."})


 
# def _chat_authenticators():
#    """Build authenticator list at request time so settings overrides work.
#
#    ENTRA_AUTH_ENABLED=True  → [EntraBearerAuthentication] only.
#      JWTAuthentication is excluded to avoid the 401 token_not_valid error
#      when a valid Entra Bearer token is sent.
#
#    ENTRA_AUTH_ENABLED=False → [JWTAuthentication] (dev mode).
#      JWTAuthentication is safe here because no Entra tokens will be sent
#      in this mode. It also provides the WWW-Authenticate header so that
#      IsAllowedSSORole can return proper 401 (not 403) when ENFORCE=True.
#      """
#   if getattr(django_settings, "ENTRA_AUTH_ENABLED", False):
#       return [EntraBearerAuthentication()]
#   return [JWTAuthentication()]

def _entra_first_authenticators():
    """Build authenticator list at request time so settings overrides work.

    Order:
    1. EntraBearerAuthentication (if ENTRA_AUTH_ENABLED).
    2. JWTAuthentication — only when ENTRA_AUTH_ENABLED=False (dev mode).
       Excluded when Entra is active to prevent SimpleJWT from rejecting
       valid Entra Bearer tokens with 'token_not_valid'.
    """
    authenticators = []
    if getattr(django_settings, "ENTRA_AUTH_ENABLED", False):
        authenticators.append(EntraBearerAuthentication())
    else:
        authenticators.append(JWTAuthentication())
    return authenticators



class ChatView(APIView):
    """
    POST /api/chat/
    Envía una pregunta al multiagente y recibe la respuesta.

    Body JSON:
    {
        "question": "dame todas las alertas del maquinista 3",
        "session_id": "opcional-uuid-de-sesion-previa",
        "role": "jefe_maquinistas",
        "region": "Colima"
    }

    Response JSON:
    {
        "answer": "Se encontraron 3 alertas...",
        "decision": "db",
        "orchestrator_reason": "la consulta requiere datos",
        "session_id": "uuid-de-sesion",
        "last_db_table": null,
        "last_error": "",
        "role": "CCO",
        "region": "Colima"
    }
    """

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        # return _chat_authenticators()
        return _entra_first_authenticators()

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        question = serializer.validated_data["question"]
        incoming_session_id = serializer.validated_data.get("session_id")

        # ✅ Obtener o crear sesión (CLAVE)
        session_id = get_or_create_session(incoming_session_id)

        # Contexto del usuario derivado server-side (ignora 'rol' del cliente)
        user_context = build_user_context(request.user, request=request)

        try:
            result = run_agent(
                question=question,
                role = user_context["role"],
                session_id=session_id
            )
        except Exception as e:
            return Response(
                {
                    "error": f"Error ejecutando el agente: {str(e)}",
                    "session_id": session_id,  # ✅ incluso en error
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ✅ Garantizar que el session_id SIEMPRE vuelva
        result["session_id"] = session_id
        result["role"] = user_context["role"]
        result["scopes"] = user_context["scopes"]

        response_serializer = ChatResponseSerializer(data=result)
        if response_serializer.is_valid():
            return Response(
                response_serializer.validated_data,
                status=status.HTTP_200_OK
            )

        # ✅ Fallback seguro
        return Response(result, status=status.HTTP_200_OK)
    


class SessionView(APIView):
    """
    DELETE /api/session/

    Elimina una sesión activa y su memoria asociada en el multiagente.

    Body JSON:
    {
        "session_id": "uuid-de-sesion"
    }

    Respuesta exitosa:
    {
        "message": "Sesión eliminada correctamente",
        "session_id": "uuid-de-sesion"
    }
    """

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _entra_first_authenticators()
        #return _chat_authenticators()

    def delete(self, request):
        session_id = request.data.get("session_id")

        if not session_id:
            return Response(
                {"error": "session_id es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deleted = delete_session(session_id)

        if deleted:
            return Response(
                {
                    "message": "Sesión eliminada correctamente.",
                    "session_id": session_id,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "error": "Sesión no encontrada o ya fue eliminada.",
                "session_id": session_id,
            },
            status=status.HTTP_404_NOT_FOUND,
        )


class SSOConfigView(APIView):
    """GET /api/sso/config/ — Public PKCE/MSAL configuration for the frontend."""

    permission_classes = [AllowAny]

    def get(self, request):
        scopes_raw = getattr(django_settings, "ENTRA_SSO_SCOPES", "")
        scopes = scopes_raw.split() if scopes_raw else []

        return Response({
            "tenant_id": getattr(django_settings, "ENTRA_TENANT_ID", ""),
            "authority": getattr(django_settings, "ENTRA_AUTHORITY", ""),
            "client_id": getattr(django_settings, "ENTRA_FRONTEND_CLIENT_ID", "") or None,
            "api_scope": getattr(django_settings, "ENTRA_API_SCOPE", ""),
            "scopes": scopes,
            "expected_audience": getattr(django_settings, "ENTRA_EXPECTED_AUDIENCE", ""),
        })


def _build_entra_token_url() -> str:
    """Resolve Entra OAuth2 token endpoint from ENTRA_AUTHORITY or tenant id."""
    authority = (getattr(django_settings, "ENTRA_AUTHORITY", "") or "").strip()
    tenant_id = (getattr(django_settings, "ENTRA_TENANT_ID", "") or "").strip()

    if authority:
        normalized = authority.rstrip("/")
        # If authority already points to oauth2 path, use it as-is.
        if "/oauth2" in normalized.lower():
            return normalized
        return f"{normalized}/oauth2/v2.0/token"

    if tenant_id:
        return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    return ""


class SSOTokenExchangeView(APIView):
    """POST /api/sso/token/ — Exchanges authorization code + PKCE for tokens."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = SSOTokenExchangeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        token_url = _build_entra_token_url()
        if not token_url:
            return Response(
                {"detail": "SSO token endpoint is not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        client_id = (
            serializer.validated_data.get("client_id")
            or getattr(django_settings, "ENTRA_FRONTEND_CLIENT_ID", "")
        )
        if not client_id:
            return Response(
                {"detail": "ENTRA_FRONTEND_CLIENT_ID is not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        scope = (
            serializer.validated_data.get("scope")
            or getattr(django_settings, "ENTRA_SSO_SCOPES", "")
            or getattr(django_settings, "ENTRA_API_SCOPE", "")
        )

        client_secret = getattr(django_settings, "ENTRA_FRONTEND_CLIENT_SECRET", "")

        payload = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": serializer.validated_data["code"],
            "redirect_uri": serializer.validated_data["redirect_uri"],
            "code_verifier": serializer.validated_data["code_verifier"],
        }
        if client_secret:
            payload["client_secret"] = client_secret
        if scope:
            payload["scope"] = scope

        try:
            upstream = http_requests.post(
                token_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
        except http_requests.RequestException:
            return Response(
                {"detail": "Unable to reach Entra token endpoint."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            body = upstream.json()
        except ValueError:
            body = {"raw": upstream.text}

        if upstream.status_code >= 400:
            return Response(
                {
                    "detail": "Entra token exchange failed.",
                    "entra_error": body,
                },
                status=upstream.status_code,
            )

        return Response(body, status=status.HTTP_200_OK)


class WhoAmIView(APIView):
    """GET /api/sso/whoami/ — Evidence endpoint for Entra SSO."""

    authentication_classes = [EntraBearerAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_context = build_user_context(request.user, request=request)
        return Response(
            {
                "status": "AUTHENTICATED",
                "oid": user_context.get("oid") or request.auth.get("oid"),
                "email": user_context.get("email"),
                "name": user_context.get("name"),
                "scp": user_context.get("scp", []),
                "capabilities": user_context.get("capabilities", ["VIEW_BASIC"]),
                "allowed": user_context.get("allowed", False),
                "role": user_context["role"],
                "scopes": user_context["scopes"],
            }
        )

