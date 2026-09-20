"""Modèles : Achats et ventes. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models


class Facture(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    type = models.CharField(max_length=16)
    numero = models.CharField(max_length=32)
    tiers_id = models.UUIDField()
    date_facture = models.DateField()
    echeance = models.DateField(null=True, blank=True)
    reference = models.CharField(max_length=64, null=True, blank=True)
    total_ht = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_frais = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_tva = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_ttc = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    repartition = models.CharField(max_length=16, default="quantite")
    cout_ventes = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    marge = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    remise_totale = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    note = models.CharField(max_length=255, null=True, blank=True)
    statut = models.CharField(max_length=16, default="validee")
    intra_groupe = models.BooleanField(default=False)
    reception_id = models.UUIDField(null=True, blank=True)
    point_vente_id = models.UUIDField(null=True, blank=True)
    origine_id = models.UUIDField(null=True, blank=True)
    devis_id = models.UUIDField(null=True, blank=True)
    facture_liee_id = models.UUIDField(null=True, blank=True)
    pos_recu_usd = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    pos_monnaie_usd = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    ecriture_id = models.UUIDField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "facture"



class LigneFacture(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facture_id = models.UUIDField()
    article_id = models.UUIDField(null=True, blank=True)
    designation = models.CharField(max_length=255)
    qte = models.DecimalField(max_digits=18, decimal_places=3, default=1)
    prix_unitaire = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    remise_pct = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    taux_tva = models.DecimalField(max_digits=6, decimal_places=2, default=16)
    montant_ht = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    montant_tva = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    frais_reparti = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    cout_entree = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    origine_ligne_id = models.UUIDField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "ligne_facture"



class FraisFacture(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facture_id = models.UUIDField()
    libelle = models.CharField(max_length=128)
    compte = models.CharField(max_length=16, default="6085")
    montant_ht = models.DecimalField(max_digits=18, decimal_places=2)
    taux_tva = models.DecimalField(max_digits=6, decimal_places=2, default=16)
    montant_tva = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    mode = models.CharField(max_length=16, default="credit")
    tiers_id = models.UUIDField(null=True, blank=True)
    compte_reglement = models.CharField(max_length=16, null=True, blank=True)
    caisse_id = models.UUIDField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "frais_facture"



class PaiementFacture(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facture_id = models.UUIDField()
    mode = models.CharField(max_length=16)
    devise = models.CharField(max_length=8, default="USD")
    montant = models.DecimalField(max_digits=18, decimal_places=2)
    taux_jour = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    montant_usd = models.DecimalField(max_digits=18, decimal_places=2)
    reference = models.CharField(max_length=64, null=True, blank=True)
    compte = models.CharField(max_length=16, null=True, blank=True)

    class Meta:
        managed = True
        db_table = "paiement_facture"



class Commande(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    tiers_id = models.UUIDField()
    date_commande = models.DateField()
    date_livraison_prevue = models.DateField(null=True, blank=True)
    reference_fournisseur = models.CharField(max_length=64, null=True, blank=True)
    total_ht = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    intra_groupe = models.BooleanField(default=False)
    statut = models.CharField(max_length=16, default="envoyee")
    destination = models.CharField(max_length=255, null=True, blank=True)
    transporteur_societe_id = models.UUIDField(null=True, blank=True)
    devis_lie_id = models.UUIDField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "commande"



class LigneCommande(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commande_id = models.UUIDField()
    article_id = models.UUIDField(null=True, blank=True)
    designation = models.CharField(max_length=255)
    qte = models.DecimalField(max_digits=18, decimal_places=3, default=1)
    qte_recue = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    prix_unitaire = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    taux_tva = models.DecimalField(max_digits=6, decimal_places=2, default=16)

    class Meta:
        managed = True
        db_table = "ligne_commande"



class Reception(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    commande_id = models.UUIDField()
    date_reception = models.DateField()
    total_valeur = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_frais = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    repartition = models.CharField(max_length=16, default="quantite")
    statut = models.CharField(max_length=16, default="recue")
    ecriture_id = models.UUIDField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "reception"



class LigneReception(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reception_id = models.UUIDField()
    ligne_commande_id = models.UUIDField(null=True, blank=True)
    article_id = models.UUIDField(null=True, blank=True)
    designation = models.CharField(max_length=255)
    qte = models.DecimalField(max_digits=18, decimal_places=3)
    prix_unitaire = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    taux_tva = models.DecimalField(max_digits=6, decimal_places=2, default=16)
    montant_ht = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    frais_reparti = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    cout = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    compte_stock = models.CharField(max_length=16, default="31")

    class Meta:
        managed = True
        db_table = "ligne_reception"



class FraisReception(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reception_id = models.UUIDField()
    libelle = models.CharField(max_length=128)
    compte = models.CharField(max_length=16, default="6085")
    montant_ht = models.DecimalField(max_digits=18, decimal_places=2)
    taux_tva = models.DecimalField(max_digits=6, decimal_places=2, default=16)
    montant_tva = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    mode = models.CharField(max_length=16, default="credit")
    tiers_id = models.UUIDField(null=True, blank=True)
    compte_reglement = models.CharField(max_length=16, null=True, blank=True)
    caisse_id = models.UUIDField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "frais_reception"



class ListePrix(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    code = models.CharField(max_length=20)
    libelle = models.CharField(max_length=128)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "liste_prix"



class TarifArticle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    liste_prix_id = models.UUIDField()
    article_id = models.UUIDField()
    prix = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        managed = True
        db_table = "tarif_article"



class PointVente(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    depot_id = models.UUIDField(null=True, blank=True)
    code = models.CharField(max_length=20)
    libelle = models.CharField(max_length=128)
    liste_prix_id = models.UUIDField(null=True, blank=True)
    caisse_id = models.UUIDField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "point_vente"



class Devis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    tiers_id = models.UUIDField()
    date_devis = models.DateField()
    validite = models.DateField(null=True, blank=True)
    statut = models.CharField(max_length=16, default="brouillon")
    remise_globale_pct = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total_ht = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_tva = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_ttc = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    remise_totale = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    conditions = models.CharField(max_length=255, null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    reference_producteur = models.CharField(max_length=64, null=True, blank=True)
    date_confirmation = models.DateTimeField(null=True, blank=True)
    commande_origine_id = models.UUIDField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "devis"



class LigneDevis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    devis_id = models.UUIDField()
    ordre = models.IntegerField(default=0)
    article_id = models.UUIDField(null=True, blank=True)
    designation = models.CharField(max_length=255)
    qte = models.DecimalField(max_digits=18, decimal_places=3, default=1)
    prix_unitaire = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    remise_pct = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    taux_tva = models.DecimalField(max_digits=6, decimal_places=2, default=16)
    montant_ht = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    montant_tva = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    qte_livree = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    qte_facturee = models.DecimalField(max_digits=18, decimal_places=3, default=0)

    class Meta:
        managed = True
        db_table = "ligne_devis"



class Livraison(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    devis_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    date_livraison = models.DateField()
    note = models.CharField(max_length=255, null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "livraison"



class LigneLivraison(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    livraison_id = models.UUIDField()
    ligne_devis_id = models.UUIDField()
    article_id = models.UUIDField(null=True, blank=True)
    designation = models.CharField(max_length=255)
    qte = models.DecimalField(max_digits=18, decimal_places=3)
    cout_unitaire = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valeur = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        managed = True
        db_table = "ligne_livraison"

