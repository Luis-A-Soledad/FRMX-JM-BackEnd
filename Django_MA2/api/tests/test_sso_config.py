"""Tests for GET /api/sso/config/ — public PKCE configuration endpoint."""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

_SSO_SETTINGS = {
    "ENTRA_TENANT_ID": "adb53b4f-b05f-4dcb-a2e1-9111380568c3",
    "ENTRA_AUTHORITY": "https://login.microsoftonline.com/adb53b4f-b05f-4dcb-a2e1-9111380568c3",
    "ENTRA_FRONTEND_CLIENT_ID": "fe-client-id-1234",
    "ENTRA_API_SCOPE": "api://aa51da3b-b8f7-41f5-bf03-c53aec9cc47c/api.access",
    "ENTRA_SSO_SCOPES": "openid profile offline_access api://aa51da3b-b8f7-41f5-bf03-c53aec9cc47c/api.access",
    "ENTRA_EXPECTED_AUDIENCE": "aa51da3b-b8f7-41f5-bf03-c53aec9cc47c",
}


@override_settings(**_SSO_SETTINGS)
class SSOConfigTests(TestCase):
    """Integration tests for the /api/sso/config/ endpoint."""

    URL = "/api/sso/config/"

    def setUp(self):
        self.client = APIClient()

    # ── 1. Public access returns expected fields ────────────

    def test_config_is_public_returns_expected_fields(self):
        """GET without auth must return 200 with all PKCE config fields."""
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data["tenant_id"], _SSO_SETTINGS["ENTRA_TENANT_ID"])
        self.assertEqual(data["authority"], _SSO_SETTINGS["ENTRA_AUTHORITY"])
        self.assertEqual(data["client_id"], _SSO_SETTINGS["ENTRA_FRONTEND_CLIENT_ID"])
        self.assertEqual(data["api_scope"], _SSO_SETTINGS["ENTRA_API_SCOPE"])
        self.assertEqual(data["expected_audience"], _SSO_SETTINGS["ENTRA_EXPECTED_AUDIENCE"])

        # scopes must be a list split from the space-separated string
        self.assertIsInstance(data["scopes"], list)
        self.assertEqual(len(data["scopes"]), 4)
        self.assertIn("openid", data["scopes"])

    # ── 2. No secrets leaked ────────────────────────────────

    def test_config_does_not_include_secrets(self):
        """Response must never contain client_secret or similar keys."""
        resp = self.client.get(self.URL)
        data = resp.json()

        forbidden_keys = {"client_secret", "secret", "password", "token"}
        self.assertTrue(
            forbidden_keys.isdisjoint(data.keys()),
            f"Response contains forbidden keys: {forbidden_keys & data.keys()}",
        )
