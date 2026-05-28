"""Vistas API para exponer alertas operacionales de Databricks."""

from __future__ import annotations

from django.conf import settings as django_settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from api.authentication.entra import EntraBearerAuthentication
from api.permissions import IsAllowedSSORole

from .service import fetch_email_alerts_operational_rows


def _email_alerts_authenticators():
    """Replica la logica de autenticadores de api.views para consistencia."""
    if getattr(django_settings, "ENTRA_AUTH_ENABLED", False):
        return [EntraBearerAuthentication(), JWTAuthentication()]
    return [JWTAuthentication()]


class EmailAlertsOperationalView(APIView):
    """GET que retorna objetos JSON dinamicos sin serializer estricto."""

    permission_classes = [IsAllowedSSORole]

    def get_authenticators(self):
        return _email_alerts_authenticators()

    def get(self, request):
        limit_param = request.query_params.get("limit")
        limit: int | None = None
        only_last_12_hours_raw = request.query_params.get("only_last_12_hours", "true").lower()
        only_last_12_hours = only_last_12_hours_raw in ("true", "1", "yes")

        if limit_param is not None:
            try:
                limit = int(limit_param)
            except (TypeError, ValueError):
                return Response(
                    {"error": "Parametro 'limit' debe ser un entero."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if limit < 1:
                return Response(
                    {"error": "Parametro 'limit' debe ser mayor a 0."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            rows = fetch_email_alerts_operational_rows(
                limit=limit,
                only_today=not only_last_12_hours,
                last_hours=12 if only_last_12_hours else None,
            )
            return Response(rows, status=status.HTTP_200_OK)
        except RuntimeError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            return Response(
                {"error": f"No fue posible consultar Databricks: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
