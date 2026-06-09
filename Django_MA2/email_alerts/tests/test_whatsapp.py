"""Tests del envío de alertas prioritarias por WhatsApp.

Cubre la lógica pura (sin red) y el hook del poller con la Cloud API mockeada.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from email_alerts import whatsapp
from email_alerts.models import WhatsAppEnvio
from email_alerts.whatsapp import (
    alert_region_to_canon,
    build_template_params,
    build_template_payload,
    contacto_cubre_region,
    format_fecha,
    resolve_destinatarios,
    to_e164_mx,
)


# ---------------------------------------------------------------------------
# Normalización de teléfono
# ---------------------------------------------------------------------------
class ToE164Tests(TestCase):
    def test_diez_digitos_antepone_52(self):
        self.assertEqual(to_e164_mx("3331234567"), "523331234567")

    def test_limpia_separadores(self):
        self.assertEqual(to_e164_mx("33 3123-4567"), "523331234567")

    def test_ya_trae_lada_52(self):
        self.assertEqual(to_e164_mx("523331234567"), "523331234567")

    def test_formato_viejo_521(self):
        self.assertEqual(to_e164_mx("5213331234567"), "523331234567")

    def test_nueve_digitos_invalido(self):
        # Registros mal capturados en silver.administrativo (9 dígitos).
        self.assertIsNone(to_e164_mx("229123456"))

    def test_none_y_vacio(self):
        self.assertIsNone(to_e164_mx(None))
        self.assertIsNone(to_e164_mx(""))
        self.assertIsNone(to_e164_mx("   "))


# ---------------------------------------------------------------------------
# Mapeo de región alerta -> bucket administrativo
# ---------------------------------------------------------------------------
class RegionMappingTests(TestCase):
    def test_canon_centro_mexico(self):
        self.assertEqual(alert_region_to_canon("CENTRO MEXICO"), "CENTRO")

    def test_canon_norte_case_insensitive(self):
        self.assertEqual(alert_region_to_canon("norte"), "NORTE")

    def test_canon_desconocido_es_none(self):
        self.assertIsNone(alert_region_to_canon("Desconocido"))
        self.assertIsNone(alert_region_to_canon("SIN_CATALOGO"))
        self.assertIsNone(alert_region_to_canon(None))

    def test_bucket_simple(self):
        self.assertTrue(contacto_cubre_region("Norte", "NORTE"))
        self.assertFalse(contacto_cubre_region("Norte", "CENTRO"))

    def test_bucket_compuesto_centro_y_ferrosur(self):
        self.assertTrue(contacto_cubre_region("Centro y Ferrosur", "CENTRO"))
        self.assertTrue(contacto_cubre_region("Centro y Ferrosur", "FERROSUR"))
        self.assertFalse(contacto_cubre_region("Centro y Ferrosur", "NORTE"))

    def test_todo_el_sistema_recibe_todo(self):
        self.assertTrue(contacto_cubre_region("Todo el sistema", "NORTE"))
        self.assertTrue(contacto_cubre_region("Todo el sistema", None))  # incluso desconocida


# ---------------------------------------------------------------------------
# Formato de fecha y parámetros del template
# ---------------------------------------------------------------------------
class FormatTests(TestCase):
    def test_fecha_iso_utc_a_local_mx(self):
        # 2026-06-08T18:00:00Z → 12:00 hora centro (UTC-6)
        out = format_fecha("2026-06-08T18:00:00Z")
        self.assertIn("08/06/2026", out)

    def test_fecha_no_parseable_devuelve_crudo(self):
        self.assertEqual(format_fecha("ayer"), "ayer")

    def test_fecha_none(self):
        self.assertEqual(format_fecha(None), "—")

    def test_params_orden_y_fallback_nombre(self):
        row = {
            "tipo_alerta": "Alerta_01",
            "train_id": "TRN-007",
            "last_event": "2026-06-08T18:00:00Z",
            "detail_mile_post_at_start": "123.4",
        }
        nombre, tren, fecha, pk = build_template_params(row)
        self.assertEqual(nombre, "Velocidad")  # fallback desde tipo_alerta
        self.assertEqual(tren, "TRN-007")
        self.assertIn("08/06/2026", fecha)
        self.assertEqual(pk, "123.4")

    def test_params_prioriza_nombre_alerta(self):
        row = {"nombre_alerta": "Exceso de velocidad", "tipo_alerta": "Alerta_01"}
        nombre = build_template_params(row)[0]
        self.assertEqual(nombre, "Exceso de velocidad")

    def test_clean_param_sin_saltos_de_linea(self):
        row = {"train_id": "TRN\n007"}
        self.assertEqual(build_template_params(row)[1], "TRN 007")


# ---------------------------------------------------------------------------
# Payload del template
# ---------------------------------------------------------------------------
@override_settings(
    WHATSAPP_TEMPLATE_NAME="alerta_prioritaria",
    WHATSAPP_TEMPLATE_LANG="es_MX",
)
class PayloadTests(TestCase):
    def test_estructura_payload(self):
        payload = build_template_payload("523331234567", ["A", "B", "C", "D"])
        self.assertEqual(payload["messaging_product"], "whatsapp")
        self.assertEqual(payload["to"], "523331234567")
        self.assertEqual(payload["type"], "template")
        tpl = payload["template"]
        self.assertEqual(tpl["name"], "alerta_prioritaria")
        self.assertEqual(tpl["language"]["code"], "es_MX")
        body = tpl["components"][0]
        self.assertEqual(body["type"], "body")
        self.assertEqual([p["text"] for p in body["parameters"]], ["A", "B", "C", "D"])


# ---------------------------------------------------------------------------
# Resolución de destinatarios
# ---------------------------------------------------------------------------
class ResolveDestinatariosTests(TestCase):
    CONTACTOS = [
        {"nombre": "Ana", "region": "Norte", "telefono": "3331234567", "cargo": "Jefe de Maq."},
        {"nombre": "Beto", "region": "Centro", "telefono": "5512345678", "cargo": "Jefe de Maq."},
        {"nombre": "Cid", "region": "Todo el sistema", "telefono": "8112345678", "cargo": "Alertas"},
        {"nombre": "Dan", "region": "Norte", "telefono": "229123456", "cargo": "Jefe de Maq."},  # tel inválido
    ]

    def test_filtra_por_region_y_incluye_catchall(self):
        dests = resolve_destinatarios("NORTE", self.CONTACTOS)
        nombres = {d["nombre"] for d in dests}
        self.assertEqual(nombres, {"Ana", "Cid"})  # Beto(Centro) fuera; Dan tel inválido

    def test_region_desconocida_solo_catchall(self):
        dests = resolve_destinatarios("SIN_CATALOGO", self.CONTACTOS)
        self.assertEqual({d["nombre"] for d in dests}, {"Cid"})

    def test_telefono_normalizado_a_e164(self):
        dests = resolve_destinatarios("NORTE", self.CONTACTOS)
        ana = next(d for d in dests if d["nombre"] == "Ana")
        self.assertEqual(ana["telefono"], "523331234567")


# ---------------------------------------------------------------------------
# Hook del poller: idempotencia y aislamiento de fallos
# ---------------------------------------------------------------------------
ALERTA_PRIORITARIA = {
    "id_alerta": "A-1",
    "tipo_alerta": "Alerta_01",
    "train_id": "TRN-007",
    "region": "NORTE",
    "last_event": "2026-06-08T18:00:00Z",
    "detail_mile_post_at_start": "123.4",
    "nombre_alerta": "Exceso de velocidad",
}
ALERTA_NO_PRIORITARIA = {**ALERTA_PRIORITARIA, "id_alerta": "A-2", "tipo_alerta": "Alerta_05"}
CONTACTOS_FAKE = [
    {"nombre": "Ana", "region": "Norte", "telefono": "3331234567", "cargo": "Jefe de Maq."},
]


@override_settings(ALERTAS_WHATSAPP_ENABLED=True, WHATSAPP_CARGOS_DESTINO="Jefe de Maq.")
class NotifyWhatsAppTests(TestCase):
    def setUp(self):
        self.p_contactos = patch(
            "email_alerts.service.fetch_administrativo_contactos",
            return_value=CONTACTOS_FAKE,
        )
        self.p_send = patch(
            "email_alerts.whatsapp.send_template_message",
            return_value={"messages": [{"id": "wamid.TEST"}]},
        )

    def test_envia_solo_prioritarias_y_registra(self):
        from email_alerts.tasks import _notify_whatsapp

        with self.p_contactos, self.p_send as mock_send:
            _notify_whatsapp([ALERTA_PRIORITARIA, ALERTA_NO_PRIORITARIA])

        self.assertEqual(mock_send.call_count, 1)
        envio = WhatsAppEnvio.objects.get()
        self.assertEqual(envio.id_alerta, "A-1")
        self.assertEqual(envio.telefono, "523331234567")
        self.assertEqual(envio.status, WhatsAppEnvio.STATUS_ENVIADO)
        self.assertEqual(envio.message_id, "wamid.TEST")

    def test_idempotencia_no_reenvia(self):
        from email_alerts.tasks import _notify_whatsapp

        with self.p_contactos, self.p_send as mock_send:
            _notify_whatsapp([ALERTA_PRIORITARIA])
            _notify_whatsapp([ALERTA_PRIORITARIA])  # segunda pasada del poller

        self.assertEqual(mock_send.call_count, 1)
        self.assertEqual(WhatsAppEnvio.objects.count(), 1)

    def test_error_de_envio_se_registra_y_no_propaga(self):
        from email_alerts.tasks import _notify_whatsapp

        with self.p_contactos, patch(
            "email_alerts.whatsapp.send_template_message",
            side_effect=RuntimeError("WhatsApp API HTTP 401"),
        ):
            _notify_whatsapp([ALERTA_PRIORITARIA])  # no debe lanzar

        envio = WhatsAppEnvio.objects.get()
        self.assertEqual(envio.status, WhatsAppEnvio.STATUS_ERROR)
        self.assertIn("401", envio.error)

    @override_settings(ALERTAS_WHATSAPP_ENABLED=False)
    def test_flag_desactivado_no_envia(self):
        from email_alerts.tasks import _notify_whatsapp

        with self.p_contactos, self.p_send as mock_send:
            _notify_whatsapp([ALERTA_PRIORITARIA])

        mock_send.assert_not_called()
        self.assertEqual(WhatsAppEnvio.objects.count(), 0)
