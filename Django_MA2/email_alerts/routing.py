"""WebSocket URL routing para email_alerts."""

from django.urls import re_path

from .consumers import AlertasConsumer, AlertasFiltradasConsumer

websocket_urlpatterns = [
    re_path(r"ws/alertas/$", AlertasConsumer.as_asgi()),
    re_path(r"ws/alertas/filtradas/$", AlertasFiltradasConsumer.as_asgi()),
]
