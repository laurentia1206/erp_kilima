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

