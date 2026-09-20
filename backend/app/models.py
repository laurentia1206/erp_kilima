"""ModÃ¨les ORM SQLAlchemy â€” miroir de database/schema_v1.sql (cÅ“ur V1).

Pour le scaffold, les tables du circuit de dÃ©caissement, le rÃ©fÃ©rentiel, la
caisse et l'audit sont mappÃ©s. Les autres tables du schÃ©ma (comptabilitÃ©
dÃ©taillÃ©e, etc.) seront ajoutÃ©es au fil des modules.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Types neutres : sur PostgreSQL â†’ uuid/json natifs ; sur SQLite â†’ CHAR(32)/TEXT.
# Permet de dÃ©velopper sur SQLite (un simple fichier) et dÃ©ployer sur PostgreSQL.


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


# â”€â”€ RÃ©fÃ©rentiel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class Societe(Base):
    __tablename__ = "societe"
    id: Mapped[uuid.UUID] = pk()
    code: Mapped[str] = mapped_column(String, unique=True)
    nom: Mapped[str] = mapped_column(String)
    rccm: Mapped[str | None] = mapped_column(String, nullable=True)
    id_nat: Mapped[str | None] = mapped_column(String, nullable=True)
    nif: Mapped[str | None] = mapped_column(String, nullable=True)
    ville: Mapped[str] = mapped_column(String, default="Likasi")
    devise_tenue: Mapped[str] = mapped_column(String, default="USD")
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Site(Base):
    __tablename__ = "site"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    code: Mapped[str] = mapped_column(String)
    nom: Mapped[str] = mapped_column(String)
    ville: Mapped[str | None] = mapped_column(String, nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("societe_id", "code"),)


class Role(Base):
    __tablename__ = "role"
    id: Mapped[uuid.UUID] = pk()
    code: Mapped[str] = mapped_column(String, unique=True)
    libelle: Mapped[str] = mapped_column(String)
    niveau: Mapped[int] = mapped_column(Integer, default=0)
    herite_de: Mapped[str | None] = mapped_column(String, nullable=True)  # rôle personnalisé :
    # code du rôle de base dont il hérite les DROITS d'accès (ex. LOGISTICIEN → COMPTABLE)


class Utilisateur(Base):
    __tablename__ = "utilisateur"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String, unique=True)
    nom: Mapped[str] = mapped_column(String)
    prenom: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str] = mapped_column(String)
    telephone: Mapped[str | None] = mapped_column(String, nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    affectations: Mapped[list["UtilisateurSociete"]] = relationship(back_populates="utilisateur")


class UtilisateurSociete(Base):
    __tablename__ = "utilisateur_societe"
    utilisateur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateur.id"), primary_key=True)
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id"), primary_key=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("site.id"), nullable=True)

    utilisateur: Mapped["Utilisateur"] = relationship(back_populates="affectations")
    role: Mapped["Role"] = relationship()
    societe: Mapped["Societe"] = relationship()


class TauxChange(Base):
    __tablename__ = "taux_change"
    id: Mapped[uuid.UUID] = pk()
    date_taux: Mapped[datetime] = mapped_column(Date)
    devise: Mapped[str] = mapped_column(String, default="CDF")
    taux_usd: Mapped[float] = mapped_column(Numeric(18, 6))
    defini_par: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateur.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("date_taux", "devise"),)


class Tiers(Base):
    __tablename__ = "tiers"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("societe.id"), nullable=True)
    type: Mapped[str] = mapped_column(String)
    code: Mapped[str] = mapped_column(String)
    nom: Mapped[str] = mapped_column(String)
    compte_auxiliaire: Mapped[str | None] = mapped_column(String, nullable=True)
    utilisateur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    intra_groupe: Mapped[bool] = mapped_column(Boolean, default=False)
    limite_credit_usd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    points_fidelite: Mapped[float] = mapped_column(Numeric(18, 2), default=0)   # cumul fidélité (POS)
    societe_liee_id: Mapped[uuid.UUID | None] = mapped_column(                  # tiers intra-groupe :
        ForeignKey("societe.id"), nullable=True)                               # ce tiers EST cette société
    actif: Mapped[bool] = mapped_column(Boolean, default=True)


class Parametre(Base):
    __tablename__ = "parametre"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("societe.id"), nullable=True)
    cle: Mapped[str] = mapped_column(String)
    valeur: Mapped[str] = mapped_column(String)
    type_valeur: Mapped[str] = mapped_column(String, default="number")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("societe_id", "cle"),)


# â”€â”€ Validation paramÃ©trable â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class PalierValidation(Base):
    __tablename__ = "palier_validation"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("societe.id"), nullable=True)
    type_document: Mapped[str] = mapped_column(String)
    etape: Mapped[str] = mapped_column(String)
    montant_min_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    montant_max_usd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    libelle: Mapped[str | None] = mapped_column(String, nullable=True)
    ordre: Mapped[int] = mapped_column(Integer, default=0)
    approbateurs: Mapped[list["PalierApprobateur"]] = relationship(back_populates="palier")


class PalierApprobateur(Base):
    __tablename__ = "palier_approbateur"
    id: Mapped[uuid.UUID] = pk()
    palier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("palier_validation.id", ondelete="CASCADE"))
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id"))
    mode: Mapped[str] = mapped_column(String, default="conjoint")
    ordre: Mapped[int] = mapped_column(Integer, default=0)
    palier: Mapped["PalierValidation"] = relationship(back_populates="approbateurs")
    role: Mapped["Role"] = relationship()


class SequenceCompteur(Base):
    __tablename__ = "sequence_compteur"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("societe.id"), nullable=True)
    type_piece: Mapped[str] = mapped_column(String)
    annee: Mapped[int] = mapped_column(Integer)
    dernier_numero: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("societe_id", "type_piece", "annee"),)


# â”€â”€ Caisse â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class Caisse(Base):
    __tablename__ = "caisse"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("site.id"), nullable=True)
    libelle: Mapped[str] = mapped_column(String)
    compte_comptable: Mapped[str | None] = mapped_column(String, nullable=True)
    responsable_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    est_principale: Mapped[bool] = mapped_column(Boolean, default=False)   # caisse centrale (destination des cessions POS)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)


class Transfert(Base):
    """Transfert de fonds entre deux points de trésorerie (caisse ou banque),
    à double validation : l'initiateur crée (sortie source), la destination valide
    (entrée effective). Toute validation crée une pièce comptable en attente."""
    __tablename__ = "transfert"
    id: Mapped[uuid.UUID] = pk()
    numero: Mapped[str] = mapped_column(String, unique=True)
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    source_type: Mapped[str] = mapped_column(String)   # 'caisse' | 'banque'
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    dest_type: Mapped[str] = mapped_column(String)
    dest_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    devise: Mapped[str] = mapped_column(String, default="USD")
    taux_jour: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    montant: Mapped[float] = mapped_column(Numeric(18, 2))
    montant_usd: Mapped[float] = mapped_column(Numeric(18, 2))
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    statut: Mapped[str] = mapped_column(String, default="a_valider")   # a_valider | valide | rejete
    initie_par: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateur.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valide_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    valide_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_rejet: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_mouvement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    dest_mouvement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class CompteBancaire(Base):
    __tablename__ = "compte_bancaire"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    banque: Mapped[str] = mapped_column(String)
    numero_compte: Mapped[str | None] = mapped_column(String, nullable=True)
    devise: Mapped[str] = mapped_column(String, default="USD")
    compte_comptable: Mapped[str | None] = mapped_column(String, nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)


class SessionCaisse(Base):
    """Journée de caisse : ouverture avec fond initial, clôture avec comptage."""
    __tablename__ = "session_caisse"
    id: Mapped[uuid.UUID] = pk()
    caisse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("caisse.id"))
    date_ouverture: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ouvert_par: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateur.id"))
    fond_initial_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    fond_initial_cdf: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    statut: Mapped[str] = mapped_column(String, default="ouverte")   # ouverte | cloturee
    date_cloture: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cloture_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    # Comptage de clôture (billetage physique par devise) + écart théorique/physique
    solde_theorique_usd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    solde_theorique_cdf: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    solde_physique_usd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    solde_physique_cdf: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    ecart_usd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    ecart_cdf: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    billetage_cloture: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"USD":{...},"CDF":{...}}
    commentaire_cloture: Mapped[str | None] = mapped_column(String, nullable=True)


class MouvementCaisse(Base):
    __tablename__ = "mouvement_caisse"
    id: Mapped[uuid.UUID] = pk()
    caisse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("caisse.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("session_caisse.id"), nullable=True)
    numero: Mapped[str | None] = mapped_column(String, nullable=True)     # n° du bon de caisse (BC-...)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)   # réf. réquisition (libre ou auto)
    billetage: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # {"100":2,"50":1,...} optionnel
    tiers_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tiers.id"), nullable=True)
    tiers_nom: Mapped[str | None] = mapped_column(String, nullable=True)  # bénéficiaire (sortie) / provenance (entrée)
    date_mouvement: Mapped[datetime] = mapped_column(Date, server_default=func.current_date())
    heure: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sens: Mapped[str] = mapped_column(String)
    nature: Mapped[str] = mapped_column(String)
    devise: Mapped[str] = mapped_column(String, default="USD")
    taux_jour: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    montant: Mapped[float] = mapped_column(Numeric(18, 2))
    montant_usd: Mapped[float] = mapped_column(Numeric(18, 2))
    reference_type: Mapped[str | None] = mapped_column(String, nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    libelle: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    __table_args__ = (CheckConstraint("sens IN ('entree','sortie')"),)


# â”€â”€ DÃ©caissement & avances â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class Requisition(Base):
    __tablename__ = "requisition"
    id: Mapped[uuid.UUID] = pk()
    numero: Mapped[str] = mapped_column(String, unique=True)
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("site.id"), nullable=True)
    initiateur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateur.id"))
    date_requisition: Mapped[datetime] = mapped_column(Date, server_default=func.current_date())
    objet: Mapped[str] = mapped_column(Text)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'avance' = avance à justifier (défaut) ; 'paiement_direct' = sur justificatif déjà fourni
    mode_decaissement: Mapped[str] = mapped_column(String, default="avance")
    # 'charge' = dépense/charge (défaut) ; 'marchandise' = achat de marchandises → stock
    nature: Mapped[str] = mapped_column(String, default="charge")
    priorite: Mapped[str] = mapped_column(String, default="normal")
    devise: Mapped[str] = mapped_column(String, default="USD")
    taux_jour: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    montant_total: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    montant_total_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    statut: Mapped[str] = mapped_column(String, default="brouillon")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lignes: Mapped[list["RequisitionLigne"]] = relationship(
        back_populates="requisition", cascade="all, delete-orphan")


class RequisitionLigne(Base):
    __tablename__ = "requisition_ligne"
    id: Mapped[uuid.UUID] = pk()
    requisition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requisition.id", ondelete="CASCADE"))
    ordre: Mapped[int] = mapped_column(Integer, default=0)
    compte_impute: Mapped[str | None] = mapped_column(String, nullable=True)
    code_article: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    unite: Mapped[str | None] = mapped_column(String, nullable=True)
    quantite: Mapped[float] = mapped_column(Numeric(18, 3), default=1)
    prix_unitaire: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    montant: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    devise: Mapped[str] = mapped_column(String, default="USD")
    montant_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    requisition: Mapped["Requisition"] = relationship(back_populates="lignes")


class PieceJointe(Base):
    __tablename__ = "piece_jointe"
    id: Mapped[uuid.UUID] = pk()
    document_type: Mapped[str] = mapped_column(String)   # 'requisition', 'justification', ...
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    nom_fichier: Mapped[str] = mapped_column(String)
    chemin_stockage: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    taille_octets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RequisitionCommentaire(Base):
    """Fil d'échange sur une réquisition (renvoi pour précisions, réponses)."""
    __tablename__ = "requisition_commentaire"
    id: Mapped[uuid.UUID] = pk()
    requisition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requisition.id", ondelete="CASCADE"))
    auteur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateur.id"))
    type: Mapped[str] = mapped_column(String, default="commentaire")  # precision_demandee | reponse | commentaire
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Validation(Base):
    __tablename__ = "validation"
    id: Mapped[uuid.UUID] = pk()
    document_type: Mapped[str] = mapped_column(String)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    etape: Mapped[str] = mapped_column(String)
    palier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("palier_validation.id"), nullable=True)
    role_attendu_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("role.id"), nullable=True)
    utilisateur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    decision: Mapped[str] = mapped_column(String, default="en_attente")
    mode: Mapped[str] = mapped_column(String, default="conjoint")
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    canal: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrdreDepense(Base):
    __tablename__ = "ordre_depense"
    id: Mapped[uuid.UUID] = pk()
    numero: Mapped[str] = mapped_column(String, unique=True)
    requisition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requisition.id"))
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    beneficiaire_tiers_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiers.id"))
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode_paiement: Mapped[str] = mapped_column(String, default="caisse")     # caisse | banque
    mode_decaissement: Mapped[str] = mapped_column(String, default="avance")  # avance | paiement_direct
    devise: Mapped[str] = mapped_column(String, default="USD")
    taux_jour: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    montant_autorise: Mapped[float] = mapped_column(Numeric(18, 2))
    montant_autorise_usd: Mapped[float] = mapped_column(Numeric(18, 2))
    montant_paye_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)   # cumul décaissé (partiels)
    montant_lettres: Mapped[str | None] = mapped_column(String, nullable=True)
    palier_applique: Mapped[str | None] = mapped_column(String, nullable=True)
    statut: Mapped[str] = mapped_column(String, default="a_valider")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BonReception(Base):
    __tablename__ = "bon_reception"
    id: Mapped[uuid.UUID] = pk()
    numero: Mapped[str] = mapped_column(String, unique=True)
    ordre_depense_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ordre_depense.id"))
    caisse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("caisse.id"), nullable=True)
    compte_bancaire_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("compte_bancaire.id"), nullable=True)
    receveur_tiers_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiers.id"))
    caissier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateur.id"))
    date_reception: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    mode: Mapped[str] = mapped_column(String, default="caisse")
    reference_paiement: Mapped[str | None] = mapped_column(String, nullable=True)  # n° OP / chèque (banque)
    devise: Mapped[str] = mapped_column(String, default="USD")
    taux_jour: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    montant: Mapped[float] = mapped_column(Numeric(18, 2))
    montant_usd: Mapped[float] = mapped_column(Numeric(18, 2))
    statut: Mapped[str] = mapped_column(String, default="emis")


