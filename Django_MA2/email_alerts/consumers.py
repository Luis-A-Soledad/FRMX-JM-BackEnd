"""WebSocket consumer para alertas en tiempo real."""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .group_names import safe_train_group_name

logger = logging.getLogger(__name__)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DEFAULT_TIPOS_ALERTA = ("Alerta_01", "Alerta_02", "Alerta_03", "Alerta_06")
# Grupo global al que todos los clientes se suscriben automáticamente
GROUP_ALL = "alertas_all"


class AlertasConsumer(AsyncJsonWebsocketConsumer):
    """Consumer WebSocket para push de alertas.

    - Al conectarse, el cliente entra al grupo ``alertas_all`` y recibe
      todas las alertas nuevas detectadas por el poller.
    - El cliente puede suscribirse a trenes específicos enviando:
        {"action": "subscribe", "train_id": "8001"}
    - Para desuscribirse:
        {"action": "unsubscribe", "train_id": "8001"}
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._train_groups: set[str] = set()
        self._fecha_filter: str | None = None
        self._train_id_filter: str | None = None
        self._tipos_alerta_filter: set[str] = set()

    @property
    def default_tipos_alerta_filter(self) -> tuple[str, ...]:
        """Permite que subclases definan filtros por defecto de tipo alerta."""
        return tuple()

    @staticmethod
    def _parse_tipos_alerta(parsed_qs: dict[str, list[str]]) -> list[str]:
        raw_values: list[str] = []
        raw_values.extend(parsed_qs.get("tipo_alerta", []))
        raw_values.extend(parsed_qs.get("tipos_alerta", []))

        parsed: list[str] = []
        seen: set[str] = set()
        for raw in raw_values:
            for token in str(raw).split(","):
                value = token.strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                parsed.append(value)
        return parsed

    @staticmethod
    def _parse_event_date(value) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        if len(s) < 10:
            return None
        date_part = s[:10]
        if _DATE_RE.match(date_part):
            return date_part
        return None

    def _extract_row_date(self, row: dict) -> str | None:
        extras = row.get("extras") if isinstance(row.get("extras"), dict) else {}
        for cand in (
            row.get("fechaCreacion"),
            row.get("last_event"),
            row.get("event_time_utc"),
            row.get("horaActualizacion"),
            extras.get("last_event"),
            extras.get("event_time_utc"),
        ):
            date_val = self._parse_event_date(cand)
            if date_val:
                return date_val
        return None

    def _extract_row_train_id(self, row: dict) -> str | None:
        extras = row.get("extras") if isinstance(row.get("extras"), dict) else {}
        train_id = row.get("train_id") or extras.get("train_id")
        if train_id is None:
            return None
        train_str = str(train_id).strip()
        return train_str if train_str else None

    def _extract_row_tipo_alerta(self, row: dict) -> str | None:
        extras = row.get("extras") if isinstance(row.get("extras"), dict) else {}
        tipo_alerta = (
            row.get("tipo_alerta")
            or row.get("tipoAlerta")
            or row.get("type")
            or extras.get("tipo_alerta")
            or extras.get("tipoAlerta")
        )
        if tipo_alerta is None:
            return None
        tipo_str = str(tipo_alerta).strip()
        return tipo_str if tipo_str else None

    def _apply_filters(self, payload: dict, filter_by_train_id: bool = False) -> dict | None:
        """Aplica filtros a un payload.
        
        Por defecto, solo filtra por fecha.
        Si filter_by_train_id=True, también filtra por train_id.
        """
        filters_active = (
            self._fecha_filter
            or self._tipos_alerta_filter
            or (filter_by_train_id and self._train_id_filter)
        )
        if not filters_active:
            return payload

        rows = payload.get("data")
        if not isinstance(rows, list):
            return payload

        filtered = rows
        if self._fecha_filter:
            filtered = [row for row in filtered if self._extract_row_date(row) == self._fecha_filter]
        if self._tipos_alerta_filter:
            filtered = [
                row
                for row in filtered
                if self._extract_row_tipo_alerta(row) in self._tipos_alerta_filter
            ]
        if filter_by_train_id and self._train_id_filter:
            filtered = [row for row in filtered if self._extract_row_train_id(row) == self._train_id_filter]
        if not filtered:
            return None

        filtered_payload = dict(payload)
        filtered_payload["data"] = filtered
        if "count" in filtered_payload:
            filtered_payload["count"] = len(filtered)

        if isinstance(filtered_payload.get("pagination"), dict):
            pagination = dict(filtered_payload["pagination"])
            pagination["totalItems"] = len(filtered)
            pagination["totalPages"] = 1
            pagination["hasNext"] = False
            pagination["hasPrev"] = False
            filtered_payload["pagination"] = pagination

        return filtered_payload

    # ── Lifecycle ────────────────────────────────────────────

    async def connect(self):
        raw_qs = self.scope.get("query_string", b"")
        parsed_qs = parse_qs(raw_qs.decode("utf-8") if isinstance(raw_qs, (bytes, bytearray)) else "")
        fecha = (parsed_qs.get("fecha") or [None])[0]
        train_id = (parsed_qs.get("train_id") or [None])[0]
        if isinstance(fecha, str) and _DATE_RE.match(fecha):
            self._fecha_filter = fecha
        if isinstance(train_id, str) and train_id.strip():
            self._train_id_filter = train_id.strip()

        tipos_alerta = self._parse_tipos_alerta(parsed_qs)
        if tipos_alerta:
            self._tipos_alerta_filter = set(tipos_alerta)
        else:
            defaults = [x for x in self.default_tipos_alerta_filter if str(x).strip()]
            if defaults:
                self._tipos_alerta_filter = set(defaults)

        await self.channel_layer.group_add(GROUP_ALL, self.channel_name)
        await self.accept()
        logger.info(
            "WS conectado: %s (fecha=%s, train_id=%s, tipos_alerta=%s)",
            self.channel_name,
            self._fecha_filter,
            self._train_id_filter,
            sorted(self._tipos_alerta_filter) if self._tipos_alerta_filter else None,
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP_ALL, self.channel_name)
        for group in list(self._train_groups):
            await self.channel_layer.group_discard(group, self.channel_name)
        self._train_groups.clear()
        logger.info("WS desconectado: %s (code=%s)", self.channel_name, close_code)

    # ── Mensajes del cliente ─────────────────────────────────

    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        train_id = content.get("train_id")

        if action == "subscribe" and train_id:
            group_name = safe_train_group_name(train_id)
            if not group_name:
                await self.send_json({"error": "train_id inválido para suscripción."})
                return
            if group_name not in self._train_groups:
                await self.channel_layer.group_add(group_name, self.channel_name)
                self._train_groups.add(group_name)
                logger.info("WS %s suscrito a %s", self.channel_name, group_name)
            await self.send_json({"status": "subscribed", "train_id": train_id})

        elif action == "unsubscribe" and train_id:
            group_name = safe_train_group_name(train_id)
            if not group_name:
                await self.send_json({"error": "train_id inválido para desuscripción."})
                return
            if group_name in self._train_groups:
                await self.channel_layer.group_discard(group_name, self.channel_name)
                self._train_groups.discard(group_name)
                logger.info("WS %s desuscrito de %s", self.channel_name, group_name)
            await self.send_json({"status": "unsubscribed", "train_id": train_id})

        else:
            await self.send_json({"error": "Acción no reconocida. Use 'subscribe' o 'unsubscribe' con 'train_id'."})

    # ── Handlers de grupo (invocados por el poller via group_send) ──

    async def alerta_nueva(self, event):
        """Recibe broadcast del poller y lo envia al cliente WebSocket."""
        incoming = event["data"]
        event_type = incoming.get("event")
        
        # snapshot_alertas_list: filtra train_id solo para este tipo de evento
        if event_type == "snapshot_alertas_list" and self._train_id_filter:
            payload = self._apply_filters(incoming, filter_by_train_id=True)
        # snapshot_alertas_list sin train_id: aplica filtro de fecha si existe
        elif event_type == "snapshot_alertas_list":
            payload = self._apply_filters(incoming, filter_by_train_id=False)
        # snapshot_alertas: nunca filtra por train_id (solo por fecha si existe)
        elif event_type == "snapshot_alertas":
            payload = self._apply_filters(incoming, filter_by_train_id=False)
        # snapshot_alertas_filtradas: nunca filtra por train_id (solo por fecha/tipo si existe)
        elif event_type == "snapshot_alertas_filtradas":
            payload = self._apply_filters(incoming, filter_by_train_id=False)
        # delta_alertas: nunca filtra por train_id (solo por fecha si existe)
        elif event_type == "delta_alertas":
            payload = self._apply_filters(incoming, filter_by_train_id=False)
        else:
            # Otros eventos: no filtrar
            payload = incoming
            
        if payload is None:
            return
        await self.send_json(payload)


class AlertasFiltradasConsumer(AlertasConsumer):
    """Consumer con filtro default por tipos de alerta prioritarios."""

    @property
    def default_tipos_alerta_filter(self) -> tuple[str, ...]:
        return _DEFAULT_TIPOS_ALERTA
