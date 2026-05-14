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
        self.assertTrue(data["username"].startswith("entra_"))
        self.assertEqual(data["email"], "tester@ferromex.com.mx")
        self.assertEqual(data["oid"], FAKE_CLAIMS["oid"])
        self.assertEqual(data["tid"], FAKE_CLAIMS["tid"])
        self.assertEqual(data["aud"], FAKE_CLAIMS["aud"])
        self.assertEqual(data["iss"], FAKE_CLAIMS["iss"])
        self.assertEqual(data["scp"], "api.access")
        # User has no UserProfile → role falls back to UNKNOWN
        self.assertEqual(data["role"], "UNKNOWN")
        self.assertEqual(data["scopes"], {"fleets": [], "regions": []})