class Avance(Base):
    __tablename__ = "avance"
    id: Mapped[uuid.UUID] = pk()
    numero: Mapped[str] = mapped_column(String, unique=True)
    ordre_depense_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ordre_depense.id"))
    bon_reception_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bon_reception.id"), nullable=True)
    beneficiaire_tiers_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiers.id"))
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    type_avance: Mapped[str | None] = mapped_column(String, nullable=True)
    devise: Mapped[str] = mapped_column(String, default="USD")
    montant_avance: Mapped[float] = mapped_column(Numeric(18, 2))
    montant_avance_usd: Mapped[float] = mapped_column(Numeric(18, 2))
    date_octroi: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delai_justif_heures: Mapped[int | None] = mapped_column(Integer, nullable=True)
    echeance_justif: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    statut: Mapped[str] = mapped_column(String, default="a_justifier")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Justification(Base):
    __tablename__ = "justification"
    id: Mapped[uuid.UUID] = pk()
    numero: Mapped[str] = mapped_column(String, unique=True)
    avance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("avance.id"))
    date_justification: Mapped[datetime] = mapped_column(Date, server_default=func.current_date())
    montant_justifie: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    montant_justifie_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    solde_retourne: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    solde_retourne_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    ecart_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    complement_demande: Mapped[bool] = mapped_column(Boolean, default=False)
    statut: Mapped[str] = mapped_column(String, default="soumise")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lignes: Mapped[list["JustificationLigne"]] = relationship(
        back_populates="justification", cascade="all, delete-orphan")


