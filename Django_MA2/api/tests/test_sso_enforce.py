"""Tests for SSO enforcement — anti-bypass via token omission.

Validates that when ENTRA_SSO_ENFORCE=True:
- Anonymous requests to /api/chat/ and /api/session/ return 401 (not 403).
- Authenticated users with disallowed roles are blocked (403).
- Authenticated users with allowed roles pass through (200).

When ENTRA_SSO_ENFORCE=False (default / dev):
- Anonymous requests are allowed.
- Authenticated users with disallowed roles are still blocked (403).

Also tests:
- Configurable allowlist via ENTRA_SSO_ALLOWED_ROLES.
- Guardrail: ENFORCE=1 + AUTH_ENABLED=0 logs a warning (DEBUG) / raises (prod).
"""

import logging
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, UserProfile

User = get_user_model()


# ── Mock helpers (same as test_chat_endpoint.py) ──────────────────────

def _mock_run_agent(question, session_id, user_context=None, **kw):
    return {
        "answer": "[TEST]",
        "decision": "mock",
        "orchestrator_reason": "test",
        "session_id": session_id,
        "last_db_table": None,
        "last_error": "",
        "rol": None,
    }


def _mock_get_or_create(sid=None):
    return sid or "test-session"


def _mock_delete_session(sid):
    return True


# ── Fixtures ──────────────────────────────────────────────────────────

class _SSOEnforceFixtures(TestCase):
    """Shared test data for SSO enforcement tests."""

    @classmethod
    def setUpTestData(cls):
        cls.role_cco, _ = Role.objects.get_or_create(name="CCO")
        cls.role_jefe, _ = Role.objects.get_or_create(name="JEFE_MAQUINISTAS")
        cls.role_op, _ = Role.objects.get_or_create(name="OPERADOR")

        cls.user_cco = User.objects.create_user(
            username="cco_enforce", password="test123",
        )
        UserProfile.objects.create(user=cls.user_cco, role=cls.role_cco)

        cls.user_jefe = User.objects.create_user(
            username="jefe_enforce", password="test123",
        )
        UserProfile.objects.create(user=cls.user_jefe, role=cls.role_jefe)

        cls.user_operador = User.objects.create_user(
            username="op_enforce", password="test123",
        )
        UserProfile.objects.create(user=cls.user_operador, role=cls.role_op)

        # Authenticated but no profile → role UNKNOWN
        cls.user_unknown = User.objects.create_user(
            username="unknown_enforce", password="test123",
        )

    def setUp(self):
        self.client = APIClient()


# ══════════════════════════════════════════════════════════════════════
#  ENFORCE = True  (production)
# ══════════════════════════════════════════════════════════════════════

@override_settings(ENTRA_SSO_ENFORCE=True)
@patch("api.views.delete_session", side_effect=_mock_delete_session)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class EnforceOnChatTests(_SSOEnforceFixtures):
    """POST /api/chat/ with ENTRA_SSO_ENFORCE=True."""

    URL = "/api/chat/"

    def test_anon_returns_401(self, *_mocks):
        """Anonymous request must get 401 — not 403."""
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 401)

    def test_unknown_role_blocked(self, *_mocks):
        self.client.force_authenticate(user=self.user_unknown)
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_operador_blocked(self, *_mocks):
        self.client.force_authenticate(user=self.user_operador)
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_cco_allowed(self, *_mocks):
        self.client.force_authenticate(user=self.user_cco)
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 200)

    def test_jefe_allowed(self, *_mocks):
        self.client.force_authenticate(user=self.user_jefe)
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 200)


