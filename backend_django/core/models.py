"""Modèles Django sur les tables EXISTANTES (mêmes noms de tables/colonnes que
les modèles SQLAlchemy de backend/app/models.py).

Depuis la bascule (phase 10), Django est PROPRIÉTAIRE du schéma : les modèles
sont managed=True et toute évolution passe par makemigrations + migrate.
Exception : utilisateur_societe (clé primaire composite) reste managed=False —
ses écritures se font en SQL brut (voir config_views.py).
"""
from __future__ import annotations

import uuid

from django.db import models

from .rh_models import (RHEquipe, RHHoraire, RHAgent, RHContrat, RHEvenement,
                        RHDocument, RHPointage, RHDemande, RHPolitique, RHDette, RHSimulation, RHDecompte,
                        RHPaieMois, RHBulletin, RHRetenue, RHPaiement)


class Societe(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=16, unique=True)
    nom = models.CharField(max_length=255)
    rccm = models.CharField(max_length=64, null=True, blank=True)
    id_nat = models.CharField(max_length=64, null=True, blank=True)
    nif = models.CharField(max_length=64, null=True, blank=True)
    ville = models.CharField(max_length=64, null=True, blank=True)
    devise_tenue = models.CharField(max_length=8, default="USD")
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "societe"


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    libelle = models.CharField(max_length=128)
    niveau = models.IntegerField(default=0)
    herite_de = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        managed = True
        db_table = "role"


class Utilisateur(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.CharField(max_length=255, unique=True)
    nom = models.CharField(max_length=128)
    prenom = models.CharField(max_length=128, null=True, blank=True)
    password_hash = models.CharField(max_length=128)
    telephone = models.CharField(max_length=32, null=True, blank=True)
    actif = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "utilisateur"

    # compat DRF (request.user)
    @property
    def is_authenticated(self) -> bool:
        return True


class Parametre(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe = models.ForeignKey(Societe, on_delete=models.DO_NOTHING,
                                db_column="societe_id", null=True, blank=True)
    cle = models.CharField(max_length=128)
    valeur = models.CharField(max_length=255)
    type_valeur = models.CharField(max_length=16, default="number")
    description = models.TextField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "parametre"


class SequenceCompteur(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField(null=True, blank=True)
    type_piece = models.CharField(max_length=32)
    annee = models.IntegerField()
    dernier_numero = models.IntegerField(default=0)

    class Meta:
        managed = True
        db_table = "sequence_compteur"


class TauxChange(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date_taux = models.DateField()
    devise = models.CharField(max_length=8, default="CDF")
    taux_usd = models.DecimalField(max_digits=18, decimal_places=6)
    defini_par_id = models.UUIDField(db_column="defini_par")
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "taux_change"


class AuditLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    utilisateur_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=32)
    table_cible = models.CharField(max_length=64)
    enregistrement_id = models.CharField(max_length=64, null=True, blank=True)
    ancienne_valeur = models.JSONField(null=True, blank=True)
    nouvelle_valeur = models.JSONField(null=True, blank=True)
    adresse_ip = models.CharField(max_length=64, null=True, blank=True)
    horodatage = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "audit_log"


class Tiers(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField(null=True, blank=True)
    type = models.CharField(max_length=32)
    code = models.CharField(max_length=32)
    nom = models.CharField(max_length=255)
    compte_auxiliaire = models.CharField(max_length=16, null=True, blank=True)
    utilisateur_id = models.UUIDField(null=True, blank=True)
    intra_groupe = models.BooleanField(default=False)
    limite_credit_usd = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    points_fidelite = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    societe_liee_id = models.UUIDField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "tiers"


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


# ── Comptabilité (phase 2 — lecture ; écriture demain avec Exercice/Journal) ─
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


class PieceJointe(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_type = models.CharField(max_length=32)
    document_id = models.UUIDField()
    nom_fichier = models.CharField(max_length=255)
    chemin_stockage = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=128, null=True, blank=True)
    taille_octets = models.IntegerField(null=True, blank=True)
    uploaded_by = models.UUIDField(null=True, blank=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "piece_jointe"


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


# ── Cycle commercial : factures, commandes, réceptions, POS ──────────
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


class ReceptionInter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    commande_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    date_reception = models.DateField()
    note = models.CharField(max_length=255, null=True, blank=True)
    statut = models.CharField(max_length=16, default="confirmee")
    confirme_par = models.UUIDField(null=True, blank=True)
    date_confirmation = models.DateTimeField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "reception_inter"


class LigneReceptionInter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reception_id = models.UUIDField()
    ligne_commande_id = models.UUIDField()
    qte_bon = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    qte_mauvais = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    qte_manquante = models.DecimalField(max_digits=18, decimal_places=3, default=0)

    class Meta:
        managed = True
        db_table = "ligne_reception_inter"


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


class UtilisateurSociete(models.Model):
    # Django ne gère pas les PK composites : on mappe sur rowid implicite via
    # une pk factice — lecture seule sur cette table en attendant la phase 9.
    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.DO_NOTHING,
                                    db_column="utilisateur_id", primary_key=True)
    societe = models.ForeignKey(Societe, on_delete=models.DO_NOTHING, db_column="societe_id")
    role = models.ForeignKey(Role, on_delete=models.DO_NOTHING, db_column="role_id")
    site_id = models.UUIDField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "utilisateur_societe"
