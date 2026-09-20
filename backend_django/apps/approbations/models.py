"""Modèles : Réquisitions et approbations. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models
from core.models import Role


class Requisition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=32, unique=True)
    societe_id = models.UUIDField()
    site_id = models.UUIDField(null=True, blank=True)
    initiateur_id = models.UUIDField()
    date_requisition = models.DateField(null=True, blank=True)
    objet = models.TextField()
    justification = models.TextField(null=True, blank=True)
    mode_decaissement = models.CharField(max_length=24, default="avance")
    nature = models.CharField(max_length=16, default="charge")
    priorite = models.CharField(max_length=16, default="normal")
    devise = models.CharField(max_length=8, default="USD")
    taux_jour = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    montant_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    montant_total_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    statut = models.CharField(max_length=32, default="brouillon")
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "requisition"



class RequisitionLigne(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requisition_id = models.UUIDField()
    ordre = models.IntegerField(default=0)
    compte_impute = models.CharField(max_length=16, null=True, blank=True)
    code_article = models.CharField(max_length=32, null=True, blank=True)
    description = models.TextField()
    unite = models.CharField(max_length=32, null=True, blank=True)
    quantite = models.DecimalField(max_digits=18, decimal_places=3, default=1)
    prix_unitaire = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    montant = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    devise = models.CharField(max_length=8, default="USD")
    montant_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        managed = True
        db_table = "requisition_ligne"



class RequisitionCommentaire(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requisition_id = models.UUIDField()
    auteur_id = models.UUIDField()
    type = models.CharField(max_length=32, default="commentaire")
    message = models.TextField()
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "requisition_commentaire"



class PalierValidation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField(null=True, blank=True)
    type_document = models.CharField(max_length=32)
    etape = models.CharField(max_length=32)
    montant_min_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    montant_max_usd = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    libelle = models.CharField(max_length=128, null=True, blank=True)
    ordre = models.IntegerField(default=0)

    class Meta:
        managed = True
        db_table = "palier_validation"



class PalierApprobateur(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    palier = models.ForeignKey(PalierValidation, on_delete=models.DO_NOTHING,
                               db_column="palier_id", related_name="approbateurs")
    role = models.ForeignKey(Role, on_delete=models.DO_NOTHING, db_column="role_id")
    mode = models.CharField(max_length=16, default="conjoint")
    ordre = models.IntegerField(default=0)

    class Meta:
        managed = True
        db_table = "palier_approbateur"



class Validation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_type = models.CharField(max_length=32)
    document_id = models.UUIDField()
    etape = models.CharField(max_length=32)
    palier_id = models.UUIDField(null=True, blank=True)
    role_attendu_id = models.UUIDField(null=True, blank=True)
    utilisateur_id = models.UUIDField(null=True, blank=True)
    decision = models.CharField(max_length=16, default="en_attente")
    mode = models.CharField(max_length=16, default="conjoint")
    commentaire = models.TextField(null=True, blank=True)
    canal = models.CharField(max_length=16, null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "validation"



class BonReception(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=32, unique=True)
    ordre_depense_id = models.UUIDField()
    caisse_id = models.UUIDField(null=True, blank=True)
    compte_bancaire_id = models.UUIDField(null=True, blank=True)
    receveur_tiers_id = models.UUIDField()
    caissier_id = models.UUIDField()
    date_reception = models.DateTimeField(null=True, blank=True)
    mode = models.CharField(max_length=16, default="caisse")
    reference_paiement = models.CharField(max_length=64, null=True, blank=True)
    devise = models.CharField(max_length=8, default="USD")
    taux_jour = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    montant = models.DecimalField(max_digits=18, decimal_places=2)
    montant_usd = models.DecimalField(max_digits=18, decimal_places=2)
    statut = models.CharField(max_length=16, default="emis")

    class Meta:
        managed = True
        db_table = "bon_reception"



class OrdreDepense(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=32)
    requisition_id = models.UUIDField()
    societe_id = models.UUIDField()
    beneficiaire_tiers_id = models.UUIDField()
    motif = models.TextField(null=True, blank=True)
    mode_paiement = models.CharField(max_length=16, default="caisse")
    mode_decaissement = models.CharField(max_length=24, default="avance")
    devise = models.CharField(max_length=8, default="USD")
    taux_jour = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    montant_autorise = models.DecimalField(max_digits=18, decimal_places=2)
    montant_autorise_usd = models.DecimalField(max_digits=18, decimal_places=2)
    montant_paye_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    montant_lettres = models.CharField(max_length=255, null=True, blank=True)
    palier_applique = models.CharField(max_length=32, null=True, blank=True)
    statut = models.CharField(max_length=32, default="a_valider")
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True)

    class Meta:
        managed = True
        db_table = "ordre_depense"

