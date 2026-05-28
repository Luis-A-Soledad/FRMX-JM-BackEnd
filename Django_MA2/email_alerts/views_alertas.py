"""Vistas API REST para recurso alertas (read-only sobre Databricks)."""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings as django_settings
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.authentication.entra import EntraBearerAuthentication
from api.permissions import IsAllowedSSORole

from .helpers import build_alerta_response, normalize_columns
from .service import (
    fetch_alerta_by_id,
    fetch_alertas_count,
    fetch_alertas_page,
    fetch_email_alerts_operational_rows,
)

logger = logging.getLogger(__name__)

DEFAULT_PAGE = 1
DEFAULT_SIZE = 20
MAX_SIZE = 100
DEFAULT_TIPOS_ALERTA_FILTRADAS = ("Alerta_01", "Alerta_02", "Alerta_03", "Alerta_06")


def _alertas_authenticators():
    """Replica la logica de autenticadores para consistencia con el resto de la API."""
    if getattr(django_settings, "ENTRA_AUTH_ENABLED", False):
        return [EntraBearerAuthentication(), JWTAuthentication()]
    return [JWTAuthentication()]


def _get_timestamp_col() -> str:
    return os.getenv("ALERTAS_TIMESTAMP_COL", "receivedDateTime")


def _error_response(code: str, message: str, details: dict | None = None, http_status: int = 400):
    body: dict = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return Response(body, status=http_status)


def _parse_tipos_alerta_query(raw_tipo_alerta: list[str], raw_tipos_alerta: list[str]) -> list[str]:
    """Parsea tipo_alerta/tipos_alerta desde query params con soporte CSV."""
    values = [*raw_tipo_alerta, *raw_tipos_alerta]
    parsed: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for token in str(raw).split(","):
            value = token.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            parsed.append(value)
    return parsed


