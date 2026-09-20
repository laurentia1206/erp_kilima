"""Modèles : Trésorerie. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models


class Caisse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    libelle = models.CharField(max_length=128)
    compte_comptable = models.CharField(max_length=16, null=True, blank=True)
    est_principale = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "caisse"



class CompteBancaire(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    banque = models.CharField(max_length=128)
    numero_compte = models.CharField(max_length=64, null=True, blank=True)
    devise = models.CharField(max_length=8, default="USD")
    compte_comptable = models.CharField(max_length=16, null=True, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "compte_bancaire"



class SessionCaisse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    caisse = models.ForeignKey(Caisse, on_delete=models.DO_NOTHING, db_column="caisse_id")
    date_ouverture = models.DateTimeField(null=True)
    ouvert_par = models.UUIDField()
    fond_initial_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    fond_initial_cdf = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    statut = models.CharField(max_length=16, default="ouverte")
    date_cloture = models.DateTimeField(null=True, blank=True)
    cloture_par = models.UUIDField(null=True, blank=True)
    solde_theorique_usd = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    solde_theorique_cdf = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    solde_physique_usd = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    solde_physique_cdf = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    ecart_usd = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    ecart_cdf = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    billetage_cloture = models.JSONField(null=True, blank=True)
    commentaire_cloture = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = True
        db_table = "session_caisse"



class MouvementCaisse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    caisse_id = models.UUIDField()
    session_id = models.UUIDField(null=True, blank=True)
    numero = models.CharField(max_length=32, null=True, blank=True)
    reference = models.CharField(max_length=64, null=True, blank=True)
    billetage = models.JSONField(null=True, blank=True)
    tiers_id = models.UUIDField(null=True, blank=True)
    tiers_nom = models.CharField(max_length=255, null=True, blank=True)
    date_mouvement = models.DateField(null=True, blank=True)
    heure = models.DateTimeField(null=True, blank=True)
    sens = models.CharField(max_length=8)
    nature = models.CharField(max_length=64, null=True, blank=True)
    devise = models.CharField(max_length=8, default="USD")
    taux_jour = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    montant = models.DecimalField(max_digits=18, decimal_places=2)
    montant_usd = models.DecimalField(max_digits=18, decimal_places=2)
    reference_type = models.CharField(max_length=32, null=True, blank=True)
    reference_id = models.UUIDField(null=True, blank=True)
    libelle = models.CharField(max_length=255, null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "mouvement_caisse"



class Avance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=32, unique=True)
    ordre_depense_id = models.UUIDField()
    bon_reception_id = models.UUIDField(null=True, blank=True)
    beneficiaire_tiers_id = models.UUIDField()
    societe_id = models.UUIDField()
    type_avance = models.CharField(max_length=32, null=True, blank=True)
    devise = models.CharField(max_length=8, default="USD")
    montant_avance = models.DecimalField(max_digits=18, decimal_places=2)
    montant_avance_usd = models.DecimalField(max_digits=18, decimal_places=2)
    date_octroi = models.DateTimeField(null=True, blank=True)
    delai_justif_heures = models.IntegerField(null=True, blank=True)
    echeance_justif = models.DateTimeField(null=True, blank=True)
    statut = models.CharField(max_length=32, default="a_justifier")
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "avance"



class Justification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=32, unique=True)
    avance_id = models.UUIDField()
    date_justification = models.DateField(null=True, blank=True)
    montant_justifie = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    montant_justifie_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    solde_retourne = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    solde_retourne_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    ecart_usd = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    complement_demande = models.BooleanField(default=False)
    statut = models.CharField(max_length=16, default="soumise")
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "justification"



class JustificationLigne(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    justification_id = models.UUIDField()
    date_achat = models.DateField(null=True, blank=True)
    nature = models.CharField(max_length=255)
    compte_impute = models.CharField(max_length=16, null=True, blank=True)
    fournisseur = models.CharField(max_length=128, null=True, blank=True)
    num_piece = models.CharField(max_length=64, null=True, blank=True)
    devise = models.CharField(max_length=8, default="USD")
    montant = models.DecimalField(max_digits=18, decimal_places=2)
    montant_usd = models.DecimalField(max_digits=18, decimal_places=2)
    a_piece_jointe = models.BooleanField(default=False)

    class Meta:
        managed = True
        db_table = "justification_ligne"



class BlocageBeneficiaire(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tiers_id = models.UUIDField()
    avance_id = models.UUIDField(null=True, blank=True)
    motif = models.TextField()
    actif = models.BooleanField(default=True)
    bloque_at = models.DateTimeField(null=True, blank=True)
    leve_par = models.UUIDField(null=True, blank=True)
    leve_motif = models.TextField(null=True, blank=True)
    leve_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "blocage_beneficiaire"



class Transfert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=32, unique=True)
    societe_id = models.UUIDField()
    source_type = models.CharField(max_length=16)
    source_id = models.UUIDField()
    dest_type = models.CharField(max_length=16)
    dest_id = models.UUIDField()
    devise = models.CharField(max_length=8, default="USD")
    taux_jour = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    montant = models.DecimalField(max_digits=18, decimal_places=2)
    montant_usd = models.DecimalField(max_digits=18, decimal_places=2)
    motif = models.TextField(null=True, blank=True)
    statut = models.CharField(max_length=16, default="a_valider")
    initie_par = models.UUIDField()
    created_at = models.DateTimeField(null=True, blank=True)
    valide_par = models.UUIDField(null=True, blank=True)
    valide_at = models.DateTimeField(null=True, blank=True)
    motif_rejet = models.TextField(null=True, blank=True)
    source_mouvement_id = models.UUIDField(null=True, blank=True)
    dest_mouvement_id = models.UUIDField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "transfert"

