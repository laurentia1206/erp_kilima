"""Modèles : Socle commun. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models


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


# Compatibilité des anciens imports. Les modèles appartiennent aux applications métier.
from apps.approbations.models import (Requisition, RequisitionLigne, RequisitionCommentaire, PalierValidation, PalierApprobateur, Validation, BonReception, OrdreDepense)  # noqa: F401,E402
from apps.tresorerie.models import (Caisse, CompteBancaire, SessionCaisse, MouvementCaisse, Avance, Justification, JustificationLigne, BlocageBeneficiaire, Transfert)  # noqa: F401,E402
from apps.comptabilite.models import (Compte, Exercice, Journal, Ecriture, LigneEcriture, RapprochementBancaire, PreparationTVA, AxeAnalytique, SectionAnalytique, VentilationAnalytique)  # noqa: F401,E402
from apps.stocks.models import (Article, MouvementStock, Depot, StockDepot, TransfertDepot, LigneTransfertDepot, InventaireDepot, LigneInventaireDepot)  # noqa: F401,E402
from apps.commercial.models import (Facture, LigneFacture, FraisFacture, PaiementFacture, Commande, LigneCommande, Reception, LigneReception, FraisReception, ListePrix, TarifArticle, PointVente, Devis, LigneDevis, Livraison, LigneLivraison)  # noqa: F401,E402
from apps.hotel.models import (Chambre, Sejour, LigneSejour, FicheTechnique, LigneFicheTechnique, ConsommationCuisine, LigneConsommationCuisine)  # noqa: F401,E402
from apps.transport.models import (Course, Camion, Chauffeur, ContratTransport, TarifContrat, CourseRequisition, PleinCarburant)  # noqa: F401,E402
from apps.maintenance.models import (InterventionCamion, DocumentFlotte, PlanEntretien)  # noqa: F401,E402
from apps.engins.models import (Engin, PrestationEngin, ArretPrestationEngin)  # noqa: F401,E402
from apps.groupe.models import (ReceptionInter, LigneReceptionInter)  # noqa: F401,E402
from apps.rh.models import (RHEquipe, RHHoraire, RHAgent, RHContrat, RHEvenement, RHDocument, RHPointage, RHDemande, RHPolitique, RHDette, RHSimulation, RHDecompte, RHPaieMois, RHBulletin, RHRetenue, RHPaiement)  # noqa: F401,E402
