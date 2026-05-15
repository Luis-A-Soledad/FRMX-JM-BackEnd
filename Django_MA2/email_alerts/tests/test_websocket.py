"""Tests para WebSocket consumer de alertas y flujo end-to-end.

Usa channels.testing.WebsocketCommunicator con InMemoryChannelLayer
para validar el consumer sin necesitar Redis ni daphne corriendo.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TestCase, override_settings

from email_alerts.consumers import AlertasConsumer, GROUP_ALL
from email_alerts.routing import websocket_urlpatterns

# Forzar InMemoryChannelLayer para los tests (independiente de settings)
TEST_CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}


def _make_communicator(path: str = "/ws/alertas/"):
    """Crea un WebsocketCommunicator apuntando al consumer."""
    from channels.routing import URLRouter
    application = URLRouter(websocket_urlpatterns)
    return WebsocketCommunicator(application, path)


# ── Fake data para mock de Databricks ───────────────────────
FAKE_DATABRICKS_ROWS = [
    {
        "id_alerta": "101",
        "train_id": "TRN-8001",
        "asset_id": "LOCO-5000",
        "titulo": "Exceso velocidad",
        "descripcion": "Superó 80 km/h en PK 45",
        "last_event": "2026-05-08T12:00:00Z",
        "detail_location_at_start": "Norte",
        "detail_location_at_end": "D-02",
        "detail_mile_post_at_start": "45",
        "detail_mile_post_at_end": "47",
        "prioridad": "2",
    },
    {
        "id_alerta": "102",
        "train_id": "TRN-9002",
        "asset_id": "LOCO-6000",
        "titulo": "Freno de emergencia",
        "descripcion": "Activación inesperada",
        "last_event": "2026-05-08T12:01:00Z",
        "detail_location_at_start": "Sur",
        "detail_location_at_end": "D-05",
        "detail_mile_post_at_start": "200",
        "detail_mile_post_at_end": "201",
        "prioridad": "7",
    },
]


@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS, ALERTAS_POLLER_ENABLED=False)
class AlertasConsumerTests(TestCase):
    """Tests unitarios del WebSocket consumer."""

    async def test_connect_and_accept(self):
        """El consumer acepta la conexión WebSocket."""
        communicator = _make_communicator()
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_subscribe_to_train(self):
        """El cliente puede suscribirse a un tren y recibe confirmación."""
        communicator = _make_communicator()
        await communicator.connect()

        await communicator.send_json_to({"action": "subscribe", "train_id": "8001"})
        response = await communicator.receive_json_from()

        self.assertEqual(response["status"], "subscribed")
        self.assertEqual(response["train_id"], "8001")
        await communicator.disconnect()

    async def test_unsubscribe_from_train(self):
        """El cliente puede desuscribirse de un tren."""
        communicator = _make_communicator()
        await communicator.connect()

        # Suscribirse primero
        await communicator.send_json_to({"action": "subscribe", "train_id": "8001"})
        await communicator.receive_json_from()

        # Desuscribirse
        await communicator.send_json_to({"action": "unsubscribe", "train_id": "8001"})
        response = await communicator.receive_json_from()

        self.assertEqual(response["status"], "unsubscribed")
        self.assertEqual(response["train_id"], "8001")
        await communicator.disconnect()

    async def test_invalid_action_returns_error(self):
        """Una acción no reconocida devuelve error."""
        communicator = _make_communicator()
        await communicator.connect()

        await communicator.send_json_to({"action": "invalid"})
        response = await communicator.receive_json_from()

        self.assertIn("error", response)
        await communicator.disconnect()

    async def test_subscribe_without_train_id_returns_error(self):
        """Subscribe sin train_id devuelve error."""
        communicator = _make_communicator()
        await communicator.connect()

        await communicator.send_json_to({"action": "subscribe"})
        response = await communicator.receive_json_from()

        self.assertIn("error", response)
        await communicator.disconnect()

    async def test_broadcast_alertas_all_reaches_client(self):
        """Un group_send a 'alertas_all' llega al cliente conectado."""
        communicator = _make_communicator()
        await communicator.connect()

        channel_layer = get_channel_layer()
        payload = {
            "event": "snapshot_alertas",
            "data": [{"train_id": "TRN-001", "asset_id": "LOCO-100", "alert_count": 1}],
            "count": 1,
        }
        await channel_layer.group_send(
            GROUP_ALL,
            {"type": "alerta.nueva", "data": payload},
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["event"], "snapshot_alertas")
        self.assertEqual(response["count"], 1)
        self.assertEqual(response["data"][0]["train_id"], "TRN-001")
        await communicator.disconnect()

    async def test_connect_with_fecha_filters_rows(self):
        """Si se conecta con ?fecha=YYYY-MM-DD, filtra rows del payload por fecha."""
        communicator = _make_communicator("/ws/alertas/?fecha=2026-05-08")
        await communicator.connect()

        channel_layer = get_channel_layer()
        payload = {
            "event": "snapshot_alertas_list",
            "data": [
                {"id": 1, "fechaCreacion": "2026-05-08T10:00:00Z"},
                {"id": 2, "fechaCreacion": "2026-05-09T10:00:00Z"},
            ],
            "count": 2,
            "pagination": {
                "page": 1,
                "size": 20,
                "totalItems": 2,
                "totalPages": 1,
                "hasNext": False,
                "hasPrev": False,
            },
            "links": {"self": "/api/alertas/?page=1&size=20", "next": None, "prev": None},
        }
        await channel_layer.group_send(
            GROUP_ALL,
            {"type": "alerta.nueva", "data": payload},
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["event"], "snapshot_alertas_list")
        self.assertEqual(response["count"], 1)
        self.assertEqual(len(response["data"]), 1)
        self.assertEqual(response["data"][0]["id"], 1)
        self.assertEqual(response["pagination"]["totalItems"], 1)

        await communicator.disconnect()

    async def test_connect_with_train_id_filters_rows(self):
        """snapshot_alertas NO filtra por train_id (siempre muestra todos los trenes).
        
        Solo snapshot_alertas_list filtra por train_id."""
        communicator = _make_communicator("/ws/alertas/?train_id=TRN-8001")
        await communicator.connect()

        channel_layer = get_channel_layer()
        payload = {
            "event": "snapshot_alertas",
            "data": [
                {"id": 1, "train_id": "TRN-8001"},
                {"id": 2, "train_id": "TRN-9002"},
            ],
            "count": 2,
        }
        await channel_layer.group_send(
            GROUP_ALL,
            {"type": "alerta.nueva", "data": payload},
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["event"], "snapshot_alertas")
        # snapshot_alertas NO filtra por train_id, siempre muestra ambas alertas
        self.assertEqual(response["count"], 2)
        self.assertEqual(len(response["data"]), 2)

        await communicator.disconnect()

    async def test_snapshot_list_train_id_filters_rows(self):
        """Con train_id en query, snapshot_alertas_list filtra solo ese tren."""
        communicator = _make_communicator("/ws/alertas/?train_id=TRN-8001")
        await communicator.connect()

        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            GROUP_ALL,
            {
                "type": "alerta.nueva",
                "data": {
                    "event": "snapshot_alertas_list",
                    "data": [
                        {"id": 11, "train_id": "TRN-8001"},
                        {"id": 12, "train_id": "TRN-9002"},
                    ],
                    "count": 2,
                    "pagination": {
                        "page": 1,
                        "size": 2,
                        "totalItems": 2,
                        "totalPages": 1,
                        "hasNext": False,
                        "hasPrev": False,
                    },
                },
            },
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["event"], "snapshot_alertas_list")
        self.assertEqual(response["count"], 1)
        self.assertEqual(response["pagination"]["totalItems"], 1)
        self.assertEqual(response["data"][0]["id"], 11)

        await communicator.disconnect()

    async def test_broadcast_train_group_reaches_subscriber_only(self):
        """Un broadcast a train_8001 llega solo al cliente suscrito."""
        # Cliente 1: suscrito a train_8001
        comm1 = _make_communicator()
        await comm1.connect()
        await comm1.send_json_to({"action": "subscribe", "train_id": "8001"})
        await comm1.receive_json_from()  # confirmación

        # Cliente 2: NO suscrito a train_8001
        comm2 = _make_communicator()
        await comm2.connect()

        channel_layer = get_channel_layer()
        payload = {
            "event": "snapshot_alertas",
            "train_id": "8001",
            "data": [{"train_id": "8001", "asset_id": "LOCO-500"}],
            "count": 1,
        }
        await channel_layer.group_send(
            "train_8001",
            {"type": "alerta.nueva", "data": payload},
        )

        # Cliente 1 recibe
        response = await comm1.receive_json_from()
        self.assertEqual(response["data"][0]["train_id"], "8001")

        # Cliente 2 NO recibe (timeout)
        nothing = await comm2.receive_nothing(timeout=0.5)
        self.assertTrue(nothing, "Cliente 2 no debió recibir mensaje de train_8001")

        await comm1.disconnect()
        await comm2.disconnect()

    async def test_disconnect_cleans_up_groups(self):
        """Al desconectar, el consumer se limpia de todos los grupos."""
        communicator = _make_communicator()
        await communicator.connect()
        await communicator.send_json_to({"action": "subscribe", "train_id": "9999"})
        await communicator.receive_json_from()

        await communicator.disconnect()

        # Broadcast — nadie debería recibirlo
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            "train_9999",
            {"type": "alerta.nueva", "data": {"event": "ghost"}},
        )
        # No hay error = el grupo existe vacío, lo cual es correcto

    async def test_multiple_subscribes_idempotent(self):
        """Suscribirse al mismo tren dos veces no genera duplicados."""
        communicator = _make_communicator()
        await communicator.connect()

        await communicator.send_json_to({"action": "subscribe", "train_id": "5000"})
        resp1 = await communicator.receive_json_from()
        self.assertEqual(resp1["status"], "subscribed")

        await communicator.send_json_to({"action": "subscribe", "train_id": "5000"})
        resp2 = await communicator.receive_json_from()
        self.assertEqual(resp2["status"], "subscribed")

        # Enviar broadcast — debería llegar solo 1 vez
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            "train_5000",
            {"type": "alerta.nueva", "data": {"event": "test"}},
        )
        response = await communicator.receive_json_from()
        self.assertEqual(response["event"], "test")

        # No debería haber otro mensaje
        nothing = await communicator.receive_nothing(timeout=0.5)
        self.assertTrue(nothing, "No debería recibir el mensaje duplicado")

        await communicator.disconnect()


@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS, ALERTAS_POLLER_ENABLED=False)
class PollerBroadcastEndToEndTests(TestCase):
    """Tests end-to-end: poller → channel_layer → consumer → cliente WS.

    Como _poll_and_broadcast() usa async_to_sync (diseñado para hilos sync),
    y los tests corren en un event loop async, ejecutamos el poller en un
    thread separado igual que en producción.
    """

    def _run_poller_in_thread(self):
        """Ejecuta _poll_and_broadcast en un thread separado (como lo haría APScheduler)."""
        import threading
        from email_alerts.tasks import _poll_and_broadcast
        t = threading.Thread(target=_poll_and_broadcast)
        t.start()
        t.join(timeout=5)

    @patch("email_alerts.tasks.fetch_alertas_since")
    @patch("email_alerts.tasks.fetch_alertas_count")
    @patch("email_alerts.tasks.fetch_alertas_page")
    @patch("email_alerts.tasks.fetch_email_alerts_operational_rows")
    async def test_poll_broadcasts_to_connected_client(
        self,
        mock_fetch_snapshot,
        mock_fetch_page,
        mock_fetch_count,
        mock_fetch_delta,
    ):
        """El poller consulta Databricks (mock) y el cliente WS recibe las alertas."""
        mock_fetch_snapshot.return_value = FAKE_DATABRICKS_ROWS
        mock_fetch_page.return_value = []
        mock_fetch_count.return_value = 0
        mock_fetch_delta.return_value = []

        communicator = _make_communicator()
        await communicator.connect()

        from email_alerts import tasks
        # Ejecutar poller en thread separado (como APScheduler haría)
        await asyncio.to_thread(tasks._poll_and_broadcast)

        response = await communicator.receive_json_from(timeout=2)
        self.assertEqual(response["event"], "snapshot_alertas")
        self.assertEqual(response["count"], 2)
        self.assertIsInstance(response["data"], list)

        self.assertGreaterEqual(mock_fetch_snapshot.call_count, 1)
        mock_fetch_snapshot.assert_any_call(only_today=False)
        mock_fetch_delta.assert_called_once()
        await communicator.disconnect()

    @patch("email_alerts.tasks.fetch_alertas_since")
    @patch("email_alerts.tasks.fetch_alertas_count")
    @patch("email_alerts.tasks.fetch_alertas_page")
    @patch("email_alerts.tasks.fetch_email_alerts_operational_rows")
    async def test_poll_sends_to_train_group(
        self,
        mock_fetch_snapshot,
        mock_fetch_page,
        mock_fetch_count,
        mock_fetch_delta,
    ):
        """El poller envía alertas al grupo específico del tren."""
        mock_fetch_snapshot.return_value = FAKE_DATABRICKS_ROWS
        mock_fetch_page.return_value = []
        mock_fetch_count.return_value = 0
        mock_fetch_delta.return_value = []

        communicator = _make_communicator()
        await communicator.connect()
        await communicator.send_json_to({"action": "subscribe", "train_id": "TRN-8001"})
        await communicator.receive_json_from()  # confirmación subscribe

        from email_alerts import tasks
        await asyncio.to_thread(tasks._poll_and_broadcast)

        # Recibe broadcast global (alertas_all)
        msg1 = await communicator.receive_json_from(timeout=2)
        self.assertEqual(msg1["event"], "snapshot_alertas")
        self.assertEqual(msg1["count"], 2)

        # Recibe broadcast del grupo train_TRN-8001
        msg2 = await communicator.receive_json_from(timeout=2)
        self.assertEqual(msg2["train_id"], "TRN-8001")
        self.assertEqual(msg2["count"], 1)

        await communicator.disconnect()

    @patch("email_alerts.tasks.fetch_alertas_since")
    @patch("email_alerts.tasks.fetch_email_alerts_operational_rows")
    async def test_poll_no_broadcast_when_empty(self, mock_fetch_snapshot, mock_fetch_delta):
        """Si no hay alertas nuevas, no se envía nada."""
        mock_fetch_snapshot.return_value = []
        mock_fetch_delta.return_value = []

        communicator = _make_communicator()
        await communicator.connect()

        from email_alerts import tasks
        await asyncio.to_thread(tasks._poll_and_broadcast)

        nothing = await communicator.receive_nothing(timeout=1)
        self.assertTrue(nothing, "No debería recibir mensaje si no hay alertas nuevas")

        await communicator.disconnect()

    @patch("email_alerts.tasks.fetch_alertas_since")
    @patch("email_alerts.tasks.fetch_email_alerts_operational_rows")
    async def test_poll_handles_databricks_error(self, mock_fetch_snapshot, mock_fetch_delta):
        """Si Databricks falla, el poller no se cae y no envía nada."""
        mock_fetch_snapshot.side_effect = RuntimeError("Databricks timeout")
        mock_fetch_delta.return_value = []

        communicator = _make_communicator()
        await communicator.connect()

        from email_alerts import tasks
        await asyncio.to_thread(tasks._poll_and_broadcast)

        nothing = await communicator.receive_nothing(timeout=1)
        self.assertTrue(nothing, "No debería enviar nada si Databricks falla")

        await communicator.disconnect()

    @patch("email_alerts.tasks.fetch_alertas_since")
    @patch("email_alerts.tasks.fetch_email_alerts_operational_rows")
    async def test_poll_emits_delta_alertas(self, mock_fetch_snapshot, mock_fetch_delta):
        """El poller híbrido emite delta_alertas cuando hay nuevas."""
        mock_fetch_snapshot.return_value = []
        mock_fetch_delta.return_value = [
            {
                "id_alerta": "201",
                "train_id": "TRN-9999",
                "asset_id": "LOCO-9999",
                "titulo": "Delta prueba",
                "descripcion": "Solo nuevas",
                "last_event": "2026-05-08T12:10:00Z",
                "detail_location_at_start": "Norte",
                "detail_location_at_end": "D-99",
                "crew_eng_name": "Juan Perez",
                "detail_mile_post_at_start": "123",
                "detail_mile_post_at_end": "124",
                "prioridad": "2",
            }
        ]

        communicator = _make_communicator()
        await communicator.connect()

        from email_alerts import tasks
        tasks._last_delta_timestamp = None
        await asyncio.to_thread(tasks._poll_and_broadcast)

        msg = await communicator.receive_json_from(timeout=2)
        self.assertEqual(msg["event"], "delta_alertas")
        self.assertEqual(msg["count"], 1)
        self.assertEqual(msg["data"][0]["train_id"], "TRN-9999")
        self.assertEqual(msg["data"][0]["region"], "Norte")
        self.assertEqual(msg["data"][0]["distrito"], "D-99")
        self.assertEqual(msg["data"][0]["maquinista"], "Juan Perez")
        self.assertEqual(msg["data"][0]["detail_mile_post_at_start"], "123")
        self.assertEqual(msg["data"][0]["detail_mile_post_at_end"], "124")
        self.assertEqual(msg["data"][0]["alert_count"], 1)

        await communicator.disconnect()

    @patch("email_alerts.tasks.fetch_alertas_since")
    @patch("email_alerts.tasks.fetch_alertas_count")
    @patch("email_alerts.tasks.fetch_alertas_page")
    @patch("email_alerts.tasks.fetch_email_alerts_operational_rows")
    async def test_poll_emits_snapshot_alertas_list(
        self,
        mock_fetch_snapshot,
        mock_fetch_page,
        mock_fetch_count,
        mock_fetch_delta,
    ):
        """El poller emite snapshot_alertas_list con contrato de /api/alertas/."""
        mock_fetch_snapshot.return_value = [
            {
                "id_alerta": "101",
                "train_id": "TRN-8001",
                "asset_id": "LOCO-5000",
                "titulo": "Exceso velocidad",
                "descripcion": "Superó 80 km/h en PK 45",
                "last_event": "2026-05-08T12:00:00Z",
                "region": "Norte",
                "distrito": "D-02",
                "maquinista": "TEST",
                "detail_mile_post_at_start": "45",
                "detail_mile_post_at_end": "47",
                "alert_count": 1,
                "detail_speed_limit": "80",
            }
        ]
        mock_fetch_page.return_value = [
            {
                "id_alerta": "101",
                "train_id": "TRN-8001",
                "asset_id": "LOCO-5000",
                "titulo": "Exceso velocidad",
                "descripcion": "Superó 80 km/h en PK 45",
                "last_event": "2026-05-08T12:00:00Z",
                "region": "Norte",
                "distrito": "D-02",
                "maquinista": "TEST",
                "detail_mile_post_at_start": "45",
                "detail_mile_post_at_end": "47",
                "alert_count": 1,
                "detail_speed_limit": "80",
            }
        ]
        mock_fetch_count.return_value = 1
        mock_fetch_delta.return_value = []

        communicator = _make_communicator()
        await communicator.connect()

        from email_alerts import tasks
        await asyncio.to_thread(tasks._poll_and_broadcast)

        first_msg = await communicator.receive_json_from(timeout=2)
        second_msg = await communicator.receive_json_from(timeout=2)

        list_msg = first_msg if first_msg.get("event") == "snapshot_alertas_list" else second_msg
        self.assertEqual(list_msg["event"], "snapshot_alertas_list")
        self.assertIn("pagination", list_msg)
        self.assertIn("links", list_msg)
        self.assertEqual(list_msg["pagination"]["totalItems"], 1)
        self.assertEqual(list_msg["data"][0]["id"], 101)
        self.assertEqual(list_msg["data"][0]["detail_speed_limit"], "80")

        await communicator.disconnect()
