"""Tests for GET /api/sso/whoami/ — Entra SSO evidence endpoint.

All tests mock the Entra JWKS / jwt.decode layer so no real tokens or
network calls are needed.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

# Claims that simulate a valid Entra access token
FAKE_CLAIMS = {
    "oid": "00000000-aaaa-bbbb-cccc-111111111111",
    "tid": "adb53b4f-b05f-4dcb-a2e1-9111380568c3",
    "preferred_username": "tester@ferromex.com.mx",
    "scp": "api.access",
    "aud": "aa51da3b-b8f7-41f5-bf03-c53aec9cc47c",
    "iss": "https://login.microsoftonline.com/adb53b4f-b05f-4dcb-a2e1-9111380568c3/v2.0",
    "name": "Tester User",
}

FAKE_DISCOVERY = {
    "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
    "issuer": FAKE_CLAIMS["iss"],
}

# Overrides to ensure Entra settings are present during tests
_ENTRA_SETTINGS = {
    "ENTRA_TENANT_ID": "adb53b4f-b05f-4dcb-a2e1-9111380568c3",
    "ENTRA_AUDIENCE": "aa51da3b-b8f7-41f5-bf03-c53aec9cc47c",
    "ENTRA_DISCOVERY_URL": None,
}


@override_settings(**_ENTRA_SETTINGS)
class WhoAmISSOTests(TestCase):
    """Integration tests for the /api/sso/whoami/ endpoint."""

    URL = "/api/sso/whoami/"


    def setUp(self):
        self.client = APIClient()

    # ── 1. No token → 401 ───────────────────────────────────

    def test_whoami_no_token_returns_401(self):
        """Request without Authorization header must be rejected."""
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 401)

    # ── 2. Invalid token → 401 ──────────────────────────────

    @patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("api.authentication.entra._get_jwk_client")
    def test_whoami_invalid_token_returns_401(self, mock_jwk_factory, mock_disc):
        """A token that Entra recognises (kid found) but fails decode → 401."""
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key
        mock_jwk_factory.return_value = mock_client

        with patch("api.authentication.entra.jwt.decode") as mock_decode:
            mock_decode.side_effect = __import__("jwt").exceptions.InvalidTokenError(
                "bad signature"
            )
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer some.invalid.token",
            )

        self.assertEqual(resp.status_code, 401)

    # ── 3. Valid token → 200 + full JSON ────────────────────

    @patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("api.authentication.entra._get_jwk_client")
    def test_whoami_valid_token_returns_200(self, mock_jwk_factory, mock_disc):
        """Simulated valid Entra token → 200 with expected JSON shape."""
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key
        mock_jwk_factory.return_value = mock_client

        with patch("api.authentication.entra.jwt.decode") as mock_decode:
            mock_decode.return_value = FAKE_CLAIMS
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer eyJ.valid.token",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "AUTHENTICATED")
        self.assertEqual(data["email"], "tester@ferromex.com.mx")
        self.assertEqual(data["oid"], FAKE_CLAIMS["oid"])
        self.assertEqual(data["name"], "Tester User")
        self.assertEqual(data["scp"], ["api.access"])
        self.assertNotIn("roles", data)
        self.assertNotIn("access_level", data)
        self.assertEqual(data["capabilities"], ["VIEW_BASIC"])
        self.assertTrue(data["allowed"])
        # User has no UserProfile → role falls back to UNKNOWN
        self.assertEqual(data["role"], "UNKNOWN")
        self.assertEqual(data["scopes"], {"fleets": [], "regions": []})

    @patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("api.authentication.entra._get_jwk_client")
    def test_whoami_valid_v1_issuer_token_returns_200(self, mock_jwk_factory, mock_disc):
        """v1 Entra issuer (sts.windows.net) must be accepted for same tenant."""
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key
        mock_jwk_factory.return_value = mock_client

        v1_claims = {
            **FAKE_CLAIMS,
            "iss": "https://sts.windows.net/adb53b4f-b05f-4dcb-a2e1-9111380568c3/",
            "ver": "1.0",
        }

        with patch("api.authentication.entra.jwt.decode") as mock_decode:
            mock_decode.return_value = v1_claims
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer eyJ.valid.v1token",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "AUTHENTICATED")

    @patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("api.authentication.entra._get_jwk_client")
    def test_whoami_valid_v2_issuer_with_trailing_slash_returns_200(self, mock_jwk_factory, mock_disc):
        """v2 issuer with trailing slash must be accepted."""
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key
        mock_jwk_factory.return_value = mock_client

        v2_claims_slash = {
            **FAKE_CLAIMS,
            "iss": "https://login.microsoftonline.com/adb53b4f-b05f-4dcb-a2e1-9111380568c3/v2.0/",
            "ver": "2.0",
        }

        with patch("api.authentication.entra.jwt.decode") as mock_decode:
            mock_decode.return_value = v2_claims_slash
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer eyJ.valid.v2slash",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "AUTHENTICATED")

    @patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("api.authentication.entra._get_jwk_client")
    def test_whoami_cco_claim_role_returns_level_2(self, mock_jwk_factory, mock_disc):
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key
        mock_jwk_factory.return_value = mock_client

        claims = {**FAKE_CLAIMS, "roles": ["CCO"]}
        with patch("api.authentication.entra.jwt.decode") as mock_decode:
            mock_decode.return_value = claims
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer eyJ.valid.cco",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn("roles", data)
        self.assertNotIn("access_level", data)
        self.assertEqual(data["capabilities"], ["*"])
        self.assertEqual(data["role"], "CCO")
        self.assertTrue(data["allowed"])

    @patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("api.authentication.entra._get_jwk_client")
    def test_whoami_jefe_role_returns_level_1(self, mock_jwk_factory, mock_disc):
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key
        mock_jwk_factory.return_value = mock_client

        claims = {**FAKE_CLAIMS, "roles": ["JEFE_MAQUINISTAS"]}
        with patch("api.authentication.entra.jwt.decode") as mock_decode:
            mock_decode.return_value = claims
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer eyJ.valid.jefe",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn("access_level", data)
        self.assertEqual(data["capabilities"], ["VIEW_*", "EDIT_SCHEDULE", "QUERY_ALERTS"])
        self.assertEqual(data["role"], "JEFE_MAQUINISTAS")

    @patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("api.authentication.entra._get_jwk_client")
    def test_whoami_role_precedence_cco_wins(self, mock_jwk_factory, mock_disc):
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key
        mock_jwk_factory.return_value = mock_client

        claims = {**FAKE_CLAIMS, "roles": ["JEFE_MAQUINISTAS", "CCO"]}
        with patch("api.authentication.entra.jwt.decode") as mock_decode:
            mock_decode.return_value = claims
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer eyJ.valid.multirole",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn("access_level", data)
        self.assertEqual(data["role"], "CCO")

    @patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("api.authentication.entra._get_jwk_client")
    @override_settings(ENTRA_REQUIRED_SCOPE="Api.access")
    def test_whoami_missing_required_scope_sets_allowed_false(self, mock_jwk_factory, mock_disc):
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key
        mock_jwk_factory.return_value = mock_client

        claims = {**FAKE_CLAIMS, "scp": "profile openid", "roles": ["CCO"]}
        with patch("api.authentication.entra.jwt.decode") as mock_decode:
            mock_decode.return_value = claims
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer eyJ.valid.missingscope",
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["allowed"])

    @patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("api.authentication.entra._get_jwk_client")
    def test_whoami_invalid_audience_returns_401(self, mock_jwk_factory, mock_disc):
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key
        mock_jwk_factory.return_value = mock_client

        with patch("api.authentication.entra.jwt.decode") as mock_decode:
            mock_decode.side_effect = __import__("jwt").InvalidAudienceError("wrong aud")
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer some.wrong.aud",
            )

        self.assertEqual(resp.status_code, 401)

    @patch("api.authentication.entra._get_discovery", return_value=FAKE_DISCOVERY)
    @patch("api.authentication.entra._get_jwk_client")
    def test_whoami_expired_token_returns_401(self, mock_jwk_factory, mock_disc):
        mock_key = MagicMock()
        mock_key.key = "fake-rsa-key"
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_key
        mock_jwk_factory.return_value = mock_client

        with patch("api.authentication.entra.jwt.decode") as mock_decode:
            mock_decode.side_effect = __import__("jwt").ExpiredSignatureError("expired")
            resp = self.client.get(
                self.URL,
                HTTP_AUTHORIZATION="Bearer some.expired.token",
            )

        self.assertEqual(resp.status_code, 401)


