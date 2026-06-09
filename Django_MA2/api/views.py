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
import json
import os
import secrets
import base64
import time
from urllib.parse import urlencode
import jwt

import requests as http_requests
from django.conf import settings as django_settings
from django.core.cache import cache
from django.http import HttpResponseRedirect
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .authentication.entra import EntraBearerAuthentication
from .authentication.stateless_jwt import StatelessJWTAuthentication
from .permissions import IsAllowedSSORole
from .serializers import (
    ChatRequestSerializer,
    ChatResponseSerializer,
    ResumenRequestSerializer,
    SSOTokenExchangeSerializer,
)
from accounts.utils import build_user_context, resolve_access_level, parse_roles
from rest_framework_simplejwt.tokens import AccessToken



# if os.getenv("MOCK_AGENT", "").strip().lower() in ("1", "true", "yes"):
#     from .agent_runner_mock import run_agent, get_or_create_session, delete_session
# else:
#     from .agent_runner import run_agent, get_or_create_session, delete_session

if os.getenv("MOCK_AGENT", "").strip().lower() in ("1", "true", "yes"):
    from .databricks_client import run_agent, get_or_create_session, delete_session
else:
    from .databricks_client import run_agent, get_or_create_session, delete_session

# Cliente del Agente de Resumenes (endpoint independiente en Databricks)
from .databricks_client_resumenes import (
    run_agent as run_resumen_agent,
    get_or_create_session as get_or_create_resumen_session,
)

# Funciones SQL deterministas (TVFs) para las vistas de calificaciones.
from datetime import date as _date, timedelta as _timedelta
from email_alerts.service import (
    fetch_calificaciones_maquinista,
    fetch_calificaciones_todos,
    fetch_vs_distritos,
)

# Vistas cuyos datos se traen server-side con funciones SQL (Opcion A) y se
# pasan al agente como 'data' (el agente las resume sin consultar Genie).
# 'region' usa la TVF vs_distritos (la misma del endpoint /viaje-seguro/distritos/):
# alertas por distrito de la region del jefe, ya ordenadas por frecuencia.
# region EXIGE fecha_inicio/fecha_fin (validado en ResumenRequestSerializer), igual
# que /viaje-seguro/distritos/, asi que NO tiene default de fechas.
_VIEWS_CON_DATA_SQL = {"calificadores", "maquinista", "region"}


# Ventana FIJA (dias hacia atras, incluyendo hoy) por vista. Si una vista esta
# aqui, el rango se IMPONE y se ignoran las fechas que mande el front.
# NOTA: 'calificadores' se quito a proposito. El resumen debe usar el MISMO
# periodo que la tabla de la pantalla (las fechas que selecciona el usuario y
# manda el front), para que el resumen y la grilla SIEMPRE coincidan.
_DIAS_VENTANA_FIJA_POR_VISTA: dict[str, int] = {}

# Ventana por defecto cuando el front NO manda fechas: los N dias previos MAS
# hoy -> [hoy-N, hoy] (N+1 dias en total). Ej.: si hoy es 5-jun y N=7, el rango
# es 29-may a 5-jun (los 7 dias previos y el dia actual).
_DIAS_VENTANA_DEFAULT = 7


