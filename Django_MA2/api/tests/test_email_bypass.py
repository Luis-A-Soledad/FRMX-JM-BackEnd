"""Tests for EmailBypassAuthentication — email-header-based dev/staging auth.

All tests use ``@override_settings`` so they are isolated from the current
environment configuration.  ``MOCK_AGENT=1`` must be set to run these tests
(the test runner patches ``run_agent`` and ``get_or_create_session``).

Run:
    $env:MOCK_AGENT="1"; python manage.py test api.tests.test_email_bypass -v2
"""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, UserProfile
from api.authentication.bypass import EmailBypassAuthentication

User = get_user_model()

# ── Shared mock helpers ───────────────────────────────────────────────

MOCK_AGENT_RESPONSE = {
    "answer": "[BYPASS-TEST] mock answer",
    "decision": "mock",
    "orchestrator_reason": "test",
    "session_id": "ignored",
    "last_db_table": None,
    "last_error": "",
    "rol": None,
}


def _mock_run_agent(question, session_id, user_context=None, **kwargs):
    return {**MOCK_AGENT_RESPONSE, "session_id": session_id}


def _mock_get_or_create(session_id=None):
    return session_id or "bypass-test-session"


def _mock_delete_session(sid):
    return True


# ── Settings shortcuts ────────────────────────────────────────────────

_BYPASS_ON = {
    "EMAIL_BYPASS_ENABLED": True,
    "EMAIL_BYPASS_MAP": {
        "ana@frmx.com": "CCO",
        "luis@frmx.com": "JEFE_MAQUINISTAS",
    },
    # Keep enforce OFF so anonymous requests aren't blocked unless we explicitly test it
    "ENTRA_SSO_ENFORCE": False,
}

_BYPASS_OFF = {
    "EMAIL_BYPASS_ENABLED": False,
    "EMAIL_BYPASS_MAP": {},
    "ENTRA_SSO_ENFORCE": False,
}


# ══════════════════════════════════════════════════════════════════════
#  Unit tests: EmailBypassAuthentication.authenticate()
# ══════════════════════════════════════════════════════════════════════

