from django.db import migrations

ROLES = [
    {
        "name": "CCO",
        "description": "Centro de Control de Operaciones: supervisión global de la operación ferroviaria.",
    },
    {
        "name": "JEFE_MAQUINISTAS",
        "description": "Jefe de Maquinistas: gestión y seguimiento del desempeño de los maquinistas.",
    },
    {
        "name": "OPERADOR",
        "description": "Operador: consulta y monitoreo de alertas y calificaciones.",
    },
]


def seed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role_data in ROLES:
        Role.objects.get_or_create(
            name=role_data["name"],
            defaults={"description": role_data["description"]},
        )


def unseed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(name__in=[r["name"] for r in ROLES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_roles, unseed_roles),
    ]