# ── Cache del resumen por HUELLA del dato ────────────────────────────────────
# El agente (LLM) es lo caro; el SQL es barato. Por eso se cachea la respuesta
# del agente y solo se vuelve a llamar cuando cambian los inputs O la huella de
# las filas (resumen_data). Asi el resumen se regenera unicamente cuando el dato
# realmente cambio (p.ej. tras correr el job horario), no en cada carga.
# El TTL es solo de respaldo (para que el cache no crezca indefinido); quien
# decide regenerar es la huella, no el reloj. Cache en memoria (LocMemCache),
# sin base de datos. Aplica a TODAS las vistas con data SQL (calificadores,
# maquinista y region): como ya hay filas para hashear, region tambien se cachea
# por huella (solo llama al LLM cuando cambian sus distritos/alertas).
_RESUMEN_CACHE_ENABLED = os.getenv("RESUMEN_CACHE_ENABLED", "1").strip() == "1"
_RESUMEN_CACHE_TTL = int(os.getenv("RESUMEN_CACHE_TTL_SECS", str(12 * 3600)))
# Piso de regeneracion (segundos): aunque el dato cambie, no se regenera mas
# seguido que esto. 0 = sin piso -> regenera en CADA cambio (comportamiento
# actual). Subirlo (ej. 600) acota el costo del LLM si el dato empieza a cambiar
# muy rapido, a cambio de servir un resumen hasta N seg desactualizado.
_RESUMEN_MIN_REGEN_SECS = int(os.getenv("RESUMEN_MIN_REGEN_SECS", "0"))


