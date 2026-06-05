from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from email_alerts.views_alertas import AlertasFiltradasListView

urlpatterns = [
    path("admin/", admin.site.urls),
    # ─── Auth endpoints (tokens) ────────────────
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # ─── API ────────────────────────────────────
    path("api/", include("api.urls")),
    path("api/email-alerts/operational/", include("email_alerts.urls")),
    path("api/alertas/", include("email_alerts.urls_alertas")),
    path("api/alertas-filtradas/", AlertasFiltradasListView.as_view(), name="alertas_filtradas_alias"),
    path("api/calificaciones/", include("email_alerts.urls_calificaciones")),
    path("api/viaje-seguro/", include("email_alerts.urls_viaje_seguro")),
]