"""Tests for POST /api/sso/token/ — authorization_code + PKCE exchange."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient


_SSO_SETTINGS = {
    "ENTRA_TENANT_ID": "adb53b4f-b05f-4dcb-a2e1-9111380568c3",
    "ENTRA_AUTHORITY": "https://login.microsoftonline.com/adb53b4f-b05f-4dcb-a2e1-9111380568c3",
    "ENTRA_FRONTEND_CLIENT_ID": "frontend-client-id-123",
    "ENTRA_SSO_SCOPES": "openid profile offline_access api://aa51da3b-b8f7-41f5-bf03-c53aec9cc47c/api.access",
}


@override_settings(**_SSO_SETTINGS)
class SSOTokenExchangeTests(TestCase):
    URL = "/api/sso/token/"

    def setUp(self):
        self.client = APIClient()

    @patch("api.views.http_requests.post")
    def test_exchange_success_returns_upstream_token_payload(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "token_type": "Bearer",
            "scope": "api.access",
            "expires_in": 3600,
            "access_token": "access-token-value",
            "refresh_token": "refresh-token-value",
            "id_token": "id-token-value",
        }

        body = {
            "code": "auth-code-123",
            "code_verifier": "verifier-123",
            "redirect_uri": "http://localhost:3000/auth/callback",
        }
        resp = self.client.post(self.URL, body, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["access_token"], "access-token-value")

        args, kwargs = mock_post.call_args
        self.assertEqual(
            args[0],
            "https://login.microsoftonline.com/adb53b4f-b05f-4dcb-a2e1-9111380568c3/oauth2/v2.0/token",
        )
        self.assertEqual(kwargs["data"]["grant_type"], "authorization_code")
        self.assertEqual(kwargs["data"]["client_id"], "frontend-client-id-123")
        self.assertEqual(kwargs["data"]["code"], "auth-code-123")
        self.assertEqual(kwargs["data"]["code_verifier"], "verifier-123")
        self.assertEqual(kwargs["data"]["redirect_uri"], "http://localhost:3000/auth/callback")
        self.assertIn("scope", kwargs["data"])

    def test_exchange_missing_required_fields_returns_400(self):
        resp = self.client.post(
            self.URL,
            {
                "code": "only-code",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertIn("code_verifier", data)
        self.assertIn("redirect_uri", data)

    @patch("api.views.http_requests.post")
    def test_exchange_invalid_code_bubbles_upstream_error(self, mock_post):
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {
            "error": "invalid_grant",
            "error_description": "AADSTS70000: bad authorization code",
        }

        resp = self.client.post(
            self.URL,
            {
                "code": "invalid-auth-code",
                "code_verifier": "verifier-123",
                "redirect_uri": "http://localhost:3000/auth/callback",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data["detail"], "Entra token exchange failed.")
        self.assertEqual(data["entra_error"]["error"], "invalid_grant")
