# Le DFI peut exécuter les décaissements par caisse : il a déjà accès au
# module caisse (ouverture, mouvements, clôture) mais le paramètre semé par
# 0026 l'excluait de l'exécution des ordres de dépense en espèces — le
# circuit réquisition validée → sortie de caisse restait bloqué pour lui.
# On ajoute DFI aux paramètres encore à la valeur d'origine (les valeurs
# personnalisées par une société ne sont pas touchées).
from django.db import migrations

ANCIEN = "CAISSIER_CENTRAL,CAISSIER_VENDEUR"
NOUVEAU = "CAISSIER_CENTRAL,CAISSIER_VENDEUR,DFI"


def ajouter_dfi(apps, schema_editor):
    Parametre = apps.get_model("core", "Parametre")
    Parametre.objects.filter(cle="decaissement.roles_caisse",
                             valeur=ANCIEN).update(valeur=NOUVEAU)


def retirer_dfi(apps, schema_editor):
    Parametre = apps.get_model("core", "Parametre")
    Parametre.objects.filter(cle="decaissement.roles_caisse",
                             valeur=NOUVEAU).update(valeur=ANCIEN)


class Migration(migrations.Migration):
    dependencies = [("core", "0036_audit_chambre_housekeeping")]
    operations = [migrations.RunPython(ajouter_dfi, retirer_dfi)]
