"""Modèles : Stocks et inventaires. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models


class Article(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    code = models.CharField(max_length=32)
    designation = models.CharField(max_length=255)
    unite = models.CharField(max_length=32, default="unité")
    prix_achat = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    prix_vente = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    assujetti_tva = models.BooleanField(default=True)
    taux_tva = models.DecimalField(max_digits=6, decimal_places=2, default=16)
    categorie = models.CharField(max_length=64, null=True, blank=True)
    # nature : marchandise (vendue au POS) | matiere_premiere | consommable
    nature = models.CharField(max_length=20, default="marchandise")
    code_barres = models.CharField(max_length=64, null=True, blank=True)
    taux_commission = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    points_fidelite = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    compte_achat = models.CharField(max_length=16, default="601")
    compte_vente = models.CharField(max_length=16, default="701")
    compte_stock = models.CharField(max_length=16, default="31")
    gere_stock = models.BooleanField(default=True)
    stock_qte = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    stock_valeur = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "article"



class MouvementStock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    article_id = models.UUIDField()
    depot_id = models.UUIDField(null=True, blank=True)
    date_mvt = models.DateField()
    sens = models.CharField(max_length=16)
    qte = models.DecimalField(max_digits=18, decimal_places=3)
    cout_unitaire = models.DecimalField(max_digits=18, decimal_places=4)
    valeur = models.DecimalField(max_digits=18, decimal_places=2)
    type_operation = models.CharField(max_length=32)
    reference = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "mouvement_stock"



class Depot(models.Model):
    """Dépôt de stock. Chaque société a un dépôt CENTRAL (créé d'office,
    reçoit tous les achats) qui approvisionne des dépôts DÉDIÉS
    (restaurant, bar, cuisine, magasin…) par bons de transfert. Un point
    de vente est lié à un dépôt dédié et y puise ses ventes."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    code = models.CharField(max_length=20)
    libelle = models.CharField(max_length=128)
    type = models.CharField(max_length=16, default="dedie")
    actif = models.BooleanField(default=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "depot"



class StockDepot(models.Model):
    """Solde de stock d'un article dans un dépôt. Invariant :
    Article.stock_qte/valeur = somme des dépôts de la société."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    depot_id = models.UUIDField()
    article_id = models.UUIDField()
    qte = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    valeur = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        managed = True
        db_table = "stock_depot"



class TransfertDepot(models.Model):
    """Bon de transfert interne entre dépôts (valorisé au CUMP du dépôt
    source — aucune écriture comptable, le compte 3x ne change pas)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    depot_source_id = models.UUIDField()
    depot_cible_id = models.UUIDField()
    date_transfert = models.DateField()
    note = models.CharField(max_length=255, null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "transfert_depot"



class LigneTransfertDepot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transfert_id = models.UUIDField()
    article_id = models.UUIDField()
    qte = models.DecimalField(max_digits=18, decimal_places=3)
    valeur = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        managed = True
        db_table = "ligne_transfert_depot"



class InventaireDepot(models.Model):
    """Comptage physique préparé ; après validation comptable/DFI,
    écart valorisé au CUMP et ajusté en stock (658/758)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    statut = models.CharField(max_length=16, default='valide')
    valide_par = models.UUIDField(null=True, blank=True)
    valide_at = models.DateTimeField(null=True, blank=True)
    depot_id = models.UUIDField()
    date_inventaire = models.DateField()
    valeur_theorique = models.DecimalField(max_digits=18, decimal_places=2,
                                           default=0)
    valeur_reelle = models.DecimalField(max_digits=18, decimal_places=2,
                                        default=0)
    ecart_valeur = models.DecimalField(max_digits=18, decimal_places=2,
                                       default=0)
    note = models.CharField(max_length=255, null=True, blank=True)
    ecriture_id = models.UUIDField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "inventaire_depot"



class LigneInventaireDepot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inventaire_id = models.UUIDField()
    article_id = models.UUIDField()
    qte_theorique = models.DecimalField(max_digits=18, decimal_places=3)
    qte_reelle = models.DecimalField(max_digits=18, decimal_places=3)
    cump = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valeur_stock_comptee = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    ecart_qte = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    ecart_valeur = models.DecimalField(max_digits=18, decimal_places=2,
                                       default=0)

    class Meta:
        managed = True
        db_table = "ligne_inventaire_depot"

