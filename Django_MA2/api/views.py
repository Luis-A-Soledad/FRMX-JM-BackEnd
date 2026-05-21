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

import hashlib
import os
import secrets
import base64
from urllib.parse import urlencode
import jwt

import requests as http_requests
from django.conf import settings as django_settings
from django.http import HttpResponseRedirect
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
from rest_framework_simplejwt.tokens import AccessToken



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


# ─── Server-side OAuth flow (Option B) ────────────────────────────────────────

def _generate_pkce():
    """Generate PKCE code_verifier and code_challenge."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _build_entra_authorize_url() -> str:
    """Build Entra OAuth2 authorize endpoint URL."""
    authority = (getattr(django_settings, "ENTRA_AUTHORITY", "") or "").strip()
    tenant_id = (getattr(django_settings, "ENTRA_TENANT_ID", "") or "").strip()

    if authority:
        normalized = authority.rstrip("/")
        if "/oauth2" in normalized.lower():
            return normalized.replace("/token", "/authorize")
        return f"{normalized}/oauth2/v2.0/authorize"

    if tenant_id:
        return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"

    return ""


class SSOLoginView(APIView):
    """GET /api/sso/login/ — Inicia el flujo OAuth. Redirige al usuario a Microsoft."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        authorize_url = _build_entra_authorize_url()
        if not authorize_url:
            return Response(
                {"detail": "SSO authorize endpoint is not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        client_id = getattr(django_settings, "ENTRA_FRONTEND_CLIENT_ID", "")
        if not client_id:
            return Response(
                {"detail": "ENTRA_FRONTEND_CLIENT_ID is not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        callback_uri = getattr(django_settings, "ENTRA_BACKEND_CALLBACK_URI", "")
        if not callback_uri:
            return Response(
                {"detail": "ENTRA_BACKEND_CALLBACK_URI is not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        scope = (
            getattr(django_settings, "ENTRA_SSO_SCOPES", "")
            or getattr(django_settings, "ENTRA_API_SCOPE", "")
            or "openid profile email"
        )

        # Generate PKCE + state
        code_verifier, code_challenge = _generate_pkce()
        state = secrets.token_urlsafe(32)

        # Store in Django session for retrieval in callback
        request.session["sso_code_verifier"] = code_verifier
        request.session["sso_state"] = state

        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": callback_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "response_mode": "query",
        }

        redirect_url = f"{authorize_url}?{urlencode(params)}"
        return HttpResponseRedirect(redirect_url)


class SSOCallbackView(APIView):
    """GET /api/sso/callback/ — Recibe el code de Microsoft y devuelve tokens al frontend."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        # -----------------------------
        # 1. Validar state (CSRF)
        # -----------------------------
        state = request.GET.get("state", "")
        stored_state = request.session.get("sso_state", "")

        if not state or not stored_state or state != stored_state:
            return Response(
                {"detail": "Invalid or missing state parameter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code = request.GET.get("code")
        if not code:
            error = request.GET.get("error", "unknown_error")
            error_desc = request.GET.get("error_description", "")
            return Response(
                {"detail": f"Azure returned error: {error}", "description": error_desc},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -----------------------------
        # 2. Obtener PKCE
        # -----------------------------
        code_verifier = request.session.get("sso_code_verifier", "")
        if not code_verifier:
            return Response(
                {"detail": "Session expired. code_verifier not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # limpiar sesión
        request.session.pop("sso_code_verifier", None)
        request.session.pop("sso_state", None)

        # -----------------------------
        # 3. Intercambiar code por tokens
        # -----------------------------
        token_url = _build_entra_token_url()

        payload = {
            "grant_type": "authorization_code",
            "client_id": django_settings.ENTRA_FRONTEND_CLIENT_ID,
            "client_secret": getattr(django_settings, "ENTRA_FRONTEND_CLIENT_SECRET", ""),
            "code": code,
            "redirect_uri": django_settings.ENTRA_BACKEND_CALLBACK_URI,
            "code_verifier": code_verifier,
            "scope": "openid profile email",
        }

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

        if upstream.status_code >= 400:
            try:
                body = upstream.json()
            except ValueError:
                body = {"raw": upstream.text}
            return Response(
                {"detail": "Entra token exchange failed.", "entra_error": body},
                status=upstream.status_code,
            )

        tokens = upstream.json()

        # -----------------------------
        # 4. Decodificar ID token de Microsoft
        # -----------------------------
        id_token = tokens.get("id_token")

        if not id_token:
            return Response(
                {"detail": "No id_token returned from Entra"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # en producción valida la firma correctamente (JWKS)
        decoded = jwt.decode(id_token, options={"verify_signature": False})

        email = decoded.get("preferred_username") or decoded.get("email")
        name = decoded.get("name")

        # -----------------------------
        # 5. Generar el JWT
        # -----------------------------        
        access_token = AccessToken()
        access_token["email"] = email
        access_token["name"] = name
        access_token["roles"] = decoded.get("roles", [])
        token_str = str(access_token)

        # -----------------------------
        # 6. Redirigir al frontend con token
        # -----------------------------
        frontend_callback = getattr(
            django_settings, "ENTRA_FRONTEND_CALLBACK_URL", ""
        )

        # ✅ usar fragment (#) en lugar de query (?):
        redirect_url = (
            f"{frontend_callback.rstrip('/')}"
            f"#token={token_str}"
            f"&email={email}"
            f"&name={name}"
        )

        return HttpResponseRedirect(redirect_url)


def decode_custom_token(token):
    try:
        decoded = jwt.decode(
            token,
            django_settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        return decoded
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

class CheckSessionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            return Response(
                {"authenticated": False},
                status=401
            )

        token = auth_header.split(" ")[1]

        decoded = decode_custom_token(token)

        if not decoded:
            return Response(
                {"authenticated": False},
                status=401
            )

        return Response(
            {
                "authenticated": True,
                "user": {
                    "email": decoded.get("email"),
                    "name": decoded.get("name"),
                    "roles": decoded.get("roles", []),
                }
            }
        )
