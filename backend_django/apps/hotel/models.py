"""Modèles : Hôtel et cuisine. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models


class Chambre(models.Model):
    """Chambre d'hôtel (module Hôtellerie — Guest House Relax).
    etat : libre | occupee | sale | nettoyage | maintenance (housekeeping)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=16)
    categorie = models.CharField(max_length=64, null=True, blank=True)
    tarif_nuit_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    capacite = models.IntegerField(default=2)
    etat = models.CharField(max_length=16, default="libre")
    note = models.CharField(max_length=255, null=True, blank=True)
    actif = models.BooleanField(default=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "chambre"



class Sejour(models.Model):
    """Réservation puis séjour : reservee -> arrivee -> terminee
    (ou annulee / no_show). Intervalle [arrivee, depart) : le jour du
    départ, la chambre est libre pour une nouvelle arrivée."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    chambre_id = models.UUIDField()
    tiers_id = models.UUIDField(null=True, blank=True)
    client_nom = models.CharField(max_length=128)
    client_telephone = models.CharField(max_length=32, null=True, blank=True)
    nb_personnes = models.IntegerField(default=1)
    date_arrivee = models.DateField()
    date_depart_prevue = models.DateField()
    date_depart = models.DateField(null=True, blank=True)
    tarif_nuit_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    statut = models.CharField(max_length=16, default="reservee")
    source = models.CharField(max_length=16, default="directe")
    note = models.CharField(max_length=255, null=True, blank=True)
    facture_id = models.UUIDField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "sejour"



class LigneSejour(models.Model):
    """Ligne du folio (la note du séjour) : extra facturé au check-out
    (blanchisserie, divers…) ou ticket POS envoyé « sur la chambre »
    (facture_pos_id renseigné = déjà facturé par le POS, affiché sur la
    note mais exclu de la facture d'hébergement)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sejour_id = models.UUIDField()
    date_ligne = models.DateField()
    designation = models.CharField(max_length=255)
    qte = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    prix_unitaire = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    montant_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    origine = models.CharField(max_length=16, default="divers")
    facture_pos_id = models.UUIDField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "ligne_sejour"



class FicheTechnique(models.Model):
    """Recette d'un plat (article vendu au POS, généralement sans stock) :
    la liste des ingrédients consommés par portion. Base du food cost."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    article_id = models.UUIDField()
    portions = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    note = models.CharField(max_length=255, null=True, blank=True)
    actif = models.BooleanField(default=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "fiche_technique"



class LigneFicheTechnique(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fiche_id = models.UUIDField()
    ingredient_article_id = models.UUIDField()
    qte = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        managed = True
        db_table = "ligne_fiche_technique"



class ConsommationCuisine(models.Model):
    """Bon de consommation THÉORIQUE d'une journée : ventes de plats du
    jour × fiches techniques → sortie des ingrédients du dépôt cuisine
    au CUMP (D 603 / C 3x). L'inventaire périodique mesure l'écart réel."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    depot_id = models.UUIDField()
    date_conso = models.DateField()
    cout_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    ca_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    nb_plats = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    ecriture_id = models.UUIDField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "consommation_cuisine"



class LigneConsommationCuisine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    consommation_id = models.UUIDField()
    article_id = models.UUIDField()
    qte = models.DecimalField(max_digits=18, decimal_places=4)
    valeur = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        managed = True
        db_table = "ligne_consommation_cuisine"