def _resumen_data_huella(resumen_data) -> str:
    """sha1 del JSON de las filas; cambia solo cuando cambian los datos."""
    return hashlib.sha1(
        json.dumps(resumen_data, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _resumen_cache_key(view: str | None, role: str, email: str | None, filters: dict) -> str:
    """Clave ESTABLE por (vista, rol, usuario, filtros) — SIN la huella del dato.
    Bajo esta clave se guarda un registro {huella, result, generated_at}, para
    poder comparar si el dato cambio y aplicar el piso de regeneracion."""
    base = json.dumps([view, role, email, filters], sort_keys=True, ensure_ascii=False, default=str)
    return "resumen:" + hashlib.sha1(base.encode("utf-8")).hexdigest()


def _resumen_rango_fechas(filters: dict, view: str | None = None) -> tuple[str, str]:
    """Rango de fechas para las funciones SQL.

    - Si la vista tiene ventana FIJA, se impone y se IGNORAN las fechas del front.
    - Si no, se usan las fechas que manda el front (filters.fecha_inicio /
      fecha_fin, YYYY-MM-DD) para que el resumen coincida con la tabla de la
      pantalla.
    - Si el front no manda fechas, se usa una ventana por defecto: los N dias
      previos MAS hoy ([hoy-N, hoy]), semana movil.

    NOTA: la vista 'region' EXIGE fecha_inicio/fecha_fin (validado en
    ResumenRequestSerializer), asi que para region SIEMPRE se usan las fechas del
    front; el default de abajo solo aplica a otras vistas que las omitan."""
    hoy = _date.today()
    dias_fijos = _DIAS_VENTANA_FIJA_POR_VISTA.get(view)
    if dias_fijos is not None:
        fecha_fin = hoy.isoformat()
        fecha_inicio = (hoy - _timedelta(days=dias_fijos - 1)).isoformat()
        return fecha_inicio, fecha_fin
    default_fin = hoy.isoformat()
    default_inicio = (hoy - _timedelta(days=_DIAS_VENTANA_DEFAULT)).isoformat()
    fecha_fin = (str(filters.get("fecha_fin") or "").strip()) or default_fin
    fecha_inicio = (str(filters.get("fecha_inicio") or "").strip()) or default_inicio
    return fecha_inicio, fecha_fin


def _fetch_resumen_data(view: str, role: str, email: str | None, filters: dict):
    """Trae las filas de calificaciones segun rol y vista (Opcion A).

    - JEFE_MAQUINISTAS -> solo sus maquinistas (via su email).
    - CCO              -> todos los maquinistas.
    - otros roles      -> sin acceso (None).

    Para la vista 'maquinista' filtra al maquinista indicado en filters.maquinista
    (match solo por id_maquinista). Retorna lista de dicts, o None si no hay acceso.

    Para la vista 'region' usa la TVF vs_distritos (la misma fuente que el endpoint
    /viaje-seguro/distritos/): resuelve la region del jefe via su email y devuelve,
    por distrito, promedio_score, riesgo y las alertas ya ordenadas por frecuencia.
    """
    fecha_inicio, fecha_fin = _resumen_rango_fechas(filters, view)

    # 'region': alertas por distrito de la region del jefe (via su email).
    if view == "region":
        if not email:
            return None
        return fetch_vs_distritos(fecha_inicio, fecha_fin, email)

    if role == "JEFE_MAQUINISTAS":
        if not email:
            return None
        rows = fetch_calificaciones_maquinista(email, fecha_inicio, fecha_fin)
    elif role == "CCO":
        rows = fetch_calificaciones_todos(fecha_inicio, fecha_fin)
    else:
        return None

    if view == "maquinista":
        target = str(filters.get("maquinista") or "").strip()
        rows = [
            r for r in rows
            if str(r.get("id_maquinista", "")).strip() == target
        ]
    return rows


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
    1. EntraBearerAuthentication (when Entra is enabled).
    2. StatelessJWTAuthentication as a fallback for the backend-issued JWT.
    """
    authenticators = []
    if getattr(django_settings, "ENTRA_AUTH_ENABLED", False):
        authenticators.append(EntraBearerAuthentication())
    authenticators.append(StatelessJWTAuthentication())
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
        "region": "Colima",
        "user_id": "ID del usuario como muestra EntraID",
        "email" :" abc@def.com",
        "name": "Nombre del usuario"
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
        "region": "Colima",
        "user_id": "ID del usuario como muestra EntraID",
        "email" :" abc@def.com",
        "name": "Nombre del usuario"
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
                role=user_context["role"],
                user_id = user_context["user_id"],
                email = user_context["email"],
                name = user_context["name"],
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
        result["user_id"] = user_context["user_id"]
        result["email"] = user_context["email"]
        result["name"] = user_context["name"]

        response_serializer = ChatResponseSerializer(data=result)
        if response_serializer.is_valid():
            return Response(
                response_serializer.validated_data,
                status=status.HTTP_200_OK
            )

        # ✅ Fallback seguro
        return Response(result, status=status.HTTP_200_OK)


class ResumenView(APIView):
    """
    POST /api/resumen/
    Genera un resumen automático de una vista en el AGENTE DE RESUMENES
    (endpoint independiente en Databricks).

    Body JSON (modo principal — por vista):
    {
        "view": "calificadores",
        "filters": { "maquinista": "NOMBRE" },   // opcional según la vista
        "session_id": "opcional-uuid-de-sesion-previa"
    }
    También acepta 'question' libre como alternativa. Debe venir 'view' o 'question'.

    Response JSON:
    {
        "answer": "...",
        "decision": "resumen",
        "view": "calificadores",
        "session_id": "uuid-de-sesion",
        "last_error": "",
        "role": "CCO"
    }
    """

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _entra_first_authenticators()

    def post(self, request):
        serializer = ResumenRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        view = serializer.validated_data.get("view")
        filters = serializer.validated_data.get("filters") or {}
        question = serializer.validated_data.get("question")
        incoming_session_id = serializer.validated_data.get("session_id")

        # Sesión del agente de resumenes (independiente de la del multiagente)
        session_id = get_or_create_resumen_session(incoming_session_id)

        # Contexto del usuario derivado server-side (ignora 'rol' del cliente)
        user_context = build_user_context(request.user, request=request)
        role = user_context["role"]
        email = user_context.get("email")

        # Opcion A: para las vistas de calificaciones, Django trae las filas con
        # funciones SQL deterministas y se las pasa al agente como 'data' (el
        # agente las resume sin Genie). Mas seguro y consistente con la grilla.
        resumen_data = None
        if view in _VIEWS_CON_DATA_SQL:
            try:
                resumen_data = _fetch_resumen_data(view, role, email, filters)
            except RuntimeError as e:
                return Response(
                    {
                        "error": f"No fue posible obtener los datos de calificaciones: {e}",
                        "session_id": session_id,
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            if resumen_data is None:
                return Response(
                    {
                        "error": "No tienes acceso a esta vista o no se pudo determinar tu identidad.",
                        "session_id": session_id,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # ── Cache por HUELLA del dato + piso de regeneracion ─────────────────
        #    Clave ESTABLE por (view, role, email, filters); el registro guarda
        #    {huella, result, generated_at}. Se reusa SIN llamar al agente si:
        #      - el dato no cambio (misma huella), o
        #      - el dato cambio pero la ultima regeneracion es mas reciente que el
        #        piso (_RESUMEN_MIN_REGEN_SECS) -> sirve algo ligeramente viejo
        #        para acotar el costo del LLM si el dato cambia muy seguido.
        #    Aplica a todas las vistas con data SQL (incluida 'region').
        cache_key = None
        huella = None
        if _RESUMEN_CACHE_ENABLED and resumen_data is not None:
            cache_key = _resumen_cache_key(view, role, email, filters)
            huella = _resumen_data_huella(resumen_data)

        result = None
        if cache_key is not None:
            record = cache.get(cache_key)
            if record is not None:
                if record.get("huella") == huella:
                    # Dato sin cambios -> se reusa el resumen cacheado.
                    result = record["result"]
                else:
                    # Dato cambio: solo se sirve el anterior si aun no se cumple
                    # el piso de regeneracion (acota el costo del LLM).
                    edad = time.time() - record.get("generated_at", 0)
                    if edad < _RESUMEN_MIN_REGEN_SECS:
                        result = record["result"]

        if result is None:
            # Primera vez, o el dato cambio y ya paso el piso -> corre el agente.
            try:
                result = run_resumen_agent(
                    question=question,
                    role=role,
                    session_id=session_id,
                    view=view,
                    filters=filters,
                    user_email=email,
                    data=resumen_data,
                )
            except Exception as e:
                return Response(
                    {
                        "error": f"Error ejecutando el agente de resumenes: {str(e)}",
                        "session_id": session_id,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            if cache_key is not None:
                cache.set(
                    cache_key,
                    {"huella": huella, "result": result, "generated_at": time.time()},
                    _RESUMEN_CACHE_TTL,
                )

        # Copia para re-sellar datos por-request (session_id/role/scopes) sin
        # mutar el objeto guardado en cache.
        result = dict(result)
        result["session_id"] = session_id
        result["role"] = user_context["role"]
        result["scopes"] = user_context["scopes"]

        # Vistas que NO necesitan la tabla cruda en el front (el dato relevante
        # ya viene en el resumen). Agregar mas vistas al set si aplica.
        _VIEWS_SIN_TABLA = {"calificadores"}
        if view in _VIEWS_SIN_TABLA:
            result.pop("last_db_table", None)

        response_serializer = ChatResponseSerializer(data=result)
        if response_serializer.is_valid():
            return Response(
                response_serializer.validated_data,
                status=status.HTTP_200_OK
            )

        # Fallback seguro
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
                "user_id": user_context.get("user_id"),
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
        ms_token = tokens.get("access_token")

        if not id_token:
            return Response(
                {"detail": "No id_token returned from Entra"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # en producción valida la firma correctamente (JWKS)
        decoded = jwt.decode(ms_token, options={"verify_signature": False})

        email = decoded.get("email")
        name = decoded.get("name")

        # -----------------------------
        # 5. Generar el JWT
        # -----------------------------        
        decoded_roles = decoded.get("roles", [])
        decoded_roles = parse_roles(decoded_roles)
        access_level, capabilities, effective_role = resolve_access_level(decoded_roles)
        access_token = AccessToken()
        access_token["email"] = email
        access_token["name"] = name
        access_token["role"] = effective_role
        access_token["capabilities"] = capabilities
        access_token["scopes"] = access_level
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
                    "role": decoded.get("role"),
                }
            }
        )
