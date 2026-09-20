"""Modèles : Comptabilité. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models


class Compte(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    numero = models.CharField(max_length=16)
    intitule = models.CharField(max_length=255)
    classe = models.CharField(max_length=4, null=True, blank=True)
    auxiliaire = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "compte"



class Exercice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    annee = models.IntegerField()
    date_debut = models.DateField()
    date_fin = models.DateField()
    statut = models.CharField(max_length=16, default="ouvert")

    class Meta:
        managed = True
        db_table = "exercice"



class Journal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    code = models.CharField(max_length=8)
    libelle = models.CharField(max_length=128)
    type = models.CharField(max_length=32)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "journal"



class Ecriture(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    exercice_id = models.UUIDField()
    journal_id = models.UUIDField(null=True, blank=True)
    numero = models.CharField(max_length=32)
    date_ecriture = models.DateField()
    numero_piece = models.CharField(max_length=64, null=True, blank=True)
    libelle = models.TextField()
    type_operation = models.CharField(max_length=48, null=True, blank=True)
    source_type = models.CharField(max_length=48, null=True, blank=True)
    source_id = models.UUIDField(null=True, blank=True)
    statut = models.CharField(max_length=16, default="valide")
    created_by = models.UUIDField(null=True, blank=True)
    # pas d'auto_now_add : horodatage posé par services.maintenant() (seconde, UTC
    # naïf) pour rester identique aux lignes CURRENT_TIMESTAMP de FastAPI/SQLite
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "ecriture"



class LigneEcriture(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ecriture = models.ForeignKey(Ecriture, on_delete=models.DO_NOTHING, db_column="ecriture_id")
    societe_id = models.UUIDField()
    ordre = models.IntegerField(default=0)
    sens = models.CharField(max_length=1)
    compte_numero = models.CharField(max_length=16)
    tiers_id = models.UUIDField(null=True, blank=True)
    montant_usd = models.DecimalField(max_digits=18, decimal_places=2)
    devise_origine = models.CharField(max_length=8, default="USD")
    montant_origine = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    taux_jour = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    libelle_ligne = models.CharField(max_length=255, null=True, blank=True)
    lettrage_code = models.CharField(max_length=16, null=True, blank=True)
    rapprochement_id = models.UUIDField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "ligne_ecriture"



class RapprochementBancaire(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    compte = models.CharField(max_length=16)
    date_releve = models.DateField()
    solde_releve_usd = models.DecimalField(max_digits=18, decimal_places=2)
    solde_comptable_usd = models.DecimalField(max_digits=18, decimal_places=2)
    solde_rapproche_usd = models.DecimalField(max_digits=18, decimal_places=2)
    ecart_usd = models.DecimalField(max_digits=18, decimal_places=2)
    statut = models.CharField(max_length=16, default="cloture")
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "rapprochement_bancaire"



class PreparationTVA(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    mois = models.CharField(max_length=7)
    donnees = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    updated_by = models.UUIDField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'preparation_tva'
        constraints = [models.UniqueConstraint(fields=['societe_id', 'mois'], name='preparation_tva_societe_mois')]



class AxeAnalytique(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    code = models.CharField(max_length=20)
    libelle = models.CharField(max_length=128)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "axe_analytique"



class SectionAnalytique(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    axe_id = models.UUIDField()
    societe_id = models.UUIDField()
    code = models.CharField(max_length=20)
    libelle = models.CharField(max_length=128)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "section_analytique"



class VentilationAnalytique(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    ligne_ecriture_id = models.UUIDField()
    axe_id = models.UUIDField()
    section_id = models.UUIDField()
    montant_usd = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        managed = True
        db_table = "ventilation_analytique"

