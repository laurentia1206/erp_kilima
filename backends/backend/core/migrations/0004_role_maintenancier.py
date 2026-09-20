# Rôle MAINTENANCIER : le métier maintenance est séparé du dispatching.
import uuid

from django.db import migrations


def creer_role(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    if not Role.objects.filter(code="MAINTENANCIER").exists():
        Role.objects.create(id=uuid.uuid4(), code="MAINTENANCIER",
                            libelle="Maintenancier", niveau=0, herite_de=None)


def supprimer_role(apps, schema_editor):
    apps.get_model("core", "Role").objects.filter(code="MAINTENANCIER").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0003_planentretien_interventioncamion_plan_id")]
    operations = [migrations.RunPython(creer_role, supprimer_role)]
