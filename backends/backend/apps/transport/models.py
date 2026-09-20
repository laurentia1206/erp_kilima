"""Modèles : Transport et carburant. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models


class Course(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    date_course = models.DateField()
    client_tiers_id = models.UUIDField()
    contrat_id = models.UUIDField(null=True, blank=True)
    camion_id = models.UUIDField(null=True, blank=True)
    chauffeur_id = models.UUIDField(null=True, blank=True)
    origine = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    marchandise = models.CharField(max_length=255)
    tonnage_prevu = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    tonnage_livre = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    unite = models.CharField(max_length=32, default="tonnes")
    tarif_mode = models.CharField(max_length=16, default="tonne")
    prix_unitaire = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    statut = models.CharField(max_length=16, default="brouillon")
    commande_origine_id = models.UUIDField(null=True, blank=True)
    heure_depart = models.DateTimeField(null=True, blank=True)
    heure_retour = models.DateTimeField(null=True, blank=True)
    km_depart = models.DecimalField(max_digits=12, decimal_places=1,
                                    null=True, blank=True)
    km_retour = models.DecimalField(max_digits=12, decimal_places=1,
                                    null=True, blank=True)
    incidents = models.TextField(null=True, blank=True)
    requisition_id = models.UUIDField(null=True, blank=True)
    st_mode = models.CharField(max_length=16, null=True, blank=True)
    st_valeur = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    st_cout = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    st_facture_id = models.UUIDField(null=True, blank=True)
    facture_id = models.UUIDField(null=True, blank=True)
    valide_par = models.UUIDField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "course"


class Camion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    immatriculation = models.CharField(max_length=32)
    marque = models.CharField(max_length=64, null=True, blank=True)
    capacite_tonnes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    consommation_l_100km = models.DecimalField(max_digits=8, decimal_places=2,
                                               null=True, blank=True)
    type = models.CharField(max_length=16, default="propre")
    proprietaire_tiers_id = models.UUIDField(null=True, blank=True)
    remuneration_mode = models.CharField(max_length=16, null=True, blank=True)
    remuneration_valeur = models.DecimalField(max_digits=18, decimal_places=2,
                                              null=True, blank=True)
    statut = models.CharField(max_length=16, default="disponible")
    motif_immobilisation = models.CharField(max_length=255, null=True, blank=True)
    immobilise_depuis = models.DateField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "camion"


class Chauffeur(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    nom = models.CharField(max_length=128)
    telephone = models.CharField(max_length=32, null=True, blank=True)
    numero_permis = models.CharField(max_length=64, null=True, blank=True)
    tiers_id = models.UUIDField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "chauffeur"


class ContratTransport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    libelle = models.CharField(max_length=128)
    client_tiers_id = models.UUIDField()
    date_debut = models.DateField()
    date_fin = models.DateField(null=True, blank=True)
    statut = models.CharField(max_length=16, default="actif")
    note = models.TextField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "contrat_transport"


class TarifContrat(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contrat_id = models.UUIDField()
    trajet = models.CharField(max_length=128)
    mode = models.CharField(max_length=16, default="tonne")
    prix = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        managed = True
        db_table = "tarif_contrat"


class CourseRequisition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course_id = models.UUIDField()
    requisition_id = models.UUIDField()

    class Meta:
        managed = True
        db_table = "course_requisition"


class PleinCarburant(models.Model):
    """Plein de carburant d'un camion ou d'un engin. La consommation réelle
    se calcule sur la période : litres / km parcourus (camions, relevés des
    courses) ou litres / heures prestées (engins, fiches de prestation),
    comparée à la consommation théorique du véhicule."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    camion_id = models.UUIDField(null=True, blank=True)
    engin_id = models.UUIDField(null=True, blank=True)
    course_id = models.UUIDField(null=True, blank=True)
    date_plein = models.DateField()
    litres = models.DecimalField(max_digits=10, decimal_places=2)
    prix_litre_usd = models.DecimalField(max_digits=10, decimal_places=3,
                                         null=True, blank=True)
    montant_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    compteur = models.DecimalField(max_digits=12, decimal_places=1,
                                   null=True, blank=True)
    fournisseur = models.CharField(max_length=128, null=True, blank=True)
    note = models.CharField(max_length=255, null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "plein_carburant"

