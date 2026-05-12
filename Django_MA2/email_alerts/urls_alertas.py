"""Rutas para el recurso REST alertas."""

from django.urls import path
from django.views.generic import TemplateView

from .views_alertas import (
    AlertaDetailView,
    AlertasListView,
    AlertasPorLocoPrincipalView,
    DebugBroadcastView,
)

urlpatterns = [
    path("", AlertasListView.as_view(), name="alertas_list"),
    path("alertas-por-loco-principal/", AlertasPorLocoPrincipalView.as_view(), name="alertas_por_loco_principal"),
    path("debug-broadcast/", DebugBroadcastView.as_view(), name="debug_broadcast"),
    path("ws-monitor/", TemplateView.as_view(template_name="ws_monitor.html"), name="ws_monitor"),
    path("<int:id>/", AlertaDetailView.as_view(), name="alertas_detail"),
]