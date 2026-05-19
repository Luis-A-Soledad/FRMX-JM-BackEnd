"""Vistas API REST para calificaciones de maquinistas (TVFs en Databricks)."""

from __future__ import annotations

import logging
from datetime import datetime

from django.conf import settings as django_settings
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.authentication.entra import EntraBearerAuthentication
from api.permissions import IsAllowedSSORole

from .service import (
    fetch_calificaciones_maquinista,
    fetch_comparativa_maquinistas,
    fetch_frecuencia_alertas_maquinista,
    fetch_resumen_semanal_maquinista,
    fetch_viajes_maquinista,
    fetch_to_maquinista,
)

logger = logging.getLogger(__name__)


def _calificaciones_authenticators():
    if getattr(django_settings, "ENTRA_AUTH_ENABLED", False):
        return [EntraBearerAuthentication(), JWTAuthentication()]
    return [JWTAuthentication()]


def _error_response(code: str, message: str, details: dict | None = None, http_status: int = 400):
    body: dict = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return Response(body, status=http_status)


def _validate_date(value: str, field_name: str) -> str | None:
    """Valida formato YYYY-MM-DD. Retorna mensaje de error o None si ok."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return None
    except (ValueError, TypeError):
        return f"'{field_name}' debe tener formato YYYY-MM-DD, se recibió '{value}'."


class CalificacionesMaquinistaView(APIView):
    """GET /api/calificaciones/ — calificaciones de todos los maquinistas en un periodo."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _calificaciones_authenticators()

    def get(self, request: Request) -> Response:
        jefe_maquinista = request.query_params.get("jefe_maquinista")
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        errors: dict = {}
        if not jefe_maquinista:
            errors["jefe_maquinista"] = "Parámetro requerido."

        if not fecha_inicio:
            errors["fecha_inicio"] = "Parámetro requerido."
        elif err := _validate_date(fecha_inicio, "fecha_inicio"):
            errors["fecha_inicio"] = err

        if not fecha_fin:
            errors["fecha_fin"] = "Parámetro requerido."
        elif err := _validate_date(fecha_fin, "fecha_fin"):
            errors["fecha_fin"] = err

        if errors:
            return _error_response(
                "PARAMETROS_INVALIDOS",
                "Parámetros inválidos o faltantes.",
                details=errors,
            )

        try:
            rows = fetch_calificaciones_maquinista(jefe_maquinista, fecha_inicio, fecha_fin)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para calificaciones")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener calificaciones en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class FrecuenciaAlertasMaquinistaView(APIView):
    """GET /api/calificaciones/frecuencia-alertas/ — frecuencia de alertas por maquinista."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _calificaciones_authenticators()

    def get(self, request: Request) -> Response:
        id_maquinista = request.query_params.get("id_maquinista")
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        errors: dict = {}
        if not id_maquinista:
            errors["id_maquinista"] = "Parámetro requerido."

        if not fecha_inicio:
            errors["fecha_inicio"] = "Parámetro requerido."
        elif err := _validate_date(fecha_inicio, "fecha_inicio"):
            errors["fecha_inicio"] = err

        if not fecha_fin:
            errors["fecha_fin"] = "Parámetro requerido."
        elif err := _validate_date(fecha_fin, "fecha_fin"):
            errors["fecha_fin"] = err

        if errors:
            return _error_response(
                "PARAMETROS_INVALIDOS",
                "Parámetros inválidos o faltantes.",
                details=errors,
            )

        try:
            rows = fetch_frecuencia_alertas_maquinista(id_maquinista, fecha_inicio, fecha_fin)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para frecuencia alertas")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener frecuencia de alertas en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class ResumenSemanalMaquinistaView(APIView):
    """GET /api/calificaciones/resumen-semanal/ — resumen semanal por maquinista."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _calificaciones_authenticators()

    def get(self, request: Request) -> Response:
        id_maquinista = request.query_params.get("id_maquinista")
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        errors: dict = {}
        if not id_maquinista:
            errors["id_maquinista"] = "Parámetro requerido."

        if not fecha_inicio:
            errors["fecha_inicio"] = "Parámetro requerido."
        elif err := _validate_date(fecha_inicio, "fecha_inicio"):
            errors["fecha_inicio"] = err

        if not fecha_fin:
            errors["fecha_fin"] = "Parámetro requerido."
        elif err := _validate_date(fecha_fin, "fecha_fin"):
            errors["fecha_fin"] = err

        if errors:
            return _error_response(
                "PARAMETROS_INVALIDOS",
                "Parámetros inválidos o faltantes.",
                details=errors,
            )

        try:
            rows = fetch_resumen_semanal_maquinista(id_maquinista, fecha_inicio, fecha_fin)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para resumen semanal")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener resumen semanal en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class ViajesMaquinistaView(APIView):
    """GET /api/calificaciones/viajes/ — viajes de un maquinista en un periodo."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _calificaciones_authenticators()

    def get(self, request: Request) -> Response:
        id_maquinista = request.query_params.get("id_maquinista")
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        errors: dict = {}
        if not id_maquinista:
            errors["id_maquinista"] = "Parámetro requerido."

        if not fecha_inicio:
            errors["fecha_inicio"] = "Parámetro requerido."
        elif err := _validate_date(fecha_inicio, "fecha_inicio"):
            errors["fecha_inicio"] = err

        if not fecha_fin:
            errors["fecha_fin"] = "Parámetro requerido."
        elif err := _validate_date(fecha_fin, "fecha_fin"):
            errors["fecha_fin"] = err

        if errors:
            return _error_response(
                "PARAMETROS_INVALIDOS",
                "Parámetros inválidos o faltantes.",
                details=errors,
            )

        try:
            rows = fetch_viajes_maquinista(id_maquinista, fecha_inicio, fecha_fin)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para viajes maquinista")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener viajes en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class ToMaquinistaView(APIView):
    """GET /api/calificaciones/to/ — uso de TO de un maquinista en un periodo."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _calificaciones_authenticators()

    def get(self, request: Request) -> Response:
        id_maquinista = request.query_params.get("id_maquinista")
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        errors: dict = {}
        if not id_maquinista:
            errors["id_maquinista"] = "Parámetro requerido."

        if not fecha_inicio:
            errors["fecha_inicio"] = "Parámetro requerido."
        elif err := _validate_date(fecha_inicio, "fecha_inicio"):
            errors["fecha_inicio"] = err

        if not fecha_fin:
            errors["fecha_fin"] = "Parámetro requerido."
        elif err := _validate_date(fecha_fin, "fecha_fin"):
            errors["fecha_fin"] = err

        if errors:
            return _error_response(
                "PARAMETROS_INVALIDOS",
                "Parámetros inválidos o faltantes.",
                details=errors,
            )

        try:
            rows = fetch_to_maquinista(id_maquinista, fecha_inicio, fecha_fin)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para TO maquinista")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener datos de TO en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class ComparativaMaquinistasView(APIView):
    """GET /api/calificaciones/comparativa/ — comparativa entre maquinistas en un periodo."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _calificaciones_authenticators()

    def get(self, request: Request) -> Response:
        id_mejor_maquinista = request.query_params.get("id_mejor_maquinista")
        id_maquinista = request.query_params.get("id_maquinista")
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")
        id_maquinista_opcional = request.query_params.get("id_maquinista_opcional")

        errors: dict = {}
        if not id_mejor_maquinista:
            errors["id_mejor_maquinista"] = "Parámetro requerido."

        if not id_maquinista:
            errors["id_maquinista"] = "Parámetro requerido."

        if not fecha_inicio:
            errors["fecha_inicio"] = "Parámetro requerido."
        elif err := _validate_date(fecha_inicio, "fecha_inicio"):
            errors["fecha_inicio"] = err

        if not fecha_fin:
            errors["fecha_fin"] = "Parámetro requerido."
        elif err := _validate_date(fecha_fin, "fecha_fin"):
            errors["fecha_fin"] = err

        if errors:
            return _error_response(
                "PARAMETROS_INVALIDOS",
                "Parámetros inválidos o faltantes.",
                details=errors,
            )

        try:
            rows = fetch_comparativa_maquinistas(
                id_mejor_maquinista, id_maquinista, fecha_inicio, fecha_fin,
                id_maquinista_opcional=id_maquinista_opcional,
            )
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para comparativa maquinistas")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener la comparativa en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )
