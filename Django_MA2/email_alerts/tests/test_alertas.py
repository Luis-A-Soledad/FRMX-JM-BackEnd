"""Tests para los endpoints REST de alertas (/api/alertas)."""

from __future__ import annotations

import math
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from email_alerts.helpers import (
    build_alerta_response,
    normalize_columns,
)

# ---------------------------------------------------------------------------
# Datos mock que simulan lo que devuelve _execute_statement
# ---------------------------------------------------------------------------

MOCK_COLUMNS = [
    "id_alerta",
    "asset_id",
    "titulo",
    "descripcion",
    "detail_location_at_start",
    "detail_location_at_end",
    "detail_mile_post_at_start",
    "detail_mile_post_at_end",
    "tipo_alerta",
    "event_time_utc",
    "train_id",
    "unknown_col",
]

def _make_row(alert_id: int = 1) -> list:
    return [
        str(alert_id),              # id_alerta
        "L-1234",                   # asset_id → locomotora
        "Exceso velocidad",         # titulo → ultimaAlerta
        "Alerta de exceso en PK 100",  # descripcion
        "Norte",                    # detail_location_at_start → region
        "D-01",                     # detail_location_at_end → distrito
        "100",                      # detail_mile_post_at_start → pkInicio
        "200",                      # detail_mile_post_at_end → pkFin
        "speed",                    # tipo_alerta → tipoAlerta
        "2025-06-15 10:00:00",      # event_time_utc
        "TRN-999",                  # train_id (allowed extra)
        "ignorado",                 # unknown_col (not in allowlist)
    ]


MOCK_ROWS_PAGE = [_make_row(i) for i in range(1, 4)]  # 3 rows
MOCK_COUNT = 50


def _mock_execute_statement_list(query, *, parameters=None):
    """Mock para fetch de lista y count."""
    if "COUNT(*)" in query:
        return ["total"], [[str(MOCK_COUNT)]]
    return MOCK_COLUMNS, MOCK_ROWS_PAGE


def _mock_execute_statement_detail_found(query, *, parameters=None):
    """Mock para fetch de detalle existente."""
    return MOCK_COLUMNS, [_make_row(1)]


def _mock_execute_statement_detail_not_found(query, *, parameters=None):
    """Mock para fetch de detalle no existente."""
    return MOCK_COLUMNS, []


def _mock_execute_statement_error(query, *, parameters=None):
    """Mock que simula error de Databricks."""
    raise RuntimeError("Databricks API HTTP error: 500 — Internal Server Error")


def _mock_resolve_connection():
    return ("fake-host", "fake-wh", "fake-token", "fake.table")


# ---------------------------------------------------------------------------
# Tests de la capa helpers (normalización)
# ---------------------------------------------------------------------------

