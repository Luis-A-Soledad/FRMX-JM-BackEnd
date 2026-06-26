"""Management command para emitir alertas fake por WebSocket.

Uso:
    python manage.py broadcast_fake_alerta
    python manage.py broadcast_fake_alerta --train-id 8001
    python manage.py broadcast_fake_alerta --count 5
"""

import json
from datetime import datetime, timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.management.base import BaseCommand
from zoneinfo import ZoneInfo


class Command(BaseCommand):
    help = "Emite alertas fake al channel layer para probar el WebSocket."

    def add_arguments(self, parser):
        parser.add_argument(
            "--train-id",
            default="TRN-TEST-001",
            help="train_id de la alerta fake (default: TRN-TEST-001)",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=1,
            help="Cantidad de alertas fake a emitir (default: 1)",
        )

    def handle(self, *args, **options):
        train_id = options["train_id"]
        count = options["count"]
        channel_layer = get_channel_layer()

        if channel_layer is None:
            self.stderr.write(self.style.ERROR("Channel layer no disponible."))
            return

        alertas = []
        for i in range(count):
            alertas.append({
                "id": f"FAKE-{i+1}",
                "train_id": train_id,
                "locomotora": f"LOCO-{1000+i}",
                "ultimaAlerta": "Exceso de velocidad (TEST)",
                "descripcion": f"Alerta de prueba #{i+1} generada manualmente",
                "region": "Norte",
                "distrito": "D-01",
                "pkInicio": "100.5",
                "pkFin": "102.3",
                "prioridad": "Alta",
                "horaActualizacion": datetime.now(ZoneInfo("America/Mexico_City")).isoformat(),
            })

        payload = {
            "event": "nuevas_alertas",
            "count": len(alertas),
            "alertas": alertas,
        }

        # Broadcast global
        async_to_sync(channel_layer.group_send)(
            "alertas_all",
            {"type": "alerta.nueva", "data": payload},
        )

        # Broadcast al grupo del tren
        train_payload = {**payload, "train_id": train_id}
        async_to_sync(channel_layer.group_send)(
            f"train_{train_id}",
            {"type": "alerta.nueva", "data": train_payload},
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Broadcast OK: {count} alerta(s) fake para train_id={train_id}"
            )
        )
        self.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
