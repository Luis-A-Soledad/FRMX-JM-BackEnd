from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication


class _StatelessUser(AnonymousUser):
    def __init__(
        self,
        *,
        email=None,
        name=None,
        role=None,
        roles=None,
        capabilities=None,
        scopes=None,
    ):
        super().__init__()
        self.email = email
        self.name = name
        self.role = role
        self.roles = roles or []
        self.capabilities = capabilities or []
        self.scopes = scopes or {}
        self.pk = email or None
        self.username = email or ""

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_username(self):
        return self.username


class StatelessJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        """Build a lightweight authenticated user from the backend JWT payload."""

        return _StatelessUser(
            email=validated_token.get("email"),
            name=validated_token.get("name"),
            role=validated_token.get("role"),
            roles=(
                validated_token.get("roles")
                or ([validated_token.get("role")] if validated_token.get("role") else [])
            ),
            capabilities=validated_token.get("capabilities") or [],
            scopes=validated_token.get("scopes") or {},
        )