class JustificationLigne(Base):
    __tablename__ = "justification_ligne"
    id: Mapped[uuid.UUID] = pk()
    justification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("justification.id", ondelete="CASCADE"))
    date_achat: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    nature: Mapped[str] = mapped_column(String)
    compte_impute: Mapped[str | None] = mapped_column(String, nullable=True)
    fournisseur: Mapped[str | None] = mapped_column(String, nullable=True)
    num_piece: Mapped[str | None] = mapped_column(String, nullable=True)
    devise: Mapped[str] = mapped_column(String, default="USD")
    montant: Mapped[float] = mapped_column(Numeric(18, 2))
    montant_usd: Mapped[float] = mapped_column(Numeric(18, 2))
    a_piece_jointe: Mapped[bool] = mapped_column(Boolean, default=False)
    justification: Mapped["Justification"] = relationship(back_populates="lignes")


class BlocageBeneficiaire(Base):
    __tablename__ = "blocage_beneficiaire"
    id: Mapped[uuid.UUID] = pk()
    tiers_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiers.id"))
    avance_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("avance.id"), nullable=True)
    motif: Mapped[str] = mapped_column(Text)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    bloque_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    leve_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    leve_motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    leve_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    utilisateur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    action: Mapped[str] = mapped_column(String)
    table_cible: Mapped[str] = mapped_column(String)
    enregistrement_id: Mapped[str | None] = mapped_column(String, nullable=True)
    ancienne_valeur: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    nouvelle_valeur: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    adresse_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    horodatage: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Comptabilité OHADA ───────────────────────────────────────────────