class AlertasListView(APIView):
    """GET /api/alertas — lista paginada de alertas."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _alertas_authenticators()

    def _get_tipos_alerta(self, request: Request) -> list[str]:
        return _parse_tipos_alerta_query(
            request.query_params.getlist("tipo_alerta"),
            request.query_params.getlist("tipos_alerta"),
        )

    def get(self, request: Request) -> Response:
        # --- Validar page ---
        page_raw = request.query_params.get("page", str(DEFAULT_PAGE))
        size_raw = request.query_params.get("size", str(DEFAULT_SIZE))

        errors: dict = {}
        try:
            page = int(page_raw)
        except (TypeError, ValueError):
            errors["page"] = f"Debe ser un entero, se recibió '{page_raw}'."
            page = None

        try:
            size = int(size_raw)
        except (TypeError, ValueError):
            errors["size"] = f"Debe ser un entero, se recibió '{size_raw}'."
            size = None

        if page is not None and page < 1:
            errors["page"] = "Debe ser >= 1."
        if size is not None and (size < 1 or size > MAX_SIZE):
            errors["size"] = f"Debe estar entre 1 y {MAX_SIZE}."

        if errors:
            return _error_response(
                "PARAMETROS_INVALIDOS",
                "Parámetros de paginación inválidos.",
                details=errors,
            )

        ts_col = _get_timestamp_col()
        train_id = request.query_params.get("train_id")
        fecha = request.query_params.get("fecha")  # YYYY-MM-DD
        tipos_alerta = self._get_tipos_alerta(request)
        only_last_12_hours_raw = request.query_params.get("only_last_12_hours", "true").lower()
        only_last_12_hours = only_last_12_hours_raw in ("true", "1", "yes")
        if fecha:
            only_last_12_hours = False

        try:
            page_kwargs = {
                "timestamp_col": ts_col,
                "train_id": train_id,
                "fecha": fecha,
                "last_hours": 12 if only_last_12_hours else None,
            }
            count_kwargs = {
                "train_id": train_id,
                "fecha": fecha,
                "last_hours": 12 if only_last_12_hours else None,
            }
            if tipos_alerta:
                page_kwargs["tipos_alerta"] = tipos_alerta
                count_kwargs["tipos_alerta"] = tipos_alerta

            rows = fetch_alertas_page(page, size, **page_kwargs)
            total_items = fetch_alertas_count(**count_kwargs)
        except RuntimeError:
            logger.exception("Error consultando Databricks para alertas list")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener alertas en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            logger.exception("Error inesperado en alertas list")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener alertas en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )

        total_pages = math.ceil(total_items / size) if total_items > 0 else 1
        has_next = page < total_pages
        has_prev = page > 1

        data = [
            build_alerta_response(normalize_columns(row), timestamp_col=ts_col)
            for row in rows
        ]

        # Build links
        base_url = request.build_absolute_uri(request.path)
        self_link = f"{base_url}?page={page}&size={size}"
        next_link = f"{base_url}?page={page + 1}&size={size}" if has_next else None
        prev_link = f"{base_url}?page={page - 1}&size={size}" if has_prev else None

        return Response(
            {
                "data": data,
                "pagination": {
                    "page": page,
                    "size": size,
                    "totalItems": total_items,
                    "totalPages": total_pages,
                    "hasNext": has_next,
                    "hasPrev": has_prev,
                },
                "links": {
                    "self": self_link,
                    "next": next_link,
                    "prev": prev_link,
                },
            },
            status=status.HTTP_200_OK,
        )


class AlertaDetailView(APIView):
    """GET /api/alertas/{id} — detalle de una alerta."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _alertas_authenticators()

    def get(self, request: Request, id: int) -> Response:
        ts_col = _get_timestamp_col()

        try:
            row = fetch_alerta_by_id(id)
        except RuntimeError:
            logger.exception("Error consultando Databricks para alerta detail id=%s", id)
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener alertas en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            logger.exception("Error inesperado en alerta detail id=%s", id)
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener alertas en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )

        if row is None:
            return _error_response(
                "ALERTA_NO_ENCONTRADA",
                f"No existe una alerta con id {id}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        alerta = build_alerta_response(normalize_columns(row), timestamp_col=ts_col)
        return Response(alerta, status=status.HTTP_200_OK)


class AlertasFiltradasListView(AlertasListView):
    """GET /api/alertas/alertas-filtradas — misma lista paginada, filtrada por alertas 01/02/03/06."""

    def _get_tipos_alerta(self, request: Request) -> list[str]:
        parsed = super()._get_tipos_alerta(request)
        return parsed or list(DEFAULT_TIPOS_ALERTA_FILTRADAS)


class AlertasPorLocoPrincipalView(APIView):
    """GET /api/alertas/alertas-por-loco-principal — alertas del ultimo asset procesado."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _alertas_authenticators()

    def _get_tipos_alerta(self, request: Request) -> list[str]:
        return _parse_tipos_alerta_query(
            request.query_params.getlist("tipo_alerta"),
            request.query_params.getlist("tipos_alerta"),
        )

    def get(self, request: Request) -> Response:
        limit_raw = request.query_params.get("limit")
        limit = None
        if limit_raw is not None:
            try:
                limit = int(limit_raw)
            except (TypeError, ValueError):
                return _error_response(
                    "PARAMETROS_INVALIDOS",
                    f"limit debe ser un entero, se recibió '{limit_raw}'.",
                )
            if limit < 1:
                return _error_response(
                    "PARAMETROS_INVALIDOS",
                    "limit debe ser >= 1.",
                )

        only_today_raw = request.query_params.get("only_today", "false").lower()
        only_today = only_today_raw in ("true", "1", "yes")
        only_last_12_hours_raw = request.query_params.get("only_last_12_hours", "true").lower()
        only_last_12_hours = only_last_12_hours_raw in ("true", "1", "yes")
        tipos_alerta = self._get_tipos_alerta(request)

        try:
            rows = fetch_email_alerts_operational_rows(
                limit=limit,
                only_today=only_today,
                last_hours=12 if only_last_12_hours else None,
                tipos_alerta=tipos_alerta or None,
            )
        except RuntimeError:
            logger.exception("Error consultando Databricks para alertas-por-loco-principal")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener alertas en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            logger.exception("Error inesperado en alertas-por-loco-principal")
            return _error_response(
                "DATABRICKS_ERROR",
                "No fue posible obtener alertas en este momento.",
                http_status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"data": rows, "count": len(rows)}, status=status.HTTP_200_OK)


class AlertasPorLocoPrincipalFiltradasView(AlertasPorLocoPrincipalView):
    """GET /api/alertas/alertas-por-loco-principal-filtradas — mismo contrato filtrado por tipo_alerta."""

    def _get_tipos_alerta(self, request: Request) -> list[str]:
        parsed = super()._get_tipos_alerta(request)
        return parsed or list(DEFAULT_TIPOS_ALERTA_FILTRADAS)


class DebugBroadcastView(APIView):
    """POST /api/alertas/debug-broadcast/ — emite alertas fake por WebSocket.

    Solo disponible con DEBUG=True. Permite probar el WebSocket sin Redis
    porque corre dentro del mismo proceso daphne.

    Uso:
        curl -X POST http://localhost:8000/api/alertas/debug-broadcast/
        curl -X POST http://localhost:8000/api/alertas/debug-broadcast/?train_id=TRN-001&count=5
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request: Request) -> Response:
        if not django_settings.DEBUG:
            return Response({"error": "Solo disponible en DEBUG"}, status=403)

        train_id = request.query_params.get("train_id", "TRN-TEST-001")
        count = int(request.query_params.get("count", "3"))

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return Response({"error": "Channel layer no disponible"}, status=500)

        alertas = []
        for i in range(count):
            alertas.append({
                "train_id": train_id,
                "asset_id": f"LOCO-{1000+i}",
                "last_event": datetime.now(timezone.utc).isoformat(),
                "id_alerta": f"FAKE-{i+1}",
                "titulo": "Exceso de velocidad (TEST)",
                "descripcion": f"Alerta de prueba #{i+1}",
                "region": "Norte",
                "distrito": "D-01",
                "maquinista": f"Maquinista TEST {i+1}",
                "detail_mile_post_at_start": "100.5",
                "detail_mile_post_at_end": "102.3",
                "alert_count": count,
            })

        payload = {"event": "snapshot_alertas", "data": alertas, "count": len(alertas)}

        async_to_sync(channel_layer.group_send)(
            "alertas_all",
            {"type": "alerta.nueva", "data": payload},
        )
        async_to_sync(channel_layer.group_send)(
            f"train_{train_id}",
            {"type": "alerta.nueva", "data": {**payload, "train_id": train_id}},
        )

        return Response({
            "status": "broadcast_sent",
            "train_id": train_id,
            "count": count,
            "alertas": alertas,
        })
