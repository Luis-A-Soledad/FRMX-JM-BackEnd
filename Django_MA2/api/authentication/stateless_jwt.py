from rest_framework_simplejwt.authentication import JWTAuthentication
from django.contrib.auth.models import AnonymousUser


class StatelessJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        """
        Evita acceso a base de datos.
        Construye un usuario directamente desde el token.
        """

        user = AnonymousUser()
        user.email = validated_token.get("email")
        user.name = validated_token.get("name")
        user.roles = validated_token.get("roles", [])

        return user