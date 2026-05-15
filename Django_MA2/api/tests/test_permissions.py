"""Tests for role_config.py — permission model security.

Validates that the least-privilege fallback works correctly:
- UNKNOWN / unmapped roles must NOT get full access.
- ANON permissions are the safety net for any unrecognised role.
- Existing roles (cco, jefe_maquinistas, otro) keep their defined permissions.
- Only CCO and JEFE_MAQUINISTAS are allowed to use the system via SSO.

All tests are deterministic and require no external tokens or services.
"""

from django.test import TestCase

from role_config import (
    ALLOWED_SSO_ROLES,
    PERMISSIONS,
    has_permission,
    get_allowed_agents,
    get_denied_message,
    is_sso_role_allowed,
    DEFAULT_DENIED_MESSAGE,
)


class TestPermissionsFallback(TestCase):
    """Unknown / unmapped roles must fall back to ANON (least privilege)."""

    def test_unknown_role_gets_anon_permissions(self):
        """role='UNKNOWN' must receive exactly the same agents as ANON."""
        self.assertEqual(
            get_allowed_agents("UNKNOWN"),
            PERMISSIONS["ANON"],
        )

    def test_unknown_role_cannot_access_db(self):
        self.assertFalse(has_permission("UNKNOWN", "db"))

    def test_unknown_role_cannot_access_rag(self):
        self.assertFalse(has_permission("UNKNOWN", "rag"))

    def test_unknown_role_cannot_access_calificador(self):
        self.assertFalse(has_permission("UNKNOWN", "calificador"))

    def test_unknown_role_cannot_access_summary(self):
        self.assertFalse(has_permission("UNKNOWN", "summary"))

    def test_unknown_role_can_access_general(self):
        """ANON (and therefore UNKNOWN) may still use the general agent."""
        self.assertTrue(has_permission("UNKNOWN", "general"))

    def test_completely_invented_role_uses_anon(self):
        """A role that doesn't exist at all also falls back to ANON."""
        self.assertEqual(
            get_allowed_agents("DOES_NOT_EXIST"),
            PERMISSIONS["ANON"],
        )

    def test_invented_role_denied_sensitive_agents(self):
        for agent in ("db", "rag", "calificador", "summary"):
            self.assertFalse(
                has_permission("DOES_NOT_EXIST", agent),
                f"Unmapped role should NOT access '{agent}'",
            )


class TestAnonPermissions(TestCase):
    """ANON role should only allow 'general'."""

    def test_anon_in_permissions(self):
        self.assertIn("ANON", PERMISSIONS)

    def test_anon_allowed_agents(self):
        self.assertEqual(PERMISSIONS["ANON"], ["general"])

    def test_anon_can_access_general(self):
        self.assertTrue(has_permission("ANON", "general"))

    def test_anon_cannot_access_db(self):
        self.assertFalse(has_permission("ANON", "db"))

    def test_anon_cannot_access_calificador(self):
        self.assertFalse(has_permission("ANON", "calificador"))


class TestExistingRolesUnchanged(TestCase):
    """Existing roles must keep their original permissions."""

    def test_cco_has_full_access(self):
        expected = {"db", "rag", "calificador", "summary", "general"}
        self.assertEqual(set(get_allowed_agents("cco")), expected)

    def test_cco_can_access_calificador(self):
        self.assertTrue(has_permission("cco", "calificador"))

    def test_jefe_maquinistas_has_limited_access(self):
        expected = {"rag", "db", "general"}
        self.assertEqual(set(get_allowed_agents("jefe_maquinistas")), expected)

    def test_jefe_maquinistas_cannot_access_calificador(self):
        self.assertFalse(has_permission("jefe_maquinistas", "calificador"))


class TestDeniedMessages(TestCase):
    """Denied message helpers should return correct strings."""

    def test_known_agent_message(self):
        msg = get_denied_message("db")
        self.assertIn("base de datos", msg)

    def test_unknown_agent_message(self):
        msg = get_denied_message("nonexistent_agent")
        self.assertEqual(msg, DEFAULT_DENIED_MESSAGE)


class TestSSOAllowedRoles(TestCase):
    """Only CCO and JEFE_MAQUINISTAS are authorized via SSO."""

    def test_cco_allowed(self):
        self.assertTrue(is_sso_role_allowed("CCO"))

    def test_cco_lowercase_allowed(self):
        self.assertTrue(is_sso_role_allowed("cco"))

    def test_jefe_maquinistas_allowed(self):
        self.assertTrue(is_sso_role_allowed("JEFE_MAQUINISTAS"))

    def test_jefe_maquinistas_lowercase_allowed(self):
        self.assertTrue(is_sso_role_allowed("jefe_maquinistas"))

    def test_unknown_denied(self):
        self.assertFalse(is_sso_role_allowed("UNKNOWN"))

    def test_anon_denied(self):
        """ANON is for unauthenticated users — not an SSO role."""
        self.assertFalse(is_sso_role_allowed("ANON"))

    def test_operador_denied(self):
        self.assertFalse(is_sso_role_allowed("OPERADOR"))

    def test_empty_string_denied(self):
        self.assertFalse(is_sso_role_allowed(""))

    def test_random_role_denied(self):
        self.assertFalse(is_sso_role_allowed("HACKER"))
