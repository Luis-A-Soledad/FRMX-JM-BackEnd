"""Cliente WebSocket para probar el endpoint ws/alertas/.

Uso:
    python test_ws_client.py
    python test_ws_client.py --host localhost --port 8000
    python test_ws_client.py --subscribe TRN-TEST-001

Requiere: pip install websockets
"""

import argparse
import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("Instalar websockets: pip install websockets")
    sys.exit(1)


async def run_client(host: str, port: int, subscribe_train: str | None = None):
    uri = f"ws://{host}:{port}/ws/alertas/"
    print(f"[*] Conectando a {uri} ...")

    try:
        async with websockets.connect(uri) as ws:
            print("[+] Conectado! Esperando mensajes... (Ctrl+C para salir)\n")

            # Suscribirse a un tren si se indicó
            if subscribe_train:
                msg = json.dumps({"action": "subscribe", "train_id": subscribe_train})
                await ws.send(msg)
                print(f"[>] Enviado subscribe: {msg}")
                resp = await ws.recv()
                print(f"[<] Respuesta: {resp}\n")

            # Escuchar mensajes
            async for message in ws:
                data = json.loads(message)
                event = data.get("event", "?")
                count = data.get("count", 0)
                train = data.get("train_id", "all")

                print(f"[ALERTA] evento={event} | count={count} | train={train}")
                if "alertas" in data:
                    for i, a in enumerate(data["alertas"], 1):
                        print(f"  #{i}: id={a.get('id')} "
                              f"loco={a.get('locomotora')} "
                              f"titulo={a.get('ultimaAlerta')} "
                              f"prioridad={a.get('prioridad')}")
                print()

    except websockets.exceptions.ConnectionClosed as e:
        print(f"[-] Conexión cerrada: {e}")
    except ConnectionRefusedError:
        print(f"[-] No se pudo conectar a {uri}. ¿Está corriendo daphne?")
    except KeyboardInterrupt:
        print("\n[*] Desconectado por usuario")


def main():
    parser = argparse.ArgumentParser(description="Test WebSocket alertas client")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--subscribe", dest="train", default=None,
                        help="train_id al que suscribirse (ej: TRN-TEST-001)")
    args = parser.parse_args()
    asyncio.run(run_client(args.host, args.port, args.train))


if __name__ == "__main__":
    main()
