from django.conf import settings
from django.db import models


class Role(models.Model):
    """Roles de la aplicación. Definidos internamente (no vienen del SSO)."""

    class RoleChoices(models.TextChoices):
        CCO = "CCO", "Centro de Control de Operaciones"
        JEFE_MAQUINISTAS = "JEFE_MAQUINISTAS", "Jefe de Maquinistas"
        OPERADOR = "OPERADOR", "Operador"

    name = models.CharField(
        max_length=50,
        unique=True,
        choices=RoleChoices.choices,
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.get_name_display()


class UserProfile(models.Model):
    """Asocia un usuario de Django con un rol de la aplicación."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="users",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"{self.user.username} – {self.role.name}"