class NormalizeColumnsTests(TestCase):
    """Tests unitarios para normalize_columns y build_alerta_response."""

    def test_normalize_known_columns(self):
        raw = {
            "id_alerta": 42,
            "asset_id": "L-99",
            "titulo": "Freno",
            "detail_location_at_start": "Sur",
            "detail_location_at_end": "D-5",
            "detail_mile_post_at_start": 10,
            "detail_mile_post_at_end": 20,
            "descripcion": "Desc de prueba",
        }
        normalized = normalize_columns(raw)
        self.assertEqual(normalized["id"], 42)
        self.assertEqual(normalized["locomotora"], "L-99")
        self.assertEqual(normalized["ultimaAlerta"], "Freno")
        self.assertEqual(normalized["region"], "Sur")
        self.assertEqual(normalized["distrito"], "D-5")
        self.assertEqual(normalized["pkInicio"], 10)
        self.assertEqual(normalized["pkFin"], 20)
        self.assertEqual(normalized["descripcion"], "Desc de prueba")

    def test_normalize_underscore_variants(self):
        raw = {"alertas_activas": 2, "pk_inicio": 5, "hora_actualizacion": "12:00"}
        normalized = normalize_columns(raw)
        self.assertEqual(normalized["alertasActivas"], 2)
        self.assertEqual(normalized["pkInicio"], 5)
        self.assertEqual(normalized["horaActualizacion"], "12:00")

    def test_unknown_columns_pass_through(self):
        raw = {"custom_field": "value", "asset_id": "L-1"}
        normalized = normalize_columns(raw)
        self.assertEqual(normalized["locomotora"], "L-1")
        self.assertEqual(normalized["custom_field"], "value")

    def test_build_alerta_response_complete(self):
        raw = {
            "id_alerta": 10,
            "asset_id": "L-50",
            "titulo": "Alerta de prueba",
            "descripcion": "Desc original de DB",
            "detail_location_at_start": "Centro",
            "detail_location_at_end": "D-3",
            "detail_mile_post_at_start": 100,
            "detail_mile_post_at_end": 200,
            "event_time_utc": "2025-06-15 10:00:00",
            "train_id": "TRN-100",
            "unknown_field": "should_not_appear",
        }
        normalized = normalize_columns(raw)
        result = build_alerta_response(normalized, timestamp_col="event_time_utc")

        self.assertEqual(result["id"], 10)
        self.assertEqual(result["titulo"], "Alerta de prueba")
        # descripcion viene directo de Databricks
        self.assertEqual(result["descripcion"], "Desc original de DB")
        self.assertEqual(result["fechaCreacion"], "2025-06-15T10:00:00Z")
        self.assertEqual(result["locomotora"], "L-50")
        self.assertEqual(result["region"], "Centro")
        # Solo extras permitidos
        self.assertIn("train_id", result["extras"])
        self.assertNotIn("unknown_field", result["extras"])

    def test_descripcion_composed_when_missing(self):
        """Si no hay columna descripcion, se compone desde campos."""
        raw = {
            "asset_id": "L-50",
            "detail_location_at_start": "Centro",
            "detail_location_at_end": "D-3",
            "detail_mile_post_at_start": 100,
            "detail_mile_post_at_end": 200,
        }
        normalized = normalize_columns(raw)
        result = build_alerta_response(normalized)
        self.assertIn("Locomotora L-50", result["descripcion"])
        self.assertIn("Centro", result["descripcion"])

    def test_estado_inactiva_when_zero_alertas(self):
        raw = {"id_alerta": 1}
        normalized = normalize_columns(raw)
        result = build_alerta_response(normalized)
        self.assertEqual(result["estado"], "INACTIVA")

    def test_estado_activa_when_alertas_present(self):
        raw = {"id_alerta": 1, "alertas_activas": 3}
        normalized = normalize_columns(raw)
        result = build_alerta_response(normalized)
        self.assertEqual(result["estado"], "ACTIVA")

    def test_fecha_creacion_iso_format(self):
        raw = {"event_time_utc": "2025-01-01 00:00:00"}
        normalized = normalize_columns(raw)
        result = build_alerta_response(normalized, timestamp_col="event_time_utc")
        self.assertEqual(result["fechaCreacion"], "2025-01-01T00:00:00Z")

    def test_fecha_creacion_already_iso(self):
        raw = {"event_time_utc": "2025-01-01T00:00:00Z"}
        normalized = normalize_columns(raw)
        result = build_alerta_response(normalized, timestamp_col="event_time_utc")
        self.assertEqual(result["fechaCreacion"], "2025-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Tests de endpoint GET /api/alertas (lista paginada)
# ---------------------------------------------------------------------------

@override_settings(ENTRA_SSO_ENFORCE=False, ENTRA_AUTH_ENABLED=False)
class AlertasListViewTests(TestCase):
    """Integration tests para GET /api/alertas."""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/alertas/"

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_list)
    def test_list_default_pagination(self, mock_exec, mock_conn):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()

        self.assertIn("data", body)
        self.assertIn("pagination", body)
        self.assertIn("links", body)

        pag = body["pagination"]
        self.assertEqual(pag["page"], 1)
        self.assertEqual(pag["size"], 20)
        self.assertEqual(pag["totalItems"], MOCK_COUNT)
        total_pages = math.ceil(MOCK_COUNT / 20)
        self.assertEqual(pag["totalPages"], total_pages)
        self.assertIs(pag["hasNext"], True)
        self.assertIs(pag["hasPrev"], False)

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_list)
    def test_list_custom_page_size(self, mock_exec, mock_conn):
        response = self.client.get(self.url, {"page": 2, "size": 10})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pag = response.json()["pagination"]
        self.assertEqual(pag["page"], 2)
        self.assertEqual(pag["size"], 10)
        self.assertIs(pag["hasPrev"], True)

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_list)
    def test_list_data_contains_required_fields(self, mock_exec, mock_conn):
        response = self.client.get(self.url, {"size": 5})
        body = response.json()
        self.assertTrue(len(body["data"]) > 0)
        alerta = body["data"][0]
        for field in [
            "id", "titulo", "descripcion", "estado", "fechaCreacion",
            "alertasActivas", "locomotora", "maquinista", "region",
            "distrito", "pkInicio", "pkFin", "ultimaAlerta",
            "horaActualizacion", "detail_speed_limit", "extras",
        ]:
            self.assertIn(field, alerta, f"Campo '{field}' falta en la respuesta")

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_list)
    def test_list_links_present(self, mock_exec, mock_conn):
        response = self.client.get(self.url)
        links = response.json()["links"]
        self.assertIn("self", links)
        self.assertIsNotNone(links["self"])
        self.assertIn("next", links)
        self.assertIn("prev", links)

    def test_list_page_zero_returns_400(self):
        response = self.client.get(self.url, {"page": 0})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = response.json()
        self.assertEqual(body["error"]["code"], "PARAMETROS_INVALIDOS")

    def test_list_size_over_max_returns_400(self):
        response = self.client.get(self.url, {"size": 200})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = response.json()
        self.assertEqual(body["error"]["code"], "PARAMETROS_INVALIDOS")

    def test_list_page_negative_returns_400(self):
        response = self.client.get(self.url, {"page": -1})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_size_zero_returns_400(self):
        response = self.client.get(self.url, {"size": 0})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_non_numeric_page_returns_400(self):
        response = self.client.get(self.url, {"page": "abc"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_error)
    def test_list_databricks_error_returns_502(self, mock_exec, mock_conn):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        body = response.json()
        self.assertEqual(body["error"]["code"], "DATABRICKS_ERROR")
        # No se expone el detalle interno
        self.assertNotIn("500", body["error"]["message"])


# ---------------------------------------------------------------------------
# Tests de endpoint GET /api/alertas/{id} (detalle)
# ---------------------------------------------------------------------------

@override_settings(ENTRA_SSO_ENFORCE=False, ENTRA_AUTH_ENABLED=False)
class AlertaDetailViewTests(TestCase):
    """Integration tests para GET /api/alertas/{id}."""

    def setUp(self):
        self.client = APIClient()

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_detail_found)
    def test_detail_found(self, mock_exec, mock_conn):
        response = self.client.get("/api/alertas/1/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["id"], 1)
        self.assertIn("titulo", body)
        self.assertIn("descripcion", body)
        self.assertIn("estado", body)
        self.assertIn("fechaCreacion", body)
        self.assertIn("extras", body)

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_detail_not_found)
    def test_detail_not_found_returns_404(self, mock_exec, mock_conn):
        response = self.client.get("/api/alertas/999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        body = response.json()
        self.assertEqual(body["error"]["code"], "ALERTA_NO_ENCONTRADA")
        self.assertIn("999", body["error"]["message"])

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_error)
    def test_detail_databricks_error_returns_502(self, mock_exec, mock_conn):
        response = self.client.get("/api/alertas/1/")
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        body = response.json()
        self.assertEqual(body["error"]["code"], "DATABRICKS_ERROR")

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_detail_found)
    def test_detail_all_contract_fields(self, mock_exec, mock_conn):
        """Verifica que todos los campos del contrato están presentes."""
        response = self.client.get("/api/alertas/1/")
        body = response.json()
        for field in [
            "id", "titulo", "descripcion", "estado", "fechaCreacion",
            "alertasActivas", "locomotora", "maquinista", "region",
            "distrito", "pkInicio", "pkFin", "ultimaAlerta",
            "horaActualizacion", "extras",
        ]:
            self.assertIn(field, body, f"Campo '{field}' falta en detalle")

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_detail_found)
    def test_detail_estado_inactiva_without_alertas_column(self, mock_exec, mock_conn):
        """Sin columna alertasActivas en la tabla, el estado es INACTIVA."""
        response = self.client.get("/api/alertas/1/")
        self.assertEqual(response.json()["estado"], "INACTIVA")

    @patch("email_alerts.service._resolve_connection", return_value=_mock_resolve_connection())
    @patch("email_alerts.service._execute_statement", side_effect=_mock_execute_statement_detail_found)
    def test_detail_extras_allowed_only(self, mock_exec, mock_conn):
        """Solo columnas permitidas aparecen en extras; las demás se descartan."""
        response = self.client.get("/api/alertas/1/")
        extras = response.json()["extras"]
        # train_id está en la allowlist
        self.assertIn("train_id", extras)
        self.assertEqual(extras["train_id"], "TRN-999")
        # tipoAlerta también está permitido
        self.assertIn("tipoAlerta", extras)
        # unknown_col NO está en la allowlist
        self.assertNotIn("unknown_col", extras)
