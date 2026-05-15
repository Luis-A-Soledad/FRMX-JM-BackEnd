import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class EmailAlertsConfig(AppConfig):
    """Configuracion del app email_alerts."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "email_alerts"

    def ready(self):
        from django.conf import settings

        if getattr(settings, "ALERTAS_POLLER_ENABLED", False):
            from .tasks import start_poller

            start_poller()
            logger.info("Alertas poller habilitado via AppConfig.ready()")
