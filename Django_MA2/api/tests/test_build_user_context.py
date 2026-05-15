from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from accounts.models import Role, UserProfile
from accounts.utils import ROLE_ANON, ROLE_UNKNOWN, build_user_context

User = get_user_model()


class BuildUserContextTests(TestCase):
    """Unit tests for accounts.utils.build_user_context."""

    @classmethod
    def setUpTestData(cls):
        cls.role_cco, _ = Role.objects.get_or_create(name="CCO")
        cls.user_with_profile = User.objects.create_user(
            username="cco_user", email="cco@test.com", password="testpass123",
        )
        UserProfile.objects.create(user=cls.user_with_profile, role=cls.role_cco)

        cls.user_no_profile = User.objects.create_user(
            username="orphan_user", email="orphan@test.com", password="testpass123",
        )

    def test_authenticated_with_profile_returns_role(self):
        ctx = build_user_context(self.user_with_profile)
        self.assertEqual(ctx["user_id"], self.user_with_profile.pk)
        self.assertEqual(ctx["email"], "cco@test.com")
        self.assertEqual(ctx["role"], "CCO")
        self.assertEqual(ctx["scopes"], {"fleets": [], "regions": []})

    def test_authenticated_without_profile_returns_unknown(self):
        ctx = build_user_context(self.user_no_profile)
        self.assertEqual(ctx["user_id"], self.user_no_profile.pk)
        self.assertEqual(ctx["role"], ROLE_UNKNOWN)
        self.assertEqual(ctx["scopes"], {"fleets": [], "regions": []})

    def test_anonymous_user_returns_anon(self):
        ctx = build_user_context(AnonymousUser())
        self.assertIsNone(ctx["user_id"])
        self.assertIsNone(ctx["email"])
        self.assertEqual(ctx["role"], ROLE_ANON)
        self.assertEqual(ctx["scopes"], {"fleets": [], "regions": []})

    def test_email_fallback_to_username(self):
        user = User.objects.create_user(
            username="no_email_user", email="", password="testpass123",
        )
        ctx = build_user_context(user)
        self.assertEqual(ctx["email"], "no_email_user")
        self.assertEqual(ctx["role"], ROLE_UNKNOWN)  # no profile

    def test_scopes_are_independent_instances(self):
        ctx1 = build_user_context(AnonymousUser())
        ctx2 = build_user_context(AnonymousUser())
        self.assertIsNot(ctx1["scopes"], ctx2["scopes"])