class BypassAuthenticateUnitTests(TestCase):
    """Direct unit tests for the authenticate() method."""

    @classmethod
    def setUpTestData(cls):
        cls.role_cco, _ = Role.objects.get_or_create(name="CCO")
        cls.role_jefe, _ = Role.objects.get_or_create(name="JEFE_MAQUINISTAS")

    def _make_request(self, email_header: str | None = None):
        """Create a minimal fake request with the given header value."""
        from django.test import RequestFactory
        rf = RequestFactory()
        req = rf.get("/")
        if email_header is not None:
            req.META["HTTP_X_BYPASS_EMAIL"] = email_header
        return req

    # ── bypass disabled ──────────────────────────────────────────────

    @override_settings(**_BYPASS_OFF)
    def test_bypass_disabled_returns_none(self):
        """When EMAIL_BYPASS_ENABLED=False, authenticate() always returns None."""
        auth = EmailBypassAuthentication()
        result = auth.authenticate(self._make_request("ana@frmx.com"))
        self.assertIsNone(result)

    # ── bypass enabled / header absent ──────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_no_header_returns_none(self):
        auth = EmailBypassAuthentication()
        result = auth.authenticate(self._make_request())
        self.assertIsNone(result)

    # ── invalid email format ─────────────────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_invalid_email_returns_none(self):
        auth = EmailBypassAuthentication()
        self.assertIsNone(auth.authenticate(self._make_request("not-an-email")))
        self.assertIsNone(auth.authenticate(self._make_request("missing@")))
        self.assertIsNone(auth.authenticate(self._make_request("@nodomain")))

    # ── email not in map ─────────────────────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_email_not_in_map_returns_none(self):
        auth = EmailBypassAuthentication()
        result = auth.authenticate(self._make_request("stranger@frmx.com"))
        self.assertIsNone(result)

    # ── successful authentication ────────────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_valid_email_cco_returns_user_and_token(self):
        auth = EmailBypassAuthentication()
        result = auth.authenticate(self._make_request("ana@frmx.com"))
        self.assertIsNotNone(result)
        user, token = result
        self.assertEqual(token["bypass"], True)
        self.assertEqual(token["email"], "ana@frmx.com")
        self.assertEqual(token["role"], "CCO")

    @override_settings(**_BYPASS_ON)
    def test_valid_email_jefe_returns_user_and_token(self):
        auth = EmailBypassAuthentication()
        result = auth.authenticate(self._make_request("luis@frmx.com"))
        self.assertIsNotNone(result)
        user, token = result
        self.assertEqual(token["role"], "JEFE_MAQUINISTAS")

    # ── case insensitivity ───────────────────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_uppercase_header_is_lowercased(self):
        """X-Bypass-Email: ANA@FRMX.COM should match 'ana@frmx.com' in the map."""
        auth = EmailBypassAuthentication()
        result = auth.authenticate(self._make_request("ANA@FRMX.COM"))
        self.assertIsNotNone(result)
        _, token = result
        self.assertEqual(token["email"], "ana@frmx.com")
        self.assertEqual(token["role"], "CCO")

    # ── idempotence ───────────────────────────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_same_email_twice_creates_single_user(self):
        """Calling authenticate() twice for the same email must not duplicate the User."""
        auth = EmailBypassAuthentication()
        auth.authenticate(self._make_request("ana@frmx.com"))
        auth.authenticate(self._make_request("ana@frmx.com"))
        count = User.objects.filter(username="bypass_ana@frmx.com").count()
        self.assertEqual(count, 1)

    # ── UserProfile creation ─────────────────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_user_profile_created_with_correct_role(self):
        auth = EmailBypassAuthentication()
        result = auth.authenticate(self._make_request("luis@frmx.com"))
        user, _ = result
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.role.name, "JEFE_MAQUINISTAS")

    # ── authenticate_header ──────────────────────────────────────────

    def test_authenticate_header_returns_bearer_realm(self):
        auth = EmailBypassAuthentication()
        from django.test import RequestFactory
        req = RequestFactory().get("/")
        self.assertEqual(auth.authenticate_header(req), 'Bearer realm="dev-bypass"')


# ══════════════════════════════════════════════════════════════════════
#  Integration tests: /api/chat/ endpoint with bypass
# ══════════════════════════════════════════════════════════════════════

@patch("api.views.delete_session", side_effect=_mock_delete_session)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class BypassChatIntegrationTests(TestCase):
    """POST /api/chat/ with EmailBypassAuthentication."""

    URL = "/api/chat/"

    @classmethod
    def setUpTestData(cls):
        cls.role_cco, _ = Role.objects.get_or_create(name="CCO")
        cls.role_jefe, _ = Role.objects.get_or_create(name="JEFE_MAQUINISTAS")

    def setUp(self):
        self.client = APIClient()

    # ── bypass OFF ───────────────────────────────────────────────────

    @override_settings(**_BYPASS_OFF)
    def test_bypass_off_header_ignored_anon(self, *_mocks):
        """When bypass is disabled, the X-Bypass-Email header has no effect."""
        self.client.credentials(HTTP_X_BYPASS_EMAIL="ana@frmx.com")
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["role"], "ANON")

    # ── bypass ON + valid emails ─────────────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_bypass_on_cco_returns_200_with_role(self, *_mocks):
        self.client.credentials(HTTP_X_BYPASS_EMAIL="ana@frmx.com")
        resp = self.client.post(self.URL, {"question": "alertas"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["role"], "CCO")

    @override_settings(**_BYPASS_ON)
    def test_bypass_on_jefe_returns_200_with_role(self, *_mocks):
        self.client.credentials(HTTP_X_BYPASS_EMAIL="luis@frmx.com")
        resp = self.client.post(self.URL, {"question": "alertas"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["role"], "JEFE_MAQUINISTAS")

    @override_settings(**_BYPASS_ON)
    def test_bypass_on_case_insensitive(self, *_mocks):
        """Uppercase email in header should authenticate correctly."""
        self.client.credentials(HTTP_X_BYPASS_EMAIL="ANA@FRMX.COM")
        resp = self.client.post(self.URL, {"question": "alertas"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["role"], "CCO")

    # ── bypass ON + email not in map ─────────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_bypass_on_email_not_in_map_returns_anon(self, *_mocks):
        self.client.credentials(HTTP_X_BYPASS_EMAIL="unknown@frmx.com")
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["role"], "ANON")

    # ── bypass ON + no header ────────────────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_bypass_on_no_header_returns_anon(self, *_mocks):
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["role"], "ANON")

    # ── bypass ON + invalid email ────────────────────────────────────

    @override_settings(**_BYPASS_ON)
    def test_bypass_on_invalid_email_returns_anon(self, *_mocks):
        self.client.credentials(HTTP_X_BYPASS_EMAIL="not-an-email")
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["role"], "ANON")


# ══════════════════════════════════════════════════════════════════════
#  Integration tests: bypass + ENFORCE=True
# ══════════════════════════════════════════════════════════════════════

_BYPASS_ON_ENFORCE = {**_BYPASS_ON, "ENTRA_SSO_ENFORCE": True}


@patch("api.views.delete_session", side_effect=_mock_delete_session)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class BypassEnforceIntegrationTests(TestCase):
    """POST /api/chat/ with bypass enabled and ENTRA_SSO_ENFORCE=True."""

    URL = "/api/chat/"

    @classmethod
    def setUpTestData(cls):
        Role.objects.get_or_create(name="CCO")
        Role.objects.get_or_create(name="JEFE_MAQUINISTAS")

    def setUp(self):
        self.client = APIClient()

    @override_settings(**_BYPASS_ON_ENFORCE)
    def test_email_in_map_returns_200(self, *_mocks):
        """Bypassed user with allowed role passes enforcement."""
        self.client.credentials(HTTP_X_BYPASS_EMAIL="ana@frmx.com")
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["role"], "CCO")

    @override_settings(**_BYPASS_ON_ENFORCE)
    def test_email_not_in_map_returns_401(self, *_mocks):
        """Unknown email → not authenticated → ENFORCE raises 401."""
        self.client.credentials(HTTP_X_BYPASS_EMAIL="unknown@frmx.com")
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 401)

    @override_settings(**_BYPASS_ON_ENFORCE)
    def test_no_header_returns_401(self, *_mocks):
        """No header → anonymous → ENFORCE raises 401."""
        resp = self.client.post(self.URL, {"question": "hola"}, format="json")
        self.assertEqual(resp.status_code, 401)


# ══════════════════════════════════════════════════════════════════════
#  Integration tests: DELETE /api/session/ with bypass
# ══════════════════════════════════════════════════════════════════════

@patch("api.views.delete_session", side_effect=_mock_delete_session)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class BypassSessionDeleteTests(TestCase):
    """DELETE /api/session/ works correctly with bypass authentication."""

    URL = "/api/session/"

    @classmethod
    def setUpTestData(cls):
        Role.objects.get_or_create(name="CCO")

    def setUp(self):
        self.client = APIClient()

    @override_settings(**_BYPASS_ON)
    def test_bypass_session_delete_returns_200(self, *_mocks):
        self.client.credentials(HTTP_X_BYPASS_EMAIL="ana@frmx.com")
        resp = self.client.delete(
            self.URL, {"session_id": "some-session"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)

    @override_settings(**_BYPASS_OFF)
    def test_bypass_off_session_delete_anon_no_enforce(self, *_mocks):
        """With bypass OFF and no enforcement, anonymous DELETE still works."""
        self.client.credentials(HTTP_X_BYPASS_EMAIL="ana@frmx.com")
        resp = self.client.delete(
            self.URL, {"session_id": "some-session"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
