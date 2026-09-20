# Rôle RECEPTIONNISTE : réception hôtel (module Hôtellerie GHR).
import uuid

from django.db import migrations


def creer_role(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    if not Role.objects.filter(code="RECEPTIONNISTE").exists():
        Role.objects.create(id=uuid.uuid4(), code="RECEPTIONNISTE",
                            libelle="Réceptionniste", niveau=0, herite_de=None)


def supprimer_role(apps, schema_editor):
    apps.get_model("core", "Role").objects.filter(code="RECEPTIONNISTE").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0007_chambre_sejour_lignesejour")]
    operations = [migrations.RunPython(creer_role, supprimer_role)]