class Exercice(Base):
    __tablename__ = "exercice"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    annee: Mapped[int] = mapped_column(Integer)
    date_debut: Mapped[datetime] = mapped_column(Date)
    date_fin: Mapped[datetime] = mapped_column(Date)
    statut: Mapped[str] = mapped_column(String, default="ouvert")
    __table_args__ = (UniqueConstraint("societe_id", "annee"),)


class Journal(Base):
    __tablename__ = "journal"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    code: Mapped[str] = mapped_column(String)
    libelle: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("societe_id", "code"),)


class Compte(Base):
    __tablename__ = "compte"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    numero: Mapped[str] = mapped_column(String)
    intitule: Mapped[str] = mapped_column(String)
    classe: Mapped[str | None] = mapped_column(String, nullable=True)
    sens_ohada: Mapped[str | None] = mapped_column(String, nullable=True)
    auxiliaire: Mapped[bool] = mapped_column(Boolean, default=False)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("societe_id", "numero"),)


class Ecriture(Base):
    __tablename__ = "ecriture"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    exercice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exercice.id"))
    journal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("journal.id"), nullable=True)
    numero: Mapped[str] = mapped_column(String)
    date_ecriture: Mapped[datetime] = mapped_column(Date)
    numero_piece: Mapped[str | None] = mapped_column(String, nullable=True)
    libelle: Mapped[str] = mapped_column(Text)
    type_operation: Mapped[str | None] = mapped_column(String, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    statut: Mapped[str] = mapped_column(String, default="valide")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lignes: Mapped[list["LigneEcriture"]] = relationship(
        back_populates="ecriture", cascade="all, delete-orphan")


class LigneEcriture(Base):
    __tablename__ = "ligne_ecriture"
    id: Mapped[uuid.UUID] = pk()
    ecriture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ecriture.id", ondelete="CASCADE"))
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    ordre: Mapped[int] = mapped_column(Integer, default=0)
    sens: Mapped[str] = mapped_column(String)
    compte_numero: Mapped[str] = mapped_column(String)
    tiers_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tiers.id"), nullable=True)
    montant_usd: Mapped[float] = mapped_column(Numeric(18, 2))
    devise_origine: Mapped[str] = mapped_column(String, default="USD")
    montant_origine: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    taux_jour: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    libelle_ligne: Mapped[str | None] = mapped_column(String, nullable=True)
    lettrage_code: Mapped[str | None] = mapped_column(String, nullable=True)
    rapprochement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rapprochement_bancaire.id"), nullable=True)
    __table_args__ = (CheckConstraint("sens IN ('D','C')"),)
    ecriture: Mapped["Ecriture"] = relationship(back_populates="lignes")


class RapprochementBancaire(Base):
    __tablename__ = "rapprochement_bancaire"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    compte: Mapped[str] = mapped_column(String)               # compte de banque (ex. 521)
    date_releve: Mapped[datetime] = mapped_column(Date)
    solde_releve_usd: Mapped[float] = mapped_column(Numeric(18, 2))
    solde_comptable_usd: Mapped[float] = mapped_column(Numeric(18, 2))   # solde livre (toutes lignes)
    solde_rapproche_usd: Mapped[float] = mapped_column(Numeric(18, 2))   # cumul pointé (D-C)
    ecart_usd: Mapped[float] = mapped_column(Numeric(18, 2))
    statut: Mapped[str] = mapped_column(String, default="cloture")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Comptabilité analytique (axes / sections / ventilation) ──────────
class AxeAnalytique(Base):
    __tablename__ = "axe_analytique"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    code: Mapped[str] = mapped_column(String)
    libelle: Mapped[str] = mapped_column(String)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("societe_id", "code"),)


class SectionAnalytique(Base):
    __tablename__ = "section_analytique"
    id: Mapped[uuid.UUID] = pk()
    axe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("axe_analytique.id"))
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    code: Mapped[str] = mapped_column(String)
    libelle: Mapped[str] = mapped_column(String)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)


class VentilationAnalytique(Base):
    __tablename__ = "ventilation_analytique"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    ligne_ecriture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ligne_ecriture.id", ondelete="CASCADE"))
    axe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("axe_analytique.id"))
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("section_analytique.id"))
    montant_usd: Mapped[float] = mapped_column(Numeric(18, 2))


