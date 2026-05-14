"""Rutas para el servicio email_alerts."""

from django.urls import path

from .views import EmailAlertsOperationalView

urlpatterns = [
    path("", EmailAlertsOperationalView.as_view(), name="email_alerts_operational"),
]
