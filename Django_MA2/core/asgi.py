"""ASGI entrypoint — HTTP + WebSocket routing via Django Channels."""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

# Django ASGI app (handles normal HTTP requests)
django_asgi_app = get_asgi_application()

# Import WS routes after Django setup so apps are loaded
from email_alerts.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        ),
    }
)
