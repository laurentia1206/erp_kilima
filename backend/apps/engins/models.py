"""Modèles : Engins. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models


class Engin(models.Model):
    """Parc d'engins loués (module Location d'engins — ETS HORIZON)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    nom = models.CharField(max_length=128)
    categorie = models.CharField(max_length=64, null=True, blank=True)
    immatriculation = models.CharField(max_length=64, null=True, blank=True)
    tarif_mensuel_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tarif_heure_supp_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    consommation_l_heure = models.DecimalField(max_digits=8, decimal_places=2,
                                               null=True, blank=True)
    statut = models.CharField(max_length=16, default="disponible")
    motif_immobilisation = models.CharField(max_length=255, null=True, blank=True)
    immobilise_depuis = models.DateField(null=True, blank=True)
    actif = models.BooleanField(default=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "engin"


class PrestationEngin(models.Model):
    """Fiche de service journalière d'un engin (heures prestées).
    Les heures sont stockées en texte "HH:MM" ; les minutes prestées sont
    recalculées à la lecture (brut - arrêts, arrondi 5 min paramétrable)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    engin_id = models.UUIDField()
    date_prestation = models.DateField()
    poste = models.CharField(max_length=8, default="jour")
    operateur = models.CharField(max_length=128, null=True, blank=True)
    heure_debut = models.CharField(max_length=5)
    heure_fin = models.CharField(max_length=5)
    index_debut = models.DecimalField(max_digits=12, decimal_places=1,
                                      null=True, blank=True)
    index_fin = models.DecimalField(max_digits=12, decimal_places=1,
                                    null=True, blank=True)
    affectation = models.CharField(max_length=255, null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "prestation_engin"


class ArretPrestationEngin(models.Model):
    """Arrêt de travail (pause, panne…) déduit du temps presté d'une fiche."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prestation_id = models.UUIDField()
    nature = models.CharField(max_length=32, default="Pause")
    debut = models.CharField(max_length=5)
    fin = models.CharField(max_length=5)

    class Meta:
        managed = True
        db_table = "arret_prestation_engin"


class ReconciliationEngins(models.Model):
    """Réconciliation mensuelle des prestations avec le planning du locataire.

    Une fiche par société et par mois. `donnees` garde, par engin et par
    jour, les minutes du client et les minutes retenues après la séance
    d'harmonisation : {engin_id: {"YYYY-MM-DD": {"client_jour", "client_nuit",
    "retenu_jour", "retenu_nuit", "note"}}}. Une fois le statut « validee »
    posé par le responsable, le mois est verrouillé : plus aucune fiche de
    prestation ne peut être créée, modifiée ou supprimée sans réouverture
    par la direction (motif tracé)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    ym = models.CharField(max_length=7)
    statut = models.CharField(max_length=16, default="en_cours")
    donnees = models.JSONField(default=dict)
    revision = models.IntegerField(default=0)
    valide_par = models.UUIDField(null=True, blank=True)
    valide_at = models.DateTimeField(null=True, blank=True)
    reouverte_par = models.UUIDField(null=True, blank=True)
    reouverte_at = models.DateTimeField(null=True, blank=True)
    motif_reouverture = models.CharField(max_length=255, null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "reconciliation_engins"


class HarmonisationEngin(models.Model):
    """Arrangement d'heures entre deux engins d'un même mois (ex. céder des
    heures d'une chargeuse à une autre), proposé par le teneur des données
    puis approuvé ou rejeté par la hiérarchie avant facturation."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    ym = models.CharField(max_length=7)
    engin_source_id = models.UUIDField()
    engin_cible_id = models.UUIDField()
    poste = models.CharField(max_length=8, default="jour")
    minutes = models.IntegerField()
    motif = models.CharField(max_length=255)
    statut = models.CharField(max_length=16, default="proposee")
    propose_par = models.UUIDField(null=True, blank=True)
    propose_at = models.DateTimeField(null=True, blank=True)
    decide_par = models.UUIDField(null=True, blank=True)
    decide_at = models.DateTimeField(null=True, blank=True)
    commentaire_decision = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = True
        db_table = "harmonisation_engin"

