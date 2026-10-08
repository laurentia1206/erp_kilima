# Rôles autorisés à exécuter les décaissements : paramétrables (les codes de
# rôles varient selon les installations — le figé en dur bloquait les caissiers).
import uuid

from django.db import migrations

CLES = (
    ("decaissement.roles_caisse", "CAISSIER_CENTRAL,CAISSIER_VENDEUR",
     "Rôles autorisés à décaisser en espèces (codes séparés par des virgules)"),
    ("decaissement.roles_banque", "COMPTABLE,DFI",
     "Rôles autorisés à décaisser par banque (codes séparés par des virgules)"),
)


def seed(apps, schema_editor):
    Parametre = apps.get_model("core", "Parametre")
    for cle, valeur, description in CLES:
        if not Parametre.objects.filter(cle=cle, societe__isnull=True).exists():
            Parametre.objects.create(id=uuid.uuid4(), societe=None, cle=cle,
                                     valeur=valeur, type_valeur="string",
                                     description=description)


def unseed(apps, schema_editor):
    Parametre = apps.get_model("core", "Parametre")
    Parametre.objects.filter(cle__in=[c for c, _, _ in CLES],
                             societe__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0025_audit_permissions")]
    operations = [migrations.RunPython(seed, unseed)]
