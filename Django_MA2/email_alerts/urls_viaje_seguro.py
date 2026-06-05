"""Rutas para Viaje Seguro."""

from django.urls import path

from .views_viaje_seguro import (
    DesempenoRegionView,
    DistritosView,
    GestionView,
    HistCertView,
    IndiceView,
    ReconocimientoView,
    ScoreMensualView,
)

urlpatterns = [
    path("desempeno-region/", DesempenoRegionView.as_view(), name="vs_desempeno_region"),
    path("distritos/", DistritosView.as_view(), name="vs_distritos"),
    path("gestion/", GestionView.as_view(), name="vs_gestion"),
    path("hist-cert/", HistCertView.as_view(), name="vs_hist_cert"),
    path("indice/", IndiceView.as_view(), name="vs_indice"),
    path("reconocimiento/", ReconocimientoView.as_view(), name="vs_reconocimiento"),
    path("score-mensual/", ScoreMensualView.as_view(), name="vs_score_mensual"),
]
