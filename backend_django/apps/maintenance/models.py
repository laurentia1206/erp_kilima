"""Modèles : Maintenance. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models


class InterventionCamion(models.Model):
    # Maintenance mutualisée de la flotte : un camion OU un engin de location
    # (exactement l'un des deux renseigné).
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    camion_id = models.UUIDField(null=True, blank=True)
    engin_id = models.UUIDField(null=True, blank=True)
    numero = models.CharField(max_length=32)
    type = models.CharField(max_length=16, default="reparation")
    statut = models.CharField(max_length=16, default="signalee")
    date_prevue = models.DateField(null=True, blank=True)
    description = models.TextField()
    prestataire = models.CharField(max_length=128, null=True, blank=True)
    cout_estime = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cout_reel = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    immobilise = models.BooleanField(default=True)
    date_signalement = models.DateField()
    date_fin = models.DateField(null=True, blank=True)
    requisition_id = models.UUIDField(null=True, blank=True)
    plan_id = models.UUIDField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "intervention_camion"



class DocumentFlotte(models.Model):
    """Document administratif d'un camion, d'un engin ou d'un chauffeur
    (assurance, contrôle technique, carte rose, permis…) avec date
    d'expiration → alertes avant échéance. Fichiers scannés attachés via
    le système générique piece_jointe (document_type='document_flotte')."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    camion_id = models.UUIDField(null=True, blank=True)
    engin_id = models.UUIDField(null=True, blank=True)
    chauffeur_id = models.UUIDField(null=True, blank=True)
    type_document = models.CharField(max_length=32, default="autre")
    libelle = models.CharField(max_length=128)
    numero = models.CharField(max_length=64, null=True, blank=True)
    date_emission = models.DateField(null=True, blank=True)
    date_expiration = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=255, null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "document_flotte"



class PlanEntretien(models.Model):
    """Entretien préventif périodique d'un véhicule (camion OU engin).
    La périodicité se mesure en heures prestées (engins), en courses
    effectuées (camions) ou en jours calendaires ; l'échéance est calculée
    depuis l'usage réel enregistré par les modules transport / location."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    camion_id = models.UUIDField(null=True, blank=True)
    engin_id = models.UUIDField(null=True, blank=True)
    libelle = models.CharField(max_length=128)
    periodicite_type = models.CharField(max_length=16, default="heures")
    periodicite_valeur = models.DecimalField(max_digits=12, decimal_places=1)
    derniere_date = models.DateField(null=True, blank=True)
    derniere_valeur = models.DecimalField(max_digits=12, decimal_places=1,
                                          null=True, blank=True)
    note = models.CharField(max_length=255, null=True, blank=True)
    actif = models.BooleanField(default=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "plan_entretien"

