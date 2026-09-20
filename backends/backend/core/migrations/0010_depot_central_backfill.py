# Reprise : un dépôt CENTRAL par société, qui reçoit tout le stock existant
# (invariant : Article.stock_qte/valeur = somme des dépôts de la société).
import uuid

from django.db import migrations


def creer_centraux(apps, schema_editor):
    Societe = apps.get_model("core", "Societe")
    Depot = apps.get_model("core", "Depot")
    StockDepot = apps.get_model("core", "StockDepot")
    Article = apps.get_model("core", "Article")
    for s in Societe.objects.all():
        depot = Depot.objects.filter(societe_id=s.id, type="central").first()
        if not depot:
            depot = Depot.objects.create(id=uuid.uuid4(), societe_id=s.id,
                                         code="CENTRAL",
                                         libelle="Dépôt central",
                                         type="central", actif=True)
        for art in Article.objects.filter(societe_id=s.id, gere_stock=True):
            if float(art.stock_qte or 0) == 0 and float(art.stock_valeur or 0) == 0:
                continue
            if not StockDepot.objects.filter(depot_id=depot.id,
                                             article_id=art.id).exists():
                StockDepot.objects.create(id=uuid.uuid4(), depot_id=depot.id,
                                          article_id=art.id,
                                          qte=art.stock_qte,
                                          valeur=art.stock_valeur)


def supprimer(apps, schema_editor):
    apps.get_model("core", "StockDepot").objects.all().delete()
    apps.get_model("core", "Depot").objects.filter(type="central").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0009_depots_stock")]
    operations = [migrations.RunPython(creer_centraux, supprimer)]
