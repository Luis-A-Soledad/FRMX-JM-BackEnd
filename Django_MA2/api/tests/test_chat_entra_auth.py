"""Tests: Entra Bearer tokens must be accepted on /api/chat/ and /api/session/.

Verifies the fix for the bug where SimpleJWT rejected Entra tokens with
"token_not_valid" because it tried to validate them before
EntraBearerAuthentication had a chance.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, UserProfile

User = get_user_model()

# ── Fake Entra claims ────────────────────────────────────────────────
FAKE_CLAIMS = {
    "oid": "00000000-aaaa-bbbb-cccc-222222222222",
    "tid": "adb53b4f-b05f-4dcb-a2e1-9111380568c3",
    "preferred_username": "chatuser@ferromex.com.mx",
    "scp": "api.access",
    "aud": "aa51da3b-b8f7-41f5-bf03-c53aec9cc47c",
    "iss": "https://login.microsoftonline.com/adb53b4f-b05f-4dcb-a2e1-9111380568c3/v2.0",
}

FAKE_DISCOVERY = {
    "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
    "issuer": FAKE_CLAIMS["iss"],
}

_ENTRA_SETTINGS = {
    "ENTRA_AUTH_ENABLED": True,
    "ENTRA_TENANT_ID": "adb53b4f-b05f-4dcb-a2e1-9111380568c3",
    "ENTRA_AUDIENCE": "aa51da3b-b8f7-41f5-bf03-c53aec9cc47c",
    "ENTRA_DISCOVERY_URL": None,
    "ENTRA_SSO_ENFORCE": False,
    "ENTRA_SSO_ALLOWED_ROLES": frozenset({"cco", "jefe_maquinistas"}),
}


# ── Mock agent helpers ────────────────────────────────────────────────

def _mock_run_agent(question, session_id, user_context=None, **kw):
    return {
        "answer": "[TEST] entra ok",
        "decision": "mock",
        "orchestrator_reason": "test",
        "session_id": session_id,
        "last_db_table": None,
        "last_error": "",
        "rol": None,
    }


def _mock_get_or_create(sid=None):
    return sid or "entra-test-session"


def _mock_delete_session(sid):
    return True


def _patch_entra_auth():
    """Context-manager stack that fakes Entra JWKS + jwt.decode."""
    mock_key = MagicMock()
    mock_key.key = "fake-rsa-key"
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key

    return (
        patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY),
        patch("api.authentication.entra._get_jwk_client", return_value=mock_client),
        patch("api.authentication.entra.jwt.decode", return_value=FAKE_CLAIMS),
    )


# ══════════════════════════════════════════════════════════════════════
#  /api/chat/ with valid Entra tokens
# ══════════════════════════════════════════════════════════════════════

@override_settings(**_ENTRA_SETTINGS)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class ChatEntraAuthTests(TestCase):
    """POST /api/chat/ must accept Entra Bearer tokens without 'token_not_valid'."""

    URL = "/api/chat/"

    @classmethod
    def setUpTestData(cls):
        cls.role_cco, _ = Role.objects.get_or_create(name="CCO")
        # Entra authenticator provisions users as "entra_<oid>"
        cls.user_cco = User.objects.create_user(
            username=f"entra_{FAKE_CLAIMS['oid']}"[:150],
            email="chatuser@ferromex.com.mx",
            password="!unused",
        )
        UserProfile.objects.create(user=cls.user_cco, role=cls.role_cco)

    def setUp(self):
        self.client = APIClient()

    def test_entra_token_does_not_trigger_token_not_valid(self, *_agent_mocks):
        """Core regression: Entra token must NOT be rejected by SimpleJWT."""
        p1, p2, p3 = _patch_entra_auth()
        with p1, p2, p3:
            resp = self.client.post(
                self.URL,
                {"question": "hola"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.fake.entra",
            )

        # Must NOT be 401 with "token_not_valid"
        self.assertNotEqual(resp.status_code, 401, resp.data)
        self.assertNotIn("token_not_valid", str(resp.data))

    def test_entra_token_allowed_role_gets_200(self, *_agent_mocks):
        """Entra user with CCO role -> 200."""
        p1, p2, p3 = _patch_entra_auth()
        with p1, p2, p3:
            resp = self.client.post(
                self.URL,
                {"question": "alertas"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.fake.entra",
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("answer", resp.data)
        self.assertEqual(resp.data["role"], "CCO")

    def test_entra_token_disallowed_role_gets_403(self, *_agent_mocks):
        """Entra user with OPERADOR role -> 403 (permission denied, NOT 401)."""
        role_op, _ = Role.objects.get_or_create(name="OPERADOR")

        op_claims = {**FAKE_CLAIMS, "oid": "00000000-aaaa-bbbb-cccc-333333333333",
                     "preferred_username": "opuser@ferromex.com.mx"}
        user_op = User.objects.create_user(
            username=f"entra_{op_claims['oid']}"[:150],
            email="opuser@ferromex.com.mx",
        )
        UserProfile.objects.create(user=user_op, role=role_op)

        p1, p2, _ = _patch_entra_auth()
        with p1, p2, patch("api.authentication.entra.jwt.decode", return_value=op_claims):
            resp = self.client.post(
                self.URL,
                {"question": "alertas"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.fake.entra",
            )

        self.assertEqual(resp.status_code, 403)


# ══════════════════════════════════════════════════════════════════════
#  /api/session/ with Entra tokens
# ══════════════════════════════════════════════════════════════════════

@override_settings(**_ENTRA_SETTINGS)
@patch("api.views.delete_session", side_effect=_mock_delete_session)
class SessionEntraAuthTests(TestCase):
    """DELETE /api/session/ must accept Entra Bearer tokens."""

    URL = "/api/session/"

    @classmethod
    def setUpTestData(cls):
        cls.role_cco, _ = Role.objects.get_or_create(name="CCO")
        sess_claims = {**FAKE_CLAIMS, "oid": "00000000-aaaa-bbbb-cccc-444444444444",
                       "preferred_username": "sessuser@ferromex.com.mx"}
        cls.sess_claims = sess_claims
        cls.user_cco = User.objects.create_user(
            username=f"entra_{sess_claims['oid']}"[:150],
            email="sessuser@ferromex.com.mx",
            password="!unused",
        )
        UserProfile.objects.create(user=cls.user_cco, role=cls.role_cco)

    def setUp(self):
        self.client = APIClient()

    def test_entra_token_not_rejected_by_simplejwt(self, *_mocks):
        """DELETE with Entra token must not return 'token_not_valid'."""
        p1, p2, _ = _patch_entra_auth()
        with p1, p2, patch("api.authentication.entra.jwt.decode", return_value=self.sess_claims):
            resp = self.client.delete(
                self.URL,
                {"session_id": "some-session"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.fake.entra",
            )

        self.assertNotEqual(resp.status_code, 401, resp.data)
        self.assertNotIn("token_not_valid", str(resp.data))


# ══════════════════════════════════════════════════════════════════════
#  Invalid Entra tokens must NOT produce "token_not_valid"
# ══════════════════════════════════════════════════════════════════════

@override_settings(**_ENTRA_SETTINGS)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class ChatInvalidEntraTokenTests(TestCase):
    """POST /api/chat/ with an INVALID Entra token must never say 'token_not_valid'."""

    URL = "/api/chat/"

    def setUp(self):
        self.client = APIClient()

    def test_expired_entra_token_returns_entra_error(self, *_mocks):
        """Expired Entra token -> 401 with Entra-specific message, not SimpleJWT."""
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with (
            patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY),
            patch("api.authentication.entra._get_jwk_client", return_value=mock_client),
            patch(
                "api.authentication.entra.jwt.decode",
                side_effect=__import__("jwt").ExpiredSignatureError("expired"),
            ),
        ):
            resp = self.client.post(
                self.URL,
                {"question": "hola"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.expired.entra",
            )

        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("token_not_valid", str(resp.data))
        self.assertIn("expired", str(resp.data).lower())

    def test_bad_signature_entra_token_returns_entra_error(self, *_mocks):
        """Invalid signature -> 401 from Entra authenticator, not SimpleJWT."""
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with (
            patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY),
            patch("api.authentication.entra._get_jwk_client", return_value=mock_client),
            patch(
                "api.authentication.entra.jwt.decode",
                side_effect=__import__("jwt").InvalidTokenError("bad sig"),
            ),
        ):
            resp = self.client.post(
                self.URL,
                {"question": "hola"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.badsig.entra",
            )

        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("token_not_valid", str(resp.data))

    def test_kid_not_in_entra_jwks_no_token_not_valid(self, *_mocks):
        """Token whose kid isn't in Entra JWKS must not produce 'token_not_valid'.

        EntraBearerAuthentication returns None -> with Entra-only auth list
        the request lands as unauthenticated (anon), not SimpleJWT 401.
        """
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.side_effect = (
            __import__("jwt").exceptions.InvalidTokenError("kid not found")
        )

        with (
            patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY),
            patch("api.authentication.entra._get_jwk_client", return_value=mock_client),
        ):
            resp = self.client.post(
                self.URL,
                {"question": "hola"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.unknown-kid.token",
            )

        # Must NOT contain "token_not_valid" from SimpleJWT
        self.assertNotIn("token_not_valid", str(resp.data))


# ══════════════════════════════════════════════════════════════════════
#  /api/sso/whoami/ still works (sanity check)
# ══════════════════════════════════════════════════════════════════════

@override_settings(**_ENTRA_SETTINGS)
class WhoAmIStillWorksTests(TestCase):
    """Ensure the fix doesn't break /api/sso/whoami/."""

    URL = "/api/sso/whoami/"

    def setUp(self):
        self.client = APIClient()

    def test_whoami_valid_entra_token_still_200(self):
        p1, p2, p3 = _patch_entra_auth()
        with p1, p2, p3:
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer eyJ.fake.entra",
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "AUTHENTICATED")
"""Tests: Entra Bearer tokens must be accepted on /api/chat/ and /api/session/.

Verifies the fix for the bug where SimpleJWT rejected Entra tokens with
"token_not_valid" because it tried to validate them before
EntraBearerAuthentication had a chance.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, UserProfile

User = get_user_model()

# ── Fake Entra claims ────────────────────────────────────────────────
FAKE_CLAIMS = {
    "oid": "00000000-aaaa-bbbb-cccc-222222222222",
    "tid": "adb53b4f-b05f-4dcb-a2e1-9111380568c3",
    "preferred_username": "chatuser@ferromex.com.mx",
    "scp": "api.access",
    "aud": "aa51da3b-b8f7-41f5-bf03-c53aec9cc47c",
    "iss": "https://login.microsoftonline.com/adb53b4f-b05f-4dcb-a2e1-9111380568c3/v2.0",
}

FAKE_DISCOVERY = {
    "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
    "issuer": FAKE_CLAIMS["iss"],
}

_ENTRA_SETTINGS = {
    "ENTRA_AUTH_ENABLED": True,
    "ENTRA_TENANT_ID": "adb53b4f-b05f-4dcb-a2e1-9111380568c3",
    "ENTRA_AUDIENCE": "aa51da3b-b8f7-41f5-bf03-c53aec9cc47c",
    "ENTRA_DISCOVERY_URL": None,
    "ENTRA_SSO_ENFORCE": False,
    "ENTRA_SSO_ALLOWED_ROLES": frozenset({"cco", "jefe_maquinistas"}),
}


# ── Mock agent helpers ────────────────────────────────────────────────

def _mock_run_agent(question, session_id, user_context=None, **kw):
    return {
        "answer": "[TEST] entra ok",
        "decision": "mock",
        "orchestrator_reason": "test",
        "session_id": session_id,
        "last_db_table": None,
        "last_error": "",
        "rol": None,
    }


def _mock_get_or_create(sid=None):
    return sid or "entra-test-session"


def _mock_delete_session(sid):
    return True


def _patch_entra_auth():
    """Context-manager stack that fakes Entra JWKS + jwt.decode."""
    mock_key = MagicMock()
    mock_key.key = "fake-rsa-key"
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key

    return (
        patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY),
        patch("api.authentication.entra._get_jwk_client", return_value=mock_client),
        patch("api.authentication.entra.jwt.decode", return_value=FAKE_CLAIMS),
    )


# ══════════════════════════════════════════════════════════════════════
#  /api/chat/ with Entra tokens
# ══════════════════════════════════════════════════════════════════════

@override_settings(**_ENTRA_SETTINGS)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class ChatEntraAuthTests(TestCase):
    """POST /api/chat/ must accept Entra Bearer tokens without 'token_not_valid'."""

    URL = "/api/chat/"

    @classmethod
    def setUpTestData(cls):
        cls.role_cco, _ = Role.objects.get_or_create(name="CCO")
        # Entra authenticator provisions users as "entra_<oid>"
        cls.user_cco = User.objects.create_user(
            username=f"entra_{FAKE_CLAIMS['oid']}"[:150],
            email="chatuser@ferromex.com.mx",
            password="!unused",
        )
        UserProfile.objects.create(user=cls.user_cco, role=cls.role_cco)

    def setUp(self):
        self.client = APIClient()

    def test_entra_token_does_not_trigger_token_not_valid(self, *_agent_mocks):
        """Core regression: Entra token must NOT be rejected by SimpleJWT."""
        p1, p2, p3 = _patch_entra_auth()
        with p1, p2, p3:
            resp = self.client.post(
                self.URL,
                {"question": "hola"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.fake.entra",
            )

        # Must NOT be 401 with "token_not_valid"
        self.assertNotEqual(resp.status_code, 401, resp.data)
        self.assertNotIn("token_not_valid", str(resp.data))

    def test_entra_token_allowed_role_gets_200(self, *_agent_mocks):
        """Entra user with CCO role → 200."""
        p1, p2, p3 = _patch_entra_auth()
        with p1, p2, p3:
            resp = self.client.post(
                self.URL,
                {"question": "alertas"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.fake.entra",
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("answer", resp.data)
        self.assertEqual(resp.data["role"], "CCO")

    def test_entra_token_disallowed_role_gets_403(self, *_agent_mocks):
        """Entra user with OPERADOR role → 403 (permission denied, NOT 401)."""
        role_op, _ = Role.objects.get_or_create(name="OPERADOR")

        op_claims = {**FAKE_CLAIMS, "oid": "00000000-aaaa-bbbb-cccc-333333333333",
                     "preferred_username": "opuser@ferromex.com.mx"}
        user_op = User.objects.create_user(
            username=f"entra_{op_claims['oid']}"[:150],
            email="opuser@ferromex.com.mx",
        )
        UserProfile.objects.create(user=user_op, role=role_op)

        p1, p2, _ = _patch_entra_auth()
        with p1, p2, patch("api.authentication.entra.jwt.decode", return_value=op_claims):
            resp = self.client.post(
                self.URL,
                {"question": "alertas"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.fake.entra",
            )

        self.assertEqual(resp.status_code, 403)


# ══════════════════════════════════════════════════════════════════════
#  /api/session/ with Entra tokens
# ══════════════════════════════════════════════════════════════════════

@override_settings(**_ENTRA_SETTINGS)
@patch("api.views.delete_session", side_effect=_mock_delete_session)
class SessionEntraAuthTests(TestCase):
    """DELETE /api/session/ must accept Entra Bearer tokens."""

    URL = "/api/session/"

    @classmethod
    def setUpTestData(cls):
        cls.role_cco, _ = Role.objects.get_or_create(name="CCO")
        sess_claims = {**FAKE_CLAIMS, "oid": "00000000-aaaa-bbbb-cccc-444444444444",
                       "preferred_username": "sessuser@ferromex.com.mx"}
        cls.sess_claims = sess_claims
        cls.user_cco = User.objects.create_user(
            username=f"entra_{sess_claims['oid']}"[:150],
            email="sessuser@ferromex.com.mx",
            password="!unused",
        )
        UserProfile.objects.create(user=cls.user_cco, role=cls.role_cco)

    def setUp(self):
        self.client = APIClient()

    def test_entra_token_not_rejected_by_simplejwt(self, *_mocks):
        """DELETE with Entra token must not return 'token_not_valid'."""
        p1, p2, _ = _patch_entra_auth()
        with p1, p2, patch("api.authentication.entra.jwt.decode", return_value=self.sess_claims):
            resp = self.client.delete(
                self.URL,
                {"session_id": "some-session"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.fake.entra",
            )

        self.assertNotEqual(resp.status_code, 401, resp.data)
        self.assertNotIn("token_not_valid", str(resp.data))


# ══════════════════════════════════════════════════════════════════════
#  Invalid Entra tokens must NOT produce "token_not_valid"
# ══════════════════════════════════════════════════════════════════════

@override_settings(**_ENTRA_SETTINGS)
@patch("api.views.run_agent", side_effect=_mock_run_agent)
@patch("api.views.get_or_create_session", side_effect=_mock_get_or_create)
class ChatInvalidEntraTokenTests(TestCase):
    """POST /api/chat/ with an INVALID Entra token must never say 'token_not_valid'."""

    URL = "/api/chat/"

    def setUp(self):
        self.client = APIClient()

    def test_expired_entra_token_returns_entra_error(self, *_mocks):
        """Expired Entra token → 401 with Entra-specific message, not SimpleJWT."""
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with (
            patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY),
            patch("api.authentication.entra._get_jwk_client", return_value=mock_client),
            patch(
                "api.authentication.entra.jwt.decode",
                side_effect=__import__("jwt").ExpiredSignatureError("expired"),
            ),
        ):
            resp = self.client.post(
                self.URL,
                {"question": "hola"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.expired.entra",
            )

        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("token_not_valid", str(resp.data))
        self.assertIn("expired", str(resp.data).lower())

    def test_bad_signature_entra_token_returns_entra_error(self, *_mocks):
        """Invalid signature → 401 from Entra authenticator, not SimpleJWT."""
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        with (
            patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY),
            patch("api.authentication.entra._get_jwk_client", return_value=mock_client),
            patch(
                "api.authentication.entra.jwt.decode",
                side_effect=__import__("jwt").InvalidTokenError("bad sig"),
            ),
        ):
            resp = self.client.post(
                self.URL,
                {"question": "hola"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.badsig.entra",
            )

        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("token_not_valid", str(resp.data))

    def test_kid_not_in_entra_jwks_no_token_not_valid(self, *_mocks):
        """Token whose kid isn't in Entra JWKS must not produce 'token_not_valid'.

        EntraBearerAuthentication returns None → with Entra-only auth list
        the request lands as unauthenticated (anon), not SimpleJWT 401.
        """
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.side_effect = (
            __import__("jwt").exceptions.InvalidTokenError("kid not found")
        )

        with (
            patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY),
            patch("api.authentication.entra._get_jwk_client", return_value=mock_client),
        ):
            resp = self.client.post(
                self.URL,
                {"question": "hola"},
                format="json",
                HTTP_AUTHORIZATION="Bearer eyJ.unknown-kid.token",
            )

        # Must NOT contain "token_not_valid" from SimpleJWT
        self.assertNotIn("token_not_valid", str(resp.data))


# ══════════════════════════════════════════════════════════════════════
#  /api/sso/whoami/ still works (sanity check)
# ══════════════════════════════════════════════════════════════════════

@override_settings(**_ENTRA_SETTINGS)
class WhoAmIStillWorksTests(TestCase):
    """Ensure the fix doesn't break /api/sso/whoami/."""

    URL = "/api/sso/whoami/"

    def setUp(self):
        self.client = APIClient()

    def test_whoami_valid_entra_token_still_200(self):
        p1, p2, p3 = _patch_entra_auth()
        with p1, p2, p3:
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer eyJ.fake.entra",
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "AUTHENTICATED")
