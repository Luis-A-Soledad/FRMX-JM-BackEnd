from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),
    # ─── Auth endpoints (tokens) ────────────────
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # ─── API ────────────────────────────────────
    path("api/", include("api.urls")),
    path("api/email-alerts/operational/", include("email_alerts.urls")),
    path("api/alertas/", include("email_alerts.urls_alertas")),
]