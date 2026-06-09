"""Modelos del app email_alerts.

El servicio expone datos externos de Databricks y, en general, no persiste
modelos locales. La única excepción es la bitácora de envíos de WhatsApp, que
sí se guarda localmente para garantizar idempotencia (no reenviar la misma
alerta al mismo destinatario) y dejar trazabilidad auditable para CCO.
"""

from django.db import models


class WhatsAppEnvio(models.Model):
    """Registro de un envío (o intento) de alerta prioritaria por WhatsApp.

    La unicidad ``(id_alerta, telefono)`` es la garantía anti-duplicados: el
    poller corre cada pocos segundos y el delta puede repetir un ``id_alerta``,
    por lo que antes de enviar se hace get_or_create sobre esta tabla.
    """

    STATUS_ENVIADO = "enviado"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_ENVIADO, "Enviado"),
        (STATUS_ERROR, "Error"),
    ]

    id_alerta = models.CharField(max_length=128, db_index=True)
    telefono = models.CharField(max_length=20)
    tipo_alerta = models.CharField(max_length=32, blank=True, default="")
    train_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ENVIADO)
    message_id = models.CharField(max_length=128, blank=True, default="")
    error = models.TextField(blank=True, default="")
    enviado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["id_alerta", "telefono"],
                name="uniq_whatsapp_alerta_telefono",
            )
        ]
        indexes = [models.Index(fields=["enviado_en"])]

    def __str__(self) -> str:
        return f"WhatsAppEnvio(alerta={self.id_alerta}, tel={self.telefono}, status={self.status})"