# ── Cycle commercial : articles, stock, factures (achats / ventes) ───
class Article(Base):
    __tablename__ = "article"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    code: Mapped[str] = mapped_column(String)
    designation: Mapped[str] = mapped_column(String)
    unite: Mapped[str] = mapped_column(String, default="unité")
    prix_achat: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    prix_vente: Mapped[float] = mapped_column(Numeric(18, 2), default=0)   # prix de vente par défaut
    assujetti_tva: Mapped[bool] = mapped_column(Boolean, default=True)     # soumis à la TVA ?
    taux_tva: Mapped[float] = mapped_column(Numeric(6, 2), default=16)
    categorie: Mapped[str | None] = mapped_column(String, nullable=True)
    code_barres: Mapped[str | None] = mapped_column(String, nullable=True)
    taux_commission: Mapped[float] = mapped_column(Numeric(6, 2), default=0)   # % commission vendeur (POS)
    points_fidelite: Mapped[float] = mapped_column(Numeric(10, 2), default=0)  # points fidélité / unité vendue
    compte_achat: Mapped[str] = mapped_column(String, default="601")
    compte_vente: Mapped[str] = mapped_column(String, default="701")
    compte_stock: Mapped[str] = mapped_column(String, default="31")
    gere_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    stock_qte: Mapped[float] = mapped_column(Numeric(18, 3), default=0)      # quantité en stock
    stock_valeur: Mapped[float] = mapped_column(Numeric(18, 2), default=0)   # valeur (pour CUMP)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("societe_id", "code"),)


class MouvementStock(Base):
    __tablename__ = "mouvement_stock"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("article.id"))
    date_mvt: Mapped[datetime] = mapped_column(Date)
    sens: Mapped[str] = mapped_column(String)             # entree | sortie | ajustement
    qte: Mapped[float] = mapped_column(Numeric(18, 3))
    cout_unitaire: Mapped[float] = mapped_column(Numeric(18, 4))
    valeur: Mapped[float] = mapped_column(Numeric(18, 2))
    type_operation: Mapped[str] = mapped_column(String)   # achat | vente | ajustement
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Facture(Base):
    __tablename__ = "facture"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    type: Mapped[str] = mapped_column(String)             # achat | vente
    numero: Mapped[str] = mapped_column(String)
    tiers_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiers.id"))
    date_facture: Mapped[datetime] = mapped_column(Date)
    echeance: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)    # n° facture fournisseur
    total_ht: Mapped[float] = mapped_column(Numeric(18, 2), default=0)     # articles HT
    total_frais: Mapped[float] = mapped_column(Numeric(18, 2), default=0)  # frais annexes HT
    total_tva: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total_ttc: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    repartition: Mapped[str] = mapped_column(String, default="quantite")   # quantite | valeur
    cout_ventes: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)   # ventes : coût sorti
    marge: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)         # ventes : marge
    remise_totale: Mapped[float] = mapped_column(Numeric(18, 2), default=0)     # remises accordées (POS)
    note: Mapped[str | None] = mapped_column(String, nullable=True)             # note ticket (POS)
    statut: Mapped[str] = mapped_column(String, default="validee")
    intra_groupe: Mapped[bool] = mapped_column(Boolean, default=False)
    reception_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reception.id"), nullable=True)
    point_vente_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("point_vente.id"), nullable=True)
    origine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facture.id"), nullable=True)  # avoir → facture d'origine
    devis_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devis.id"), nullable=True)      # facture issue d'une commande client
    facture_liee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facture.id"), nullable=True)  # miroir intersociété (vente ↔ achat)
    pos_recu_usd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)     # espèces reçues (équiv. USD)
    pos_monnaie_usd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)  # monnaie rendue (équiv. USD)
    ecriture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ecriture.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lignes: Mapped[list["LigneFacture"]] = relationship(
        back_populates="facture", cascade="all, delete-orphan")


class LigneFacture(Base):
    __tablename__ = "ligne_facture"
    id: Mapped[uuid.UUID] = pk()
    facture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facture.id", ondelete="CASCADE"))
    article_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("article.id"), nullable=True)
    designation: Mapped[str] = mapped_column(String)
    qte: Mapped[float] = mapped_column(Numeric(18, 3), default=1)
    prix_unitaire: Mapped[float] = mapped_column(Numeric(18, 2), default=0)   # prix BRUT (avant remise)
    remise_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)       # remise ligne+globale combinée (POS)
    taux_tva: Mapped[float] = mapped_column(Numeric(6, 2), default=16)
    montant_ht: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    montant_tva: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    frais_reparti: Mapped[float] = mapped_column(Numeric(18, 2), default=0)   # quote-part des frais annexes
    cout_entree: Mapped[float] = mapped_column(Numeric(18, 2), default=0)     # coût d'acquisition (HT + frais)
    origine_ligne_id: Mapped[uuid.UUID | None] = mapped_column(               # avoir → ligne vendue d'origine
        ForeignKey("ligne_facture.id"), nullable=True)
    facture: Mapped["Facture"] = relationship(back_populates="lignes")


# ── Transport (KAKO Logistique) : flotte, courses, contrats ──────────
class Camion(Base):
    """Camion de la flotte — propre ou sous-traité (camion d'un tiers)."""
    __tablename__ = "camion"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    immatriculation: Mapped[str] = mapped_column(String)
    marque: Mapped[str | None] = mapped_column(String, nullable=True)
    capacite_tonnes: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    consommation_l_100km: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    type: Mapped[str] = mapped_column(String, default="propre")   # propre | sous_traite
    proprietaire_tiers_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tiers.id"), nullable=True)
    # rémunération par défaut du sous-traitant (modifiable course par course)
    remuneration_mode: Mapped[str | None] = mapped_column(String, nullable=True)   # forfait | pourcentage
    remuneration_valeur: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    statut: Mapped[str] = mapped_column(String, default="disponible")  # disponible | en_course | immobilise
    motif_immobilisation: Mapped[str | None] = mapped_column(String, nullable=True)
    immobilise_depuis: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("societe_id", "immatriculation"),)