@override_settings(ENTRA_SSO_ENFORCE=True)
@patch("api.views.delete_session", side_effect=_mock_delete_session)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class EnforceOnSessionTests(_SSOEnforceFixtures):
    """DELETE /api/session/ with ENTRA_SSO_ENFORCE=True."""

    URL = "/api/session/"

    def test_anon_returns_401(self, *_mocks):
        resp = self.client.delete(
            self.URL, {"session_id": "s1"}, format="json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_unknown_role_blocked(self, *_mocks):
        self.client.force_authenticate(user=self.user_unknown)
        resp = self.client.delete(
            self.URL, {"session_id": "s1"}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_cco_allowed(self, *_mocks):
        self.client.force_authenticate(user=self.user_cco)
        resp = self.client.delete(
            self.URL, {"session_id": "s1"}, format="json",
        )
        self.assertIn(resp.status_code, (200, 404))


# ══════════════════════════════════════════════════════════════════════
#  ENFORCE = False  (dev / default)
# ══════════════════════════════════════════════════════════════════════

@override_settings(ENTRA_SSO_ENFORCE=False)
@patch("api.views.delete_session", side_effect=_mock_delete_session)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class EnforceOffChatTests(_SSOEnforceFixtures):
    """POST /api/chat/ with ENTRA_SSO_ENFORCE=False (dev convenience)."""

    URL = "/api/chat/"

    def test_anon_allowed(self, *_mocks):
        """Without enforce, anonymous access is still allowed (dev)."""
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 200)

    def test_unknown_still_blocked(self, *_mocks):
        """Even without enforce, authenticated UNKNOWN gets 403."""
        self.client.force_authenticate(user=self.user_unknown)
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_cco_allowed(self, *_mocks):
        self.client.force_authenticate(user=self.user_cco)
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 200)


# ══════════════════════════════════════════════════════════════════════
#  Public endpoints stay unaffected
# ══════════════════════════════════════════════════════════════════════

@override_settings(ENTRA_SSO_ENFORCE=True)
class PublicEndpointsUnaffectedTests(TestCase):
    """SSO config and health must remain public regardless of enforce mode."""

    def setUp(self):
        self.client = APIClient()

    def test_sso_config_public(self):
        resp = self.client.get("/api/sso/config/")
        self.assertEqual(resp.status_code, 200)

    def test_health_public(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)


# ══════════════════════════════════════════════════════════════════════
#  Configurable allowlist via ENTRA_SSO_ALLOWED_ROLES
# ══════════════════════════════════════════════════════════════════════

@override_settings(
    ENTRA_SSO_ENFORCE=True,
    ENTRA_SSO_ALLOWED_ROLES=frozenset({"cco"}),  # only CCO
)
@patch("api.views.delete_session", side_effect=_mock_delete_session)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class CustomAllowlistTests(_SSOEnforceFixtures):
    """When allowlist is restricted to CCO only, JEFE must be denied."""

    URL = "/api/chat/"

    def test_cco_still_allowed(self, *_mocks):
        self.client.force_authenticate(user=self.user_cco)
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 200)

    def test_jefe_now_denied(self, *_mocks):
        """JEFE_MAQUINISTAS is NOT in the custom allowlist → 403."""
        self.client.force_authenticate(user=self.user_jefe)
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_operador_still_denied(self, *_mocks):
        self.client.force_authenticate(user=self.user_operador)
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 403)


# ══════════════════════════════════════════════════════════════════════
#  Guardrail: ENFORCE=1 + AUTH_ENABLED=0
# ══════════════════════════════════════════════════════════════════════

class GuardrailTests(TestCase):
    """ENFORCE=1 without AUTH_ENABLED=1 must warn (debug) or crash (prod)."""

    def test_debug_mode_logs_warning(self):
        """In DEBUG mode, a loud warning is emitted but startup proceeds."""
        import importlib
        import core.settings as mod

        with patch.dict(
            "os.environ",
            {
                "ENTRA_SSO_ENFORCE": "1",
                "ENTRA_AUTH_ENABLED": "0",
                "DJANGO_DEBUG": "True",
            },
        ):
            with self.assertLogs("core.settings", level=logging.WARNING) as cm:
                importlib.reload(mod)

        self.assertTrue(
            any("ENTRA_SSO_ENFORCE=1 but ENTRA_AUTH_ENABLED=0" in m for m in cm.output),
            f"Expected warning not found in logs: {cm.output}",
        )

    def test_production_raises_improperly_configured(self):
        """In production (DEBUG=False), misconfiguration must crash."""
        import importlib
        import core.settings as mod

        # Temporarily set env vars to trigger the guardrail on reload
        with patch.dict(
            "os.environ",
            {"ENTRA_SSO_ENFORCE": "1", "ENTRA_AUTH_ENABLED": "0", "DJANGO_DEBUG": "False"},
        ):
            with self.assertRaises(ImproperlyConfigured):
                importlib.reload(mod)
