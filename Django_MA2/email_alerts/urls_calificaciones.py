"""Rutas para calificaciones de maquinistas."""

from django.urls import path

from .views_calificaciones import (
    CalificacionesMaquinistaView,
    FrecuenciaAlertasMaquinistaView,
    ResumenSemanalMaquinistaView,
    ViajesMaquinistaView,
    ToMaquinistaView,
)

urlpatterns = [
    path("", CalificacionesMaquinistaView.as_view(), name="calificaciones_maquinista"),
    path("frecuencia-alertas/", FrecuenciaAlertasMaquinistaView.as_view(), name="frecuencia_alertas_maquinista"),
    path("resumen-semanal/", ResumenSemanalMaquinistaView.as_view(), name="resumen_semanal_maquinista"),
    path("viajes/", ViajesMaquinistaView.as_view(), name="viajes_maquinista"),
    path("to/", ToMaquinistaView.as_view(), name="to_maquinista"),
]