class Chauffeur(Base):
    __tablename__ = "chauffeur"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    nom: Mapped[str] = mapped_column(String)
    telephone: Mapped[str | None] = mapped_column(String, nullable=True)
    numero_permis: Mapped[str | None] = mapped_column(String, nullable=True)
    tiers_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tiers.id"), nullable=True)  # pour ses avances
    actif: Mapped[bool] = mapped_column(Boolean, default=True)


class ContratTransport(Base):
    """Contrat-cadre client (ex. grand contrat) — grille tarifaire par trajet."""
    __tablename__ = "contrat_transport"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    numero: Mapped[str] = mapped_column(String)
    libelle: Mapped[str] = mapped_column(String)
    client_tiers_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiers.id"))
    date_debut: Mapped[datetime] = mapped_column(Date)
    date_fin: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    statut: Mapped[str] = mapped_column(String, default="actif")   # actif | suspendu | clos
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    tarifs: Mapped[list["TarifContrat"]] = relationship(
        back_populates="contrat", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("societe_id", "numero"),)


class TarifContrat(Base):
    __tablename__ = "tarif_contrat"
    id: Mapped[uuid.UUID] = pk()
    contrat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contrat_transport.id", ondelete="CASCADE"))
    trajet: Mapped[str] = mapped_column(String)                    # ex. « Likasi → Kolwezi »
    mode: Mapped[str] = mapped_column(String, default="tonne")     # tonne | voyage
    prix: Mapped[float] = mapped_column(Numeric(18, 2))            # USD / tonne ou forfait / voyage
    contrat: Mapped["ContratTransport"] = relationship(back_populates="tarifs")


class Course(Base):
    """Fiche Course (PROC-KL-01→04) : de la demande de transport à la facturation."""
    __tablename__ = "course"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    numero: Mapped[str] = mapped_column(String)
    date_course: Mapped[datetime] = mapped_column(Date)            # départ prévu
    client_tiers_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiers.id"))
    contrat_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contrat_transport.id"), nullable=True)
    camion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("camion.id"), nullable=True)  # null tant que « demande »
    chauffeur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chauffeur.id"), nullable=True)
    origine: Mapped[str] = mapped_column(String)
    destination: Mapped[str] = mapped_column(String)
    marchandise: Mapped[str] = mapped_column(String)
    tonnage_prevu: Mapped[float] = mapped_column(Numeric(12, 3), default=0)
    tonnage_livre: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    unite: Mapped[str] = mapped_column(String, default="tonnes")   # sacs, pièces, fûts, tonnes…
    tarif_mode: Mapped[str] = mapped_column(String, default="tonne")   # tonne | voyage
    prix_unitaire: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    # demande (PO intersociété en attente) | brouillon | validee | en_cours | livree | facturee | annulee
    statut: Mapped[str] = mapped_column(String, default="brouillon")
    commande_origine_id: Mapped[uuid.UUID | None] = mapped_column(               # PO qui a déclenché la demande
        ForeignKey("commande.id"), nullable=True)
    heure_depart: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heure_retour: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    incidents: Mapped[str | None] = mapped_column(Text, nullable=True)
    requisition_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("requisition.id"), nullable=True)
    # sous-traitance (camion tiers) : mode/valeur figés à la clôture
    st_mode: Mapped[str | None] = mapped_column(String, nullable=True)         # forfait | pourcentage
    st_valeur: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    st_cout: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    st_facture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facture.id"), nullable=True)
    facture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facture.id"), nullable=True)
    valide_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("societe_id", "numero"),)


class ReceptionInter(Base):
    """Réception PHYSIQUE par l'acheteur d'un PO intersociété : quantités en bon
    état, en mauvais état et manquantes. Conditionne la facturation du vendeur
    et du transporteur ; les manquants sont supportés par le transporteur au
    prix d'achat (règle du groupe)."""
    __tablename__ = "reception_inter"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))   # acheteur
    commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commande.id"))
    numero: Mapped[str] = mapped_column(String)
    date_reception: Mapped[datetime] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    # L'acheteur constate, le TRANSPORTEUR confirme (les manquants sont à sa charge)
    statut: Mapped[str] = mapped_column(String, default="confirmee")   # a_confirmer | confirmee
    confirme_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    date_confirmation: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lignes: Mapped[list["LigneReceptionInter"]] = relationship(
        back_populates="reception", cascade="all, delete-orphan")


class LigneReceptionInter(Base):
    __tablename__ = "ligne_reception_inter"
    id: Mapped[uuid.UUID] = pk()
    reception_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reception_inter.id", ondelete="CASCADE"))
    ligne_commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ligne_commande.id"))
    qte_bon: Mapped[float] = mapped_column(Numeric(18, 3), default=0)
    qte_mauvais: Mapped[float] = mapped_column(Numeric(18, 3), default=0)
    qte_manquante: Mapped[float] = mapped_column(Numeric(18, 3), default=0)
    reception: Mapped["ReceptionInter"] = relationship(back_populates="lignes")


class CourseRequisition(Base):
    """Réquisitions (carburant, péages, frais) rattachées à une course — à tout
    moment, y compris en cours d'exécution (dépenses supplémentaires en route)."""
    __tablename__ = "course_requisition"
    id: Mapped[uuid.UUID] = pk()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("course.id", ondelete="CASCADE"))
    requisition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requisition.id"))
    __table_args__ = (UniqueConstraint("course_id", "requisition_id"),)


class InterventionCamion(Base):
    """Maintenance (PROC-KL-05/06) : entretien, réparation, immobilisation."""
    __tablename__ = "intervention_camion"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    camion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("camion.id"))
    numero: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String, default="reparation")  # entretien | reparation | controle | accident
    statut: Mapped[str] = mapped_column(String, default="signalee")  # signalee | en_cours | terminee
    description: Mapped[str] = mapped_column(Text)
    prestataire: Mapped[str | None] = mapped_column(String, nullable=True)
    cout_estime: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    cout_reel: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    immobilise: Mapped[bool] = mapped_column(Boolean, default=True)  # camion hors service pendant l'intervention
    date_signalement: Mapped[datetime] = mapped_column(Date)
    date_fin: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    requisition_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("requisition.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("societe_id", "numero"),)


# ── Cycle de vente : devis → commande client → livraison → facture ───
class Devis(Base):
    """Devis client ; une fois confirmé, il devient la commande client
    (même document, statuts successifs — comme le sale.order d'Odoo)."""
    __tablename__ = "devis"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    numero: Mapped[str] = mapped_column(String)
    tiers_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiers.id"))       # client
    date_devis: Mapped[datetime] = mapped_column(Date)
    validite: Mapped[datetime | None] = mapped_column(Date, nullable=True)    # date limite d'acceptation
    statut: Mapped[str] = mapped_column(String, default="brouillon")  # brouillon|envoye|confirme|annule
    remise_globale_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    total_ht: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total_tva: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total_ttc: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    remise_totale: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    conditions: Mapped[str | None] = mapped_column(String, nullable=True)     # conditions de paiement/livraison
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_producteur: Mapped[str | None] = mapped_column(String, nullable=True)  # n° commande du producteur
    # (logiciel du fournisseur du vendeur, ex. GCK) — clé de réconciliation, sur tous les documents
    date_confirmation: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commande_origine_id: Mapped[uuid.UUID | None] = mapped_column(               # PO intersociété d'origine
        ForeignKey("commande.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lignes: Mapped[list["LigneDevis"]] = relationship(
        back_populates="devis", cascade="all, delete-orphan", order_by="LigneDevis.ordre")
    __table_args__ = (UniqueConstraint("societe_id", "numero"),)


class LigneDevis(Base):
    __tablename__ = "ligne_devis"
    id: Mapped[uuid.UUID] = pk()
    devis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devis.id", ondelete="CASCADE"))
    ordre: Mapped[int] = mapped_column(Numeric(6, 0), default=0)
    article_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("article.id"), nullable=True)
    designation: Mapped[str] = mapped_column(String)
    qte: Mapped[float] = mapped_column(Numeric(18, 3), default=1)
    prix_unitaire: Mapped[float] = mapped_column(Numeric(18, 2), default=0)   # prix BRUT
    remise_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)       # remise ligne+globale combinée
    taux_tva: Mapped[float] = mapped_column(Numeric(6, 2), default=16)
    montant_ht: Mapped[float] = mapped_column(Numeric(18, 2), default=0)      # net de remise
    montant_tva: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    qte_livree: Mapped[float] = mapped_column(Numeric(18, 3), default=0)
    qte_facturee: Mapped[float] = mapped_column(Numeric(18, 3), default=0)
    devis: Mapped["Devis"] = relationship(back_populates="lignes")


class Livraison(Base):
    """Bon de livraison (BL) — sortie de stock au CUMP, livraisons partielles."""
    __tablename__ = "livraison"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    devis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devis.id"))
    numero: Mapped[str] = mapped_column(String)
    date_livraison: Mapped[datetime] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lignes: Mapped[list["LigneLivraison"]] = relationship(
        back_populates="livraison", cascade="all, delete-orphan")


class LigneLivraison(Base):
    __tablename__ = "ligne_livraison"
    id: Mapped[uuid.UUID] = pk()
    livraison_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("livraison.id", ondelete="CASCADE"))
    ligne_devis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ligne_devis.id"))
    article_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("article.id"), nullable=True)
    designation: Mapped[str] = mapped_column(String)
    qte: Mapped[float] = mapped_column(Numeric(18, 3))
    cout_unitaire: Mapped[float] = mapped_column(Numeric(18, 4), default=0)   # CUMP à la sortie
    valeur: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    livraison: Mapped["Livraison"] = relationship(back_populates="lignes")


class PaiementFacture(Base):
    """Règlement d'un ticket POS — une vente peut mélanger plusieurs modes
    (espèces USD/CDF, mobile money, banque, crédit client)."""
    __tablename__ = "paiement_facture"
    id: Mapped[uuid.UUID] = pk()
    facture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facture.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String)                 # espece | mobile_money | banque | credit
    devise: Mapped[str] = mapped_column(String, default="USD")
    montant: Mapped[float] = mapped_column(Numeric(18, 2))    # dans la devise du paiement
    taux_jour: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    montant_usd: Mapped[float] = mapped_column(Numeric(18, 2))
    reference: Mapped[str | None] = mapped_column(String, nullable=True)   # n° transaction MM / banque
    compte: Mapped[str | None] = mapped_column(String, nullable=True)      # compte de trésorerie mouvementé
    __table_args__ = (CheckConstraint("mode IN ('espece','mobile_money','banque','credit')"),)


class FraisFacture(Base):
    """Frais accessoires d'achat (transport, douane…) répartis sur les articles."""
    __tablename__ = "frais_facture"
    id: Mapped[uuid.UUID] = pk()
    facture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facture.id", ondelete="CASCADE"))
    libelle: Mapped[str] = mapped_column(String)
    compte: Mapped[str] = mapped_column(String, default="6085")   # frais sur achats 6085 (SYSCOHADA)
    montant_ht: Mapped[float] = mapped_column(Numeric(18, 2))
    taux_tva: Mapped[float] = mapped_column(Numeric(6, 2), default=16)
    montant_tva: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    # Contrepartie du frais (peut différer du fournisseur des marchandises)
    mode: Mapped[str] = mapped_column(String, default="credit")   # credit | banque | caisse
    tiers_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tiers.id"), nullable=True)   # si crédit (fournisseur du frais)
    compte_reglement: Mapped[str | None] = mapped_column(String, nullable=True)   # compte trésorerie si banque/caisse
    caisse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("caisse.id"), nullable=True)


