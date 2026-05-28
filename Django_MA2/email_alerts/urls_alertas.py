"""Rutas para el recurso REST alertas."""

from django.urls import path
from django.views.generic import TemplateView

from .views_alertas import (
    AlertaDetailView,
    AlertasFiltradasListView,
    AlertasListView,
    AlertasPorLocoPrincipalView,
    AlertasPorLocoPrincipalFiltradasView,
    DebugBroadcastView,
)

urlpatterns = [
    path("", AlertasListView.as_view(), name="alertas_list"),
    path("alertas-filtradas/", AlertasFiltradasListView.as_view(), name="alertas_list_filtradas"),
    path("alertas-por-loco-principal/", AlertasPorLocoPrincipalView.as_view(), name="alertas_por_loco_principal"),
    path("alertas-por-loco-principal-filtradas/", AlertasPorLocoPrincipalFiltradasView.as_view(), name="alertas_por_loco_principal_filtradas"),
    path("debug-broadcast/", DebugBroadcastView.as_view(), name="debug_broadcast"),
    path("ws-monitor/", TemplateView.as_view(template_name="ws_monitor.html"), name="ws_monitor"),
    path("<int:id>/", AlertaDetailView.as_view(), name="alertas_detail"),
]