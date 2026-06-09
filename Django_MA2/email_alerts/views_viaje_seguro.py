"""Vistas API REST para Viaje Seguro (TVFs en Databricks)."""

from __future__ import annotations

import logging
from datetime import datetime

from django.conf import settings as django_settings
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from api.distritos import DISTRITOS
from api.authentication.stateless_jwt import StatelessJWTAuthentication
from api.authentication.entra import EntraBearerAuthentication
from api.permissions import IsAllowedSSORole

from .service import (
    fetch_vs_desempeno_region,
    fetch_vs_distritos,
    fetch_vs_gestion,
    fetch_vs_hist_cert,
    fetch_vs_indice,
    fetch_vs_reconocimiento,
    fetch_vs_score_mensual,
)

logger = logging.getLogger(__name__)


def _viaje_seguro_authenticators():
    authenticators = []
    if getattr(django_settings, "ENTRA_AUTH_ENABLED", False):
        authenticators.append(EntraBearerAuthentication())
    authenticators.append(StatelessJWTAuthentication())
    return authenticators


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


class DesempenoRegionView(APIView):
    """GET /api/viaje-seguro/desempeno-region/ — desempeño regional actual vs anterior."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _viaje_seguro_authenticators()

    def get(self, request: Request) -> Response:
        email_jefe = request.user.email
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        errors: dict = {}
        if not email_jefe:
            errors["email_jefe"] = "No se encontró email asociado. Revisa tu autenticación."
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
            rows = fetch_vs_desempeno_region(fecha_inicio, fecha_fin, email_jefe)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para desempeño región")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener desempeño regional en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class DistritosView(APIView):
    """GET /api/viaje-seguro/distritos/ — distritos con score y riesgo."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _viaje_seguro_authenticators()

    def get(self, request: Request) -> Response:
        email_jefe = request.user.email
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        errors: dict = {}
        if not email_jefe:
            errors["email_jefe"] = "No se encontró email asociado. Revisa tu autenticación."
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
            rows = fetch_vs_distritos(fecha_inicio, fecha_fin, email_jefe)
            for row in rows:
                distrito_actual = row.get("distrito")
                distrito_info = DISTRITOS.get(distrito_actual, {})
                row["lat"] = distrito_info.get("lat")
                row["lng"] = distrito_info.get("lng")

            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para distritos")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener distritos en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class GestionView(APIView):
    """GET /api/viaje-seguro/gestion/ — gestión de maquinistas con scores y certificados."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _viaje_seguro_authenticators()

    def get(self, request: Request) -> Response:
        email_jefe = request.user.email
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        errors: dict = {}
        if not email_jefe:
            errors["email_jefe"] = "No se encontró email asociado. Revisa tu autenticación."
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
            rows = fetch_vs_gestion(fecha_inicio, fecha_fin, email_jefe)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para gestión")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener datos de gestión en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class HistCertView(APIView):
    """GET /api/viaje-seguro/hist-cert/ — historial de certificados de un maquinista."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _viaje_seguro_authenticators()

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
            rows = fetch_vs_hist_cert(fecha_inicio, fecha_fin, id_maquinista)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para historial certificados")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener historial de certificados en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class IndiceView(APIView):
    """GET /api/viaje-seguro/indice/ — índices de certificación y viajes."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _viaje_seguro_authenticators()

    def get(self, request: Request) -> Response:
        email_jefe = request.user.email
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        errors: dict = {}
        if not email_jefe:
            errors["email_jefe"] = "No se encontró email asociado. Revisa tu autenticación."
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
            rows = fetch_vs_indice(fecha_inicio, fecha_fin, email_jefe)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para índice")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener índices en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class ReconocimientoView(APIView):
    """GET /api/viaje-seguro/reconocimiento/ — ranking de reconocimiento de maquinistas."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _viaje_seguro_authenticators()

    def get(self, request: Request) -> Response:
        email_jefe = request.user.email
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        errors: dict = {}
        if not email_jefe:
            errors["email_jefe"] = "No se encontró email asociado. Revisa tu autenticación."
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
            rows = fetch_vs_reconocimiento(fecha_inicio, fecha_fin, email_jefe)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para reconocimiento")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener reconocimientos en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )


class ScoreMensualView(APIView):
    """GET /api/viaje-seguro/score-mensual/ — score mensual de un maquinista."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _viaje_seguro_authenticators()

    def get(self, request: Request) -> Response:
        id_maquinista = request.query_params.get("id_maquinista")

        errors: dict = {}
        if not id_maquinista:
            errors["id_maquinista"] = "Parámetro requerido."

        if errors:
            return _error_response(
                "PARAMETROS_INVALIDOS",
                "Parámetros inválidos o faltantes.",
                details=errors,
            )

        try:
            rows = fetch_vs_score_mensual(id_maquinista)
            return Response({"data": rows}, status=status.HTTP_200_OK)
        except RuntimeError:
            logger.exception("Error consultando Databricks para score mensual")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener score mensual en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )
