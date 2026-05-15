from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, UserProfile

User = get_user_model()

# Respuesta mock reutilizable — misma estructura que agent_runner_mock.
MOCK_AGENT_RESPONSE = {
    "answer": "[TEST] respuesta mock",
    "decision": "mock",
    "orchestrator_reason": "test",
    "session_id": "ignored-will-be-overwritten",
    "last_db_table": None,
    "last_error": "",
    "rol": None,
}


def _mock_run_agent(question, session_id, user_context=None, **kwargs):
    return {**MOCK_AGENT_RESPONSE, "session_id": session_id}


def _mock_get_or_create_session(session_id=None):
    return session_id or "test-session-id"


@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create_session)
class ChatEndpointTests(TestCase):
    """Integration tests for POST /api/chat/ with user context."""

    @classmethod
    def setUpTestData(cls):
        cls.role_cco, _ = Role.objects.get_or_create(name="CCO")
        cls.role_op, _ = Role.objects.get_or_create(name="OPERADOR")

        cls.user_cco = User.objects.create_user(
            username="cco_user", email="cco@test.com", password="testpass123",
        )
        UserProfile.objects.create(user=cls.user_cco, role=cls.role_cco)

        cls.user_no_profile = User.objects.create_user(
            username="orphan", email="orphan@test.com", password="testpass123",
        )

    def setUp(self):
        self.client = APIClient()

    def test_anonymous_returns_role_anon(self, mock_session, mock_run):
        resp = self.client.post(
            "/api/chat/", {"question": "hola"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("answer", resp.data)
        self.assertIn("session_id", resp.data)
        self.assertEqual(resp.data["role"], "ANON")
        self.assertEqual(resp.data["scopes"], {"fleets": [], "regions": []})

    def test_authenticated_with_profile_returns_role(self, mock_session, mock_run):
        self.client.force_authenticate(user=self.user_cco)
        resp = self.client.post(
            "/api/chat/", {"question": "alertas"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["role"], "CCO")

    def test_authenticated_without_profile_returns_403(self, mock_session, mock_run):
        """SSO user without UserProfile (UNKNOWN role) gets 403."""
        self.client.force_authenticate(user=self.user_no_profile)
        resp = self.client.post(
            "/api/chat/", {"question": "alertas"}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_client_rol_is_ignored(self, mock_session, mock_run):
        """Enviar 'rol' en el body NO cambia response.role."""
        self.client.force_authenticate(user=self.user_cco)
        resp = self.client.post(
            "/api/chat/",
            {"question": "test", "rol": "OPERADOR"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        # role viene del perfil (CCO), no del body (OPERADOR)
        self.assertEqual(resp.data["role"], "CCO")

    def test_user_context_passed_to_run_agent(self, mock_session, mock_run):
        self.client.force_authenticate(user=self.user_cco)
        self.client.post(
            "/api/chat/", {"question": "test"}, format="json",
        )
        _, kwargs = mock_run.call_args
        self.assertIn("user_context", kwargs)
        self.assertEqual(kwargs["user_context"]["role"], "CCO")
        self.assertEqual(kwargs["user_context"]["user_id"], self.user_cco.pk)