# ── Circuit 2 : achat en gros (commande → réception → facture) ───────
class Commande(Base):
    __tablename__ = "commande"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    numero: Mapped[str] = mapped_column(String)
    tiers_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiers.id"))   # fournisseur
    date_commande: Mapped[datetime] = mapped_column(Date)
    date_livraison_prevue: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    reference_fournisseur: Mapped[str | None] = mapped_column(String, nullable=True)
    total_ht: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    intra_groupe: Mapped[bool] = mapped_column(Boolean, default=False)
    statut: Mapped[str] = mapped_column(String, default="envoyee")  # envoyee|receptionnee|soldee|annulee
    # Commande intersociété : détails logistiques + documents miroir
    destination: Mapped[str | None] = mapped_column(String, nullable=True)      # lieu de livraison souhaité
    transporteur_societe_id: Mapped[uuid.UUID | None] = mapped_column(          # transporteur du groupe choisi
        ForeignKey("societe.id"), nullable=True)
    devis_lie_id: Mapped[uuid.UUID | None] = mapped_column(                     # commande client miroir chez le vendeur
        ForeignKey("devis.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lignes: Mapped[list["LigneCommande"]] = relationship(
        back_populates="commande", cascade="all, delete-orphan")


class LigneCommande(Base):
    __tablename__ = "ligne_commande"
    id: Mapped[uuid.UUID] = pk()
    commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commande.id", ondelete="CASCADE"))
    article_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("article.id"), nullable=True)
    designation: Mapped[str] = mapped_column(String)
    qte: Mapped[float] = mapped_column(Numeric(18, 3), default=1)
    qte_recue: Mapped[float] = mapped_column(Numeric(18, 3), default=0)
    prix_unitaire: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    taux_tva: Mapped[float] = mapped_column(Numeric(6, 2), default=16)
    commande: Mapped["Commande"] = relationship(back_populates="lignes")


class Reception(Base):
    __tablename__ = "reception"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    numero: Mapped[str] = mapped_column(String)
    commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commande.id"))
    date_reception: Mapped[datetime] = mapped_column(Date)
    total_valeur: Mapped[float] = mapped_column(Numeric(18, 2), default=0)   # coût d'acquisition entré
    total_frais: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    repartition: Mapped[str] = mapped_column(String, default="quantite")
    statut: Mapped[str] = mapped_column(String, default="recue")   # recue | facturee
    ecriture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ecriture.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lignes: Mapped[list["LigneReception"]] = relationship(
        back_populates="reception", cascade="all, delete-orphan")


class LigneReception(Base):
    __tablename__ = "ligne_reception"
    id: Mapped[uuid.UUID] = pk()
    reception_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reception.id", ondelete="CASCADE"))
    ligne_commande_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ligne_commande.id"), nullable=True)
    article_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("article.id"), nullable=True)
    designation: Mapped[str] = mapped_column(String)
    qte: Mapped[float] = mapped_column(Numeric(18, 3))
    prix_unitaire: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    taux_tva: Mapped[float] = mapped_column(Numeric(6, 2), default=16)
    montant_ht: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    frais_reparti: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    cout: Mapped[float] = mapped_column(Numeric(18, 2), default=0)   # montant_ht + frais_reparti
    compte_stock: Mapped[str] = mapped_column(String, default="31")
    reception: Mapped["Reception"] = relationship(back_populates="lignes")


class FraisReception(Base):
    __tablename__ = "frais_reception"
    id: Mapped[uuid.UUID] = pk()
    reception_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reception.id", ondelete="CASCADE"))
    libelle: Mapped[str] = mapped_column(String)
    compte: Mapped[str] = mapped_column(String, default="6085")   # frais sur achats (SYSCOHADA)
    montant_ht: Mapped[float] = mapped_column(Numeric(18, 2))
    taux_tva: Mapped[float] = mapped_column(Numeric(6, 2), default=16)
    montant_tva: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    # Contrepartie du frais (comme FraisFacture) : dette fournisseur du frais / banque / caisse
    mode: Mapped[str] = mapped_column(String, default="credit")   # credit | banque | caisse
    tiers_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tiers.id"), nullable=True)
    compte_reglement: Mapped[str | None] = mapped_column(String, nullable=True)
    caisse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("caisse.id"), nullable=True)


# ── Listes de prix & points de vente (préparation POS) ───────────────
class ListePrix(Base):
    __tablename__ = "liste_prix"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    code: Mapped[str] = mapped_column(String)
    libelle: Mapped[str] = mapped_column(String)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("societe_id", "code"),)


class TarifArticle(Base):
    __tablename__ = "tarif_article"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    liste_prix_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("liste_prix.id", ondelete="CASCADE"))
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("article.id", ondelete="CASCADE"))
    prix: Mapped[float] = mapped_column(Numeric(18, 2))
    __table_args__ = (UniqueConstraint("liste_prix_id", "article_id"),)


class PointVente(Base):
    __tablename__ = "point_vente"
    id: Mapped[uuid.UUID] = pk()
    societe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societe.id"))
    code: Mapped[str] = mapped_column(String)
    libelle: Mapped[str] = mapped_column(String)
    liste_prix_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("liste_prix.id"), nullable=True)
    caisse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("caisse.id"), nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("societe_id", "code"),)

