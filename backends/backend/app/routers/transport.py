"""Module Transport — KAKO Logistique (PROC-KL-01 → 06).

Flotte (camions propres et sous-traités), fiches de course numériques,
contrats-cadres avec grilles tarifaires, sous-traitance (forfait ou % du prix
client), facturation externe (706) ou intersociété (facture miroir), et
maintenance avec immobilisation bloquante.

Garde-fous issus du manuel de procédures :
- un camion immobilisé ou déjà en course est inaffectable (PROC-KL-01) ;
- pas de départ tant que l'avance carburant liée n'est pas décaissée (PROC-KL-02) ;
- la facturation ne porte que sur des courses livrées (PROC-KL-04).
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import comptabilite, models, services
from ..database import get_db
from ..deps import assert_acces_societe, assert_role, get_current_user

router = APIRouter(prefix="/api/transport", tags=["transport"])
ROLES = {"COMPTABLE", "DFI", "ASSISTANT_TECH", "DG"}


def _role_validation(db: Session, societe_id) -> str:
    """Rôle habilité à valider les fiches de course — configurable par société
    (défaut : DFI, conformément à PROC-KL-01, mais délégable)."""
    return services.get_parametre(db, "transport.role_validation", societe_id, "DFI")


@router.get("/config")
def config_transport(societe_id: uuid.UUID, db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    tous = [{"code": r.code, "libelle": r.libelle}
            for r in db.execute(select(models.Role).order_by(models.Role.code)).scalars()]
    return {"role_validation": _role_validation(db, societe_id), "roles": tous}


class ConfigTransportIn(BaseModel):
    role_validation: str = Field(min_length=2)


@router.post("/config")
def maj_config_transport(societe_id: uuid.UUID, payload: ConfigTransportIn,
                         db: Session = Depends(get_db),
                         user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, {"DFI", "PRESIDENT", "ADMIN_SYS"})
    code = payload.role_validation.strip().upper()
    if not db.execute(select(models.Role).where(models.Role.code == code)).scalars().first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Rôle {code} inconnu.")
    p = db.execute(select(models.Parametre).where(
        models.Parametre.cle == "transport.role_validation",
        models.Parametre.societe_id == societe_id)).scalars().first()
    if p:
        p.valeur = code
    else:
        db.add(models.Parametre(societe_id=societe_id, cle="transport.role_validation",
                                valeur=code, type_valeur="string",
                                description="Rôle validateur des fiches de course"))
    services.enregistrer_audit(db, user.id, "CONFIG", "transport", None, None,
                               {"role_validation": code})
    db.commit()
    return {"role_validation": code}


# ═══ Flotte ══════════════════════════════════════════════════════════
class CamionIn(BaseModel):
    immatriculation: str = Field(min_length=2)
    marque: str | None = None
    capacite_tonnes: float = 0
    consommation_l_100km: float | None = None
    type: str = Field(default="propre", pattern="^(propre|sous_traite)$")
    proprietaire_tiers_id: uuid.UUID | None = None
    remuneration_mode: str | None = Field(default=None, pattern="^(forfait|pourcentage)$")
    remuneration_valeur: float | None = None


class CamionMaj(BaseModel):
    marque: str | None = None
    capacite_tonnes: float | None = None
    consommation_l_100km: float | None = None
    proprietaire_tiers_id: uuid.UUID | None = None
    remuneration_mode: str | None = Field(default=None, pattern="^(forfait|pourcentage)$")
    remuneration_valeur: float | None = None
    actif: bool | None = None


def _camion_dict(db: Session, c: models.Camion) -> dict:
    prop = db.get(models.Tiers, c.proprietaire_tiers_id) if c.proprietaire_tiers_id else None
    return {"id": str(c.id), "immatriculation": c.immatriculation, "marque": c.marque,
            "capacite_tonnes": float(c.capacite_tonnes or 0),
            "consommation_l_100km": float(c.consommation_l_100km) if c.consommation_l_100km else None,
            "type": c.type, "proprietaire": prop.nom if prop else None,
            "proprietaire_tiers_id": str(c.proprietaire_tiers_id) if c.proprietaire_tiers_id else None,
            "remuneration_mode": c.remuneration_mode,
            "remuneration_valeur": float(c.remuneration_valeur) if c.remuneration_valeur is not None else None,
            "statut": c.statut, "motif_immobilisation": c.motif_immobilisation,
            "immobilise_depuis": c.immobilise_depuis.isoformat() if c.immobilise_depuis else None,
            "actif": bool(c.actif)}


@router.get("/camions")
def lister_camions(societe_id: uuid.UUID, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    cs = db.execute(select(models.Camion).where(models.Camion.societe_id == societe_id)
                    .order_by(models.Camion.immatriculation)).scalars().all()
    return [_camion_dict(db, c) for c in cs]


@router.post("/camions", status_code=status.HTTP_201_CREATED)
def creer_camion(societe_id: uuid.UUID, payload: CamionIn, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    if payload.type == "sous_traite" and not payload.proprietaire_tiers_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Un camion sous-traité doit avoir un propriétaire (tiers fournisseur).")
    immat = payload.immatriculation.strip().upper()
    if db.execute(select(models.Camion).where(models.Camion.societe_id == societe_id,
                                              models.Camion.immatriculation == immat)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Le camion {immat} existe déjà.")
    c = models.Camion(societe_id=societe_id, immatriculation=immat, marque=payload.marque,
                      capacite_tonnes=payload.capacite_tonnes,
                      consommation_l_100km=payload.consommation_l_100km,
                      type=payload.type, proprietaire_tiers_id=payload.proprietaire_tiers_id,
                      remuneration_mode=payload.remuneration_mode,
                      remuneration_valeur=payload.remuneration_valeur)
    db.add(c)
    db.commit()
    return _camion_dict(db, c)


@router.patch("/camions/{camion_id}")
def maj_camion(camion_id: uuid.UUID, payload: CamionMaj, db: Session = Depends(get_db),
               user: models.Utilisateur = Depends(get_current_user)):
    c = db.get(models.Camion, camion_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camion introuvable.")
    roles = assert_acces_societe(db, user, c.societe_id)
    assert_role(roles, ROLES)
    for f in ("marque", "capacite_tonnes", "consommation_l_100km", "proprietaire_tiers_id",
              "remuneration_mode", "remuneration_valeur", "actif"):
        v = getattr(payload, f)
        if v is not None:
            setattr(c, f, v)
    db.commit()
    return _camion_dict(db, c)


# ═══ Chauffeurs ══════════════════════════════════════════════════════
class ChauffeurIn(BaseModel):
    nom: str = Field(min_length=2)
    telephone: str | None = None
    numero_permis: str | None = None


@router.get("/chauffeurs")
def lister_chauffeurs(societe_id: uuid.UUID, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    return [{"id": str(c.id), "nom": c.nom, "telephone": c.telephone,
             "numero_permis": c.numero_permis, "actif": bool(c.actif)}
            for c in db.execute(select(models.Chauffeur).where(
                models.Chauffeur.societe_id == societe_id,
                models.Chauffeur.actif.is_(True)).order_by(models.Chauffeur.nom)).scalars()]


@router.post("/chauffeurs", status_code=status.HTTP_201_CREATED)
def creer_chauffeur(societe_id: uuid.UUID, payload: ChauffeurIn, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    # tiers « personnel » associé — permet les avances à justifier du chauffeur
    tiers = models.Tiers(societe_id=societe_id, type="personnel",
                         code=f"CHF-{payload.nom.strip().upper()[:16]}", nom=payload.nom.strip())
    db.add(tiers)
    db.flush()
    c = models.Chauffeur(societe_id=societe_id, nom=payload.nom.strip(),
                         telephone=payload.telephone, numero_permis=payload.numero_permis,
                         tiers_id=tiers.id)
    db.add(c)
    db.commit()
    return {"id": str(c.id), "nom": c.nom}


# ═══ Contrats de transport ═══════════════════════════════════════════
class TarifIn(BaseModel):
    trajet: str = Field(min_length=2)
    mode: str = Field(default="tonne", pattern="^(tonne|voyage)$")
    prix: float = Field(gt=0)


class ContratIn(BaseModel):
    libelle: str = Field(min_length=2)
    client_tiers_id: uuid.UUID
    date_debut: date
    date_fin: date | None = None
    note: str | None = None
    tarifs: list[TarifIn] = []


def _contrat_dict(db: Session, c: models.ContratTransport) -> dict:
    t = db.get(models.Tiers, c.client_tiers_id)
    nb = db.execute(select(func.count()).select_from(models.Course).where(
        models.Course.contrat_id == c.id)).scalar() or 0
    return {"id": str(c.id), "numero": c.numero, "libelle": c.libelle,
            "client": t.nom if t else None, "client_tiers_id": str(c.client_tiers_id),
            "intra_groupe": bool(t and t.societe_liee_id),
            "date_debut": c.date_debut.isoformat(),
            "date_fin": c.date_fin.isoformat() if c.date_fin else None,
            "statut": c.statut, "note": c.note, "nb_courses": nb,
            "tarifs": [{"id": str(x.id), "trajet": x.trajet, "mode": x.mode, "prix": float(x.prix)}
                       for x in c.tarifs]}


@router.get("/contrats")
def lister_contrats(societe_id: uuid.UUID, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    cs = db.execute(select(models.ContratTransport).where(
        models.ContratTransport.societe_id == societe_id)
        .order_by(models.ContratTransport.created_at.desc())).scalars().all()
    return [_contrat_dict(db, c) for c in cs]


@router.post("/contrats", status_code=status.HTTP_201_CREATED)
def creer_contrat(societe_id: uuid.UUID, payload: ContratIn, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    societe = db.get(models.Societe, societe_id)
    tiers = db.get(models.Tiers, payload.client_tiers_id)
    if not tiers or tiers.type != "client":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sélectionnez un client.")
    c = models.ContratTransport(
        societe_id=societe_id,
        numero=services.next_numero(db, "contrat_transport", payload.date_debut.year,
                                    societe.code, societe.id),
        libelle=payload.libelle.strip(), client_tiers_id=tiers.id,
        date_debut=payload.date_debut, date_fin=payload.date_fin,
        note=(payload.note or "").strip() or None, created_by=user.id)
    for t in payload.tarifs:
        c.tarifs.append(models.TarifContrat(trajet=t.trajet.strip(), mode=t.mode, prix=t.prix))
    db.add(c)
    db.commit()
    return _contrat_dict(db, c)


@router.put("/contrats/{contrat_id}")
def modifier_contrat(contrat_id: uuid.UUID, payload: ContratIn, db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    c = db.get(models.ContratTransport, contrat_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contrat introuvable.")
    roles = assert_acces_societe(db, user, c.societe_id)
    assert_role(roles, ROLES)
    c.libelle = payload.libelle.strip()
    c.client_tiers_id = payload.client_tiers_id
    c.date_debut, c.date_fin = payload.date_debut, payload.date_fin
    c.note = (payload.note or "").strip() or None
    c.tarifs.clear()
    for t in payload.tarifs:
        c.tarifs.append(models.TarifContrat(trajet=t.trajet.strip(), mode=t.mode, prix=t.prix))
    db.commit()
    return _contrat_dict(db, c)


# ═══ Fiches de course ════════════════════════════════════════════════
class CourseIn(BaseModel):
    client_tiers_id: uuid.UUID
    contrat_id: uuid.UUID | None = None
    camion_id: uuid.UUID
    chauffeur_id: uuid.UUID | None = None
    date_course: date | None = None
    origine: str = Field(min_length=2)
    destination: str = Field(min_length=2)
    marchandise: str = Field(min_length=2)
    tonnage_prevu: float = Field(gt=0)
    unite: str = "tonnes"                        # sacs, pièces, fûts, tonnes…
    tarif_mode: str = Field(default="tonne", pattern="^(tonne|voyage)$")
    prix_unitaire: float = Field(ge=0)
    requisition_id: uuid.UUID | None = None      # réquisition carburant/frais liée


class RetourIn(BaseModel):
    tonnage_livre: float = Field(gt=0)
    incidents: str | None = None
    # sous-traitance : figée au retour (défaut = paramètres du camion)
    st_mode: str | None = Field(default=None, pattern="^(forfait|pourcentage)$")
    st_valeur: float | None = None


def _recette(c: models.Course) -> float:
    base = float(c.tonnage_livre if c.tonnage_livre is not None else c.tonnage_prevu)
    return round(base * float(c.prix_unitaire), 2) if c.tarif_mode == "tonne" else round(float(c.prix_unitaire), 2)


def _reqs_course(db: Session, c: models.Course) -> list[models.Requisition]:
    """Toutes les réquisitions rattachées à la course (initiale + suppléments)."""
    ids = [r.requisition_id for r in db.execute(select(models.CourseRequisition).where(
        models.CourseRequisition.course_id == c.id)).scalars()]
    return [db.get(models.Requisition, i) for i in ids if i]


def _frais_course(db: Session, c: models.Course) -> float:
    """Frais de route réels : justifications des avances de TOUTES les
    réquisitions rattachées (carburant initial + dépenses en route)."""
    req_ids = [r.id for r in _reqs_course(db, c)]
    if not req_ids:
        return 0.0
    rows = db.execute(
        select(func.coalesce(func.sum(models.Justification.montant_justifie_usd), 0))
        .join(models.Avance, models.Avance.id == models.Justification.avance_id)
        .join(models.OrdreDepense, models.OrdreDepense.id == models.Avance.ordre_depense_id)
        .where(models.OrdreDepense.requisition_id.in_(req_ids))).scalar()
    return round(float(rows or 0), 2)


def _course_dict(db: Session, c: models.Course) -> dict:
    cam = db.get(models.Camion, c.camion_id) if c.camion_id else None
    chf = db.get(models.Chauffeur, c.chauffeur_id) if c.chauffeur_id else None
    cli = db.get(models.Tiers, c.client_tiers_id)
    ctr = db.get(models.ContratTransport, c.contrat_id) if c.contrat_id else None
    fac = db.get(models.Facture, c.facture_id) if c.facture_id else None
    stf = db.get(models.Facture, c.st_facture_id) if c.st_facture_id else None
    reqs = _reqs_course(db, c)
    recette = _recette(c)
    frais = _frais_course(db, c)
    st = float(c.st_cout or 0)
    # PO d'origine (demande intersociété) : prenable en charge une fois le vendeur confirmé
    cmd = db.get(models.Commande, c.commande_origine_id) if c.commande_origine_id else None
    deblocable = True
    vendeur_statut = None
    reception_po = None
    if c.statut == "demande" and cmd and cmd.devis_lie_id:
        dv = db.get(models.Devis, cmd.devis_lie_id)
        vendeur_statut = dv.statut if dv else None
        deblocable = bool(dv and dv.statut == "confirme")
    if cmd:
        from .intersociete import reception_po_resume
        r = reception_po_resume(db, cmd)
        reception_po = {"recu": round(r["totaux"]["bon"] + r["totaux"]["mauvais"], 3),
                        "manquant": r["totaux"]["manquant"], "livre": r["totaux"]["livre"],
                        "complete": r["complete"],
                        "valeur_manquants_usd": r["valeur_manquants_usd"],
                        "toutes_confirmees": r["toutes_confirmees"],
                        "a_confirmer": [x for x in r["receptions"] if x["statut"] == "a_confirmer"]}
    return {"id": str(c.id), "numero": c.numero, "statut": c.statut,
            "date": c.date_course.isoformat(),
            "client": cli.nom if cli else None, "client_tiers_id": str(c.client_tiers_id),
            "intra_groupe": bool(cli and cli.societe_liee_id),
            "contrat": ctr.libelle if ctr else None, "contrat_id": str(c.contrat_id) if c.contrat_id else None,
            "camion": cam.immatriculation if cam else None, "camion_id": str(c.camion_id),
            "camion_type": cam.type if cam else None,
            "chauffeur": chf.nom if chf else None, "chauffeur_id": str(c.chauffeur_id) if c.chauffeur_id else None,
            "origine": c.origine, "destination": c.destination, "marchandise": c.marchandise,
            "tonnage_prevu": float(c.tonnage_prevu), "tonnage_livre": float(c.tonnage_livre) if c.tonnage_livre is not None else None,
            "unite": c.unite or "tonnes",
            "tarif_mode": c.tarif_mode, "prix_unitaire": float(c.prix_unitaire),
            "recette_usd": recette, "frais_route_usd": frais,
            "st_mode": c.st_mode, "st_valeur": float(c.st_valeur) if c.st_valeur is not None else None,
            "st_cout_usd": st, "st_facture": stf.numero if stf else None,
            "marge_usd": round(recette - frais - st, 2) if c.statut in ("livree", "facturee") else None,
            "heure_depart": c.heure_depart.isoformat() if c.heure_depart else None,
            "heure_retour": c.heure_retour.isoformat() if c.heure_retour else None,
            "incidents": c.incidents,
            "requisitions": [{"id": str(r.id), "numero": r.numero, "statut": r.statut}
                             for r in reqs],
            "commande_origine": cmd.numero if cmd else None,
            "reference_producteur": cmd.reference_fournisseur if cmd else None,
            "deblocable": deblocable, "vendeur_statut": vendeur_statut,
            "reception_po": reception_po,
            "facture": fac.numero if fac else None}


def _course_ou_404(db, course_id, user):
    c = db.get(models.Course, course_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course introuvable.")
    roles = assert_acces_societe(db, user, c.societe_id)
    assert_role(roles, ROLES)
    return c, roles


@router.get("/courses")
def lister_courses(societe_id: uuid.UUID, statut: str | None = None,
                   db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    q = select(models.Course).where(models.Course.societe_id == societe_id)
    if statut:
        q = q.where(models.Course.statut == statut)
    cs = db.execute(q.order_by(models.Course.created_at.desc())).scalars().all()
    return [_course_dict(db, c) for c in cs]


@router.post("/courses", status_code=status.HTTP_201_CREATED)
def creer_course(societe_id: uuid.UUID, payload: CourseIn, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    societe = db.get(models.Societe, societe_id)
    cam = db.get(models.Camion, payload.camion_id)
    if not cam or cam.societe_id != societe_id or not cam.actif:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Camion invalide.")
    cli = db.get(models.Tiers, payload.client_tiers_id)
    if not cli or cli.type != "client":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sélectionnez un client.")
    jour = payload.date_course or date.today()
    c = models.Course(societe_id=societe_id,
                      numero=services.next_numero(db, "course", jour.year, societe.code, societe.id),
                      date_course=jour, client_tiers_id=cli.id, contrat_id=payload.contrat_id,
                      camion_id=cam.id, chauffeur_id=payload.chauffeur_id,
                      origine=payload.origine.strip(), destination=payload.destination.strip(),
                      marchandise=payload.marchandise.strip(), tonnage_prevu=payload.tonnage_prevu,
                      unite=(payload.unite or "tonnes").strip(),
                      tarif_mode=payload.tarif_mode, prix_unitaire=payload.prix_unitaire,
                      requisition_id=payload.requisition_id, created_by=user.id)
    db.add(c)
    db.flush()
    if payload.requisition_id:
        db.add(models.CourseRequisition(course_id=c.id, requisition_id=payload.requisition_id))
    services.enregistrer_audit(db, user.id, "INSERT", "course", c.id, None,
                               {"numero": c.numero, "camion": cam.immatriculation})
    db.commit()
    return _course_dict(db, c)


class PriseEnChargeIn(BaseModel):
    camion_id: uuid.UUID
    chauffeur_id: uuid.UUID | None = None
    tonnage_prevu: float | None = None
    unite: str | None = None
    tarif_mode: str = Field(default="tonne", pattern="^(tonne|voyage)$")
    prix_unitaire: float = Field(ge=0)
    contrat_id: uuid.UUID | None = None
    origine: str | None = None
    destination: str | None = None
    requisition_id: uuid.UUID | None = None


@router.post("/courses/{course_id}/prendre-en-charge")
def prendre_en_charge(course_id: uuid.UUID, payload: PriseEnChargeIn,
                      db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    """Une DEMANDE de course (issue d'un PO intersociété) est complétée par le
    transporteur — camion, chauffeur, tarif — et devient une fiche brouillon.
    Bloqué tant que le vendeur n'a pas confirmé la commande."""
    c, _ = _course_ou_404(db, course_id, user)
    if c.statut != "demande":
        raise HTTPException(status.HTTP_409_CONFLICT, "Cette course n'est pas une demande en attente.")
    if c.commande_origine_id:
        cmd = db.get(models.Commande, c.commande_origine_id)
        dv = db.get(models.Devis, cmd.devis_lie_id) if cmd and cmd.devis_lie_id else None
        if dv and dv.statut == "annule":
            raise HTTPException(status.HTTP_409_CONFLICT, "La commande d'origine a été annulée par le vendeur.")
        if not dv or dv.statut != "confirme":
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "En attente : le vendeur n'a pas encore confirmé la commande — "
                                "la course sera prenable en charge dès sa confirmation.")
    cam = db.get(models.Camion, payload.camion_id)
    if not cam or cam.societe_id != c.societe_id or not cam.actif:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Camion invalide.")
    c.camion_id = cam.id
    c.chauffeur_id = payload.chauffeur_id
    c.contrat_id = payload.contrat_id
    if payload.tonnage_prevu:
        c.tonnage_prevu = payload.tonnage_prevu
    if payload.unite:
        c.unite = payload.unite.strip()
    c.tarif_mode = payload.tarif_mode
    c.prix_unitaire = payload.prix_unitaire
    if payload.origine:
        c.origine = payload.origine.strip()
    if payload.destination:
        c.destination = payload.destination.strip()
    if payload.requisition_id:
        db.add(models.CourseRequisition(course_id=c.id, requisition_id=payload.requisition_id))
    c.statut = "brouillon"
    services.enregistrer_audit(db, user.id, "PRISE_EN_CHARGE", "course", c.id, None,
                               {"numero": c.numero, "camion": cam.immatriculation})
    db.commit()
    return _course_dict(db, c)


class LierRequisitionIn(BaseModel):
    requisition_id: uuid.UUID


@router.post("/courses/{course_id}/lier-requisition")
def lier_requisition(course_id: uuid.UUID, payload: LierRequisitionIn,
                     db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    """Rattache une réquisition (carburant, péage, dépannage…) à la course —
    possible À TOUT MOMENT, y compris en cours de route (PROC-KL-02)."""
    c, _ = _course_ou_404(db, course_id, user)
    if c.statut in ("facturee", "annulee"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Course clôturée — plus de rattachement possible.")
    req = db.get(models.Requisition, payload.requisition_id)
    if not req or req.societe_id != c.societe_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Réquisition invalide pour cette société.")
    deja = db.execute(select(models.CourseRequisition).where(
        models.CourseRequisition.course_id == c.id,
        models.CourseRequisition.requisition_id == req.id)).scalars().first()
    if deja:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{req.numero} est déjà rattachée à cette course.")
    db.add(models.CourseRequisition(course_id=c.id, requisition_id=req.id))
    services.enregistrer_audit(db, user.id, "LIEN", "course", c.id, None,
                               {"numero": c.numero, "requisition": req.numero})
    db.commit()
    return _course_dict(db, c)


@router.post("/courses/{course_id}/valider")
def valider_course(course_id: uuid.UUID, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    """Validation de la Fiche Course (PROC-KL-01, étape 4) — par le rôle
    validateur configuré pour la société (défaut : DFI)."""
    c, roles = _course_ou_404(db, course_id, user)
    role_requis = _role_validation(db, c.societe_id)
    if role_requis not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"La validation des fiches de course est réservée au rôle {role_requis} "
                            "(modifiable dans les réglages transport).")
    if c.statut != "brouillon":
        raise HTTPException(status.HTTP_409_CONFLICT, "Seule une fiche brouillon se valide.")
    c.statut = "validee"
    c.valide_par = user.id
    services.enregistrer_audit(db, user.id, "VALIDATION", "course", c.id, None, {"numero": c.numero})
    db.commit()
    return _course_dict(db, c)


@router.post("/courses/{course_id}/depart")
def depart_course(course_id: uuid.UUID, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    """Libération du camion. Bloqué si le camion n'est pas disponible ou si
    l'avance carburant liée n'a pas été décaissée (PROC-KL-01/02)."""
    c, _ = _course_ou_404(db, course_id, user)
    if c.statut != "validee":
        raise HTTPException(status.HTTP_409_CONFLICT, "La fiche doit d'abord être validée par le DFI.")
    cam = db.get(models.Camion, c.camion_id)
    if cam.statut == "immobilise":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Camion {cam.immatriculation} immobilisé ({cam.motif_immobilisation or 'maintenance'}) — inaffectable.")
    if cam.statut == "en_course":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Camion {cam.immatriculation} déjà en course.")
    req_ids = [r.id for r in _reqs_course(db, c)]
    if req_ids:
        avance = db.execute(
            select(models.Avance)
            .join(models.OrdreDepense, models.OrdreDepense.id == models.Avance.ordre_depense_id)
            .where(models.OrdreDepense.requisition_id.in_(req_ids))).scalars().first()
        if not avance:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "L'avance carburant liée n'est pas encore décaissée — pas de départ "
                                "sans carburant mis (PROC-KL-02).")
    c.statut = "en_cours"
    c.heure_depart = func.now()
    cam.statut = "en_course"
    services.enregistrer_audit(db, user.id, "DEPART", "course", c.id, None, {"numero": c.numero})
    db.commit()
    return _course_dict(db, c)


@router.post("/courses/{course_id}/arrivee")
def arrivee_course(course_id: uuid.UUID, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    """Le camion est arrivé à destination — déchargement en cours. Visible en
    temps réel par l'acheteur et le vendeur (suivi partagé de la course)."""
    c, _ = _course_ou_404(db, course_id, user)
    if c.statut != "en_cours":
        raise HTTPException(status.HTTP_409_CONFLICT, "La course n'est pas en route.")
    c.statut = "arrivee"
    services.enregistrer_audit(db, user.id, "ARRIVEE", "course", c.id, None, {"numero": c.numero})
    db.commit()
    return _course_dict(db, c)


@router.post("/courses/{course_id}/retour")
def retour_course(course_id: uuid.UUID, payload: RetourIn, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    """Clôture au retour du camion (PROC-KL-03) : tonnage livré, incidents,
    coût de sous-traitance figé et dette envers le propriétaire générée."""
    c, _ = _course_ou_404(db, course_id, user)
    if c.statut not in ("en_cours", "arrivee", "receptionnee"):
        raise HTTPException(status.HTTP_409_CONFLICT, "La course n'est pas en cours.")
    cam = db.get(models.Camion, c.camion_id)
    c.tonnage_livre = payload.tonnage_livre
    c.incidents = (payload.incidents or "").strip() or None
    c.heure_retour = func.now()
    c.statut = "livree"
    cam.statut = "disponible"

    # ── Sous-traitance : coût figé + facture fournisseur (dette 401) ──
    if cam.type == "sous_traite":
        mode = payload.st_mode or cam.remuneration_mode
        valeur = payload.st_valeur if payload.st_valeur is not None else (
            float(cam.remuneration_valeur) if cam.remuneration_valeur is not None else None)
        if not mode or valeur is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Camion sous-traité : précisez la rémunération (forfait ou % du prix client).")
        recette = _recette(c)
        cout = round(valeur, 2) if mode == "forfait" else round(recette * valeur / 100, 2)
        c.st_mode, c.st_valeur, c.st_cout = mode, valeur, cout
        prop = db.get(models.Tiers, cam.proprietaire_tiers_id)
        societe = db.get(models.Societe, c.societe_id)
        numero = services.next_numero(db, "facture_achat", date.today().year, societe.code, societe.id)
        fa = models.Facture(societe_id=c.societe_id, type="achat", numero=numero,
                            tiers_id=prop.id, date_facture=date.today(), reference=c.numero,
                            total_ht=cout, total_ttc=cout, statut="validee", created_by=user.id)
        db.add(fa)
        db.flush()
        db.add(models.LigneFacture(facture_id=fa.id, designation=(
            f"Sous-traitance transport {c.numero} — camion {cam.immatriculation} "
            f"({c.origine} → {c.destination})"), qte=1, prix_unitaire=cout,
            taux_tva=0, montant_ht=cout, montant_tva=0))
        cpt_st = comptabilite._compte(db, "compte_sous_traitance", c.societe_id)
        ecr = comptabilite.post_ecriture(
            db, societe, "AC", "Achats", "achat", date.today(),
            f"Sous-traitance {c.numero} — {prop.nom}",
            [{"sens": "D", "compte": cpt_st, "montant_usd": cout,
              "libelle": f"Sous-traitance {c.numero} ({cam.immatriculation})"},
             {"sens": "C", "compte": comptabilite._compte(db, "compte_fournisseur", c.societe_id),
              "montant_usd": cout, "tiers_id": prop.id,
              "libelle": f"Dû à {prop.nom} — {c.numero}"}],
            "sous_traitance", "facture", fa.id, numero, user.id, statut="valide")
        fa.ecriture_id = ecr.id
        c.st_facture_id = fa.id

    services.enregistrer_audit(db, user.id, "RETOUR", "course", c.id, None,
                               {"numero": c.numero, "tonnage": payload.tonnage_livre})
    db.commit()
    return _course_dict(db, c)


@router.post("/courses/{course_id}/annuler")
def annuler_course(course_id: uuid.UUID, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    c, _ = _course_ou_404(db, course_id, user)
    if c.statut not in ("brouillon", "validee"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Une course partie ne s'annule plus.")
    c.statut = "annulee"
    db.commit()
    return _course_dict(db, c)


class FacturerCoursesIn(BaseModel):
    course_ids: list[uuid.UUID]
    echeance: date | None = None


@router.post("/facturer", status_code=status.HTTP_201_CREATED)
def facturer_courses(societe_id: uuid.UUID, payload: FacturerCoursesIn,
                     db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    """Facture une ou plusieurs courses livrées d'un même client (PROC-KL-04 :
    sous 48 h). Client du groupe → facture miroir automatique chez lui."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    if not payload.course_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sélectionnez au moins une course.")
    courses = [db.get(models.Course, cid) for cid in payload.course_ids]
    for c in courses:
        if not c or c.societe_id != societe_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Course invalide.")
        if c.statut != "livree":
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"{c.numero} : seule une course livrée se facture (statut {c.statut}).")
    clients = {c.client_tiers_id for c in courses}
    if len(clients) > 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Une facture regroupe des courses d'un même client.")
    # Course issue d'un PO : le transport ne se facture qu'après la réception
    # de l'acheteur (le transporteur facture la quantité reçue, règle du groupe)
    for c in courses:
        if c.commande_origine_id:
            from .intersociete import reception_po_resume
            cmd_po = db.get(models.Commande, c.commande_origine_id)
            r = reception_po_resume(db, cmd_po) if cmd_po else None
            if not r or r["totaux"]["bon"] + r["totaux"]["mauvais"] + r["totaux"]["manquant"] <= 0:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"{c.numero} : facturation bloquée — l'acheteur n'a pas encore "
                                    "réceptionné la marchandise (le transport se facture sur le reçu).")
            if not r["toutes_confirmees"]:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"{c.numero} : facturation bloquée — confirmez d'abord la réception "
                                    "de l'acheteur (bouton « Confirmer la réception » sur la course).")
    societe = db.get(models.Societe, societe_id)
    tiers = db.get(models.Tiers, courses[0].client_tiers_id)
    jour = date.today()
    tva_taux = float(services.get_parametre(db, "tva.taux_defaut", societe_id, "16"))
    from .commercial import _statut_piece
    statut_piece = _statut_piece(db, societe_id, "vente")
    numero = services.next_numero(db, "facture_vente", jour.year, societe.code, societe.id)
    fac = models.Facture(societe_id=societe_id, type="vente", numero=numero, tiers_id=tiers.id,
                         date_facture=jour, echeance=payload.echeance,
                         statut="validee" if statut_piece == "valide" else "en_attente",
                         created_by=user.id)
    db.add(fac)
    db.flush()

    total_ht = total_tva = cout_total = 0.0
    lm_list = []
    for c in courses:
        ht = _recette(c)
        tva = round(ht * tva_taux / 100, 2)
        cam = db.get(models.Camion, c.camion_id)
        des = (f"Transport {c.marchandise} — {c.origine} → {c.destination} "
               f"({c.numero}, camion {cam.immatriculation}, "
               f"{float(c.tonnage_livre or 0):g} t)")
        lm = models.LigneFacture(facture_id=fac.id, designation=des, qte=1,
                                 prix_unitaire=ht, taux_tva=tva_taux,
                                 montant_ht=ht, montant_tva=tva)
        db.add(lm)
        lm_list.append(lm)
        total_ht += ht
        total_tva += tva
        cout_total += float(c.st_cout or 0) + _frais_course(db, c)
        c.statut = "facturee"
        c.facture_id = fac.id
    fac.total_ht = round(total_ht, 2)
    fac.total_tva = round(total_tva, 2)
    fac.total_ttc = round(total_ht + total_tva, 2)
    fac.cout_ventes = round(cout_total, 2)
    fac.marge = round(fac.total_ht - cout_total, 2)

    # Écriture : D 411 (client) / C 706 (produits de transport) + C 4431
    cpt_produit = comptabilite._compte(db, "compte_vente_transport", societe_id)
    lignes = [{"sens": "D", "compte": comptabilite._compte(db, "compte_client", societe_id),
               "montant_usd": float(fac.total_ttc), "tiers_id": tiers.id,
               "libelle": f"Client {tiers.nom} — {numero}"},
              {"sens": "C", "compte": cpt_produit, "montant_usd": float(fac.total_ht),
               "libelle": f"Produits de transport {numero}"}]
    if float(fac.total_tva):
        lignes.append({"sens": "C", "compte": comptabilite._compte(db, "tva_collectee", societe_id),
                       "montant_usd": float(fac.total_tva), "libelle": f"TVA collectée {numero}"})
    ecr = comptabilite.post_ecriture(db, societe, "VE", "Ventes", "vente", jour,
                                     f"Facture transport {numero} — {tiers.nom}", lignes,
                                     "facture_vente", "facture", fac.id, numero, user.id,
                                     statut=statut_piece)
    fac.ecriture_id = ecr.id

    # Intersociété : client du groupe → miroir achat chez lui
    from .intersociete import creer_facture_miroir
    creer_facture_miroir(db, fac, user.id)

    services.enregistrer_audit(db, user.id, "INSERT", "facture", fac.id, None,
                               {"numero": numero, "courses": [c.numero for c in courses]})
    db.commit()
    return {"facture": {"id": str(fac.id), "numero": numero, "total_ttc": float(fac.total_ttc),
                        "intra_groupe": bool(fac.intra_groupe)},
            "courses": [_course_dict(db, c) for c in courses]}


# ═══ Maintenance (PROC-KL-05/06) ═════════════════════════════════════
class InterventionIn(BaseModel):
    camion_id: uuid.UUID
    type: str = Field(default="reparation", pattern="^(entretien|reparation|controle|accident)$")
    description: str = Field(min_length=3)
    prestataire: str | None = None
    cout_estime: float | None = None
    immobilise: bool = True
    requisition_id: uuid.UUID | None = None


class InterventionFinIn(BaseModel):
    cout_reel: float | None = None


def _intervention_dict(db: Session, i: models.InterventionCamion) -> dict:
    cam = db.get(models.Camion, i.camion_id)
    req = db.get(models.Requisition, i.requisition_id) if i.requisition_id else None
    return {"id": str(i.id), "numero": i.numero, "type": i.type, "statut": i.statut,
            "camion": cam.immatriculation if cam else None, "camion_id": str(i.camion_id),
            "description": i.description, "prestataire": i.prestataire,
            "cout_estime": float(i.cout_estime) if i.cout_estime is not None else None,
            "cout_reel": float(i.cout_reel) if i.cout_reel is not None else None,
            "immobilise": bool(i.immobilise),
            "date_signalement": i.date_signalement.isoformat(),
            "date_fin": i.date_fin.isoformat() if i.date_fin else None,
            "requisition": req.numero if req else None}


@router.get("/interventions")
def lister_interventions(societe_id: uuid.UUID, camion_id: uuid.UUID | None = None,
                         db: Session = Depends(get_db),
                         user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    q = select(models.InterventionCamion).where(models.InterventionCamion.societe_id == societe_id)
    if camion_id:
        q = q.where(models.InterventionCamion.camion_id == camion_id)
    return [_intervention_dict(db, i) for i in
            db.execute(q.order_by(models.InterventionCamion.created_at.desc())).scalars()]


@router.post("/interventions", status_code=status.HTTP_201_CREATED)
def signaler_intervention(societe_id: uuid.UUID, payload: InterventionIn,
                          db: Session = Depends(get_db),
                          user: models.Utilisateur = Depends(get_current_user)):
    """Signalement de panne / entretien. Si immobilisant, le camion sort de la
    flotte disponible immédiatement (PROC-KL-06)."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    cam = db.get(models.Camion, payload.camion_id)
    if not cam or cam.societe_id != societe_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Camion invalide.")
    if payload.immobilise and cam.statut == "en_course":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{cam.immatriculation} est en course — clôturez la course avant d'immobiliser.")
    societe = db.get(models.Societe, societe_id)
    i = models.InterventionCamion(
        societe_id=societe_id, camion_id=cam.id,
        numero=services.next_numero(db, "intervention", date.today().year, societe.code, societe.id),
        type=payload.type, description=payload.description.strip(),
        prestataire=(payload.prestataire or "").strip() or None,
        cout_estime=payload.cout_estime, immobilise=payload.immobilise,
        date_signalement=date.today(), requisition_id=payload.requisition_id,
        statut="en_cours", created_by=user.id)
    db.add(i)
    if payload.immobilise:
        cam.statut = "immobilise"
        cam.motif_immobilisation = f"{payload.type} — {payload.description.strip()[:80]}"
        cam.immobilise_depuis = date.today()
    services.enregistrer_audit(db, user.id, "INSERT", "intervention", i.id, None,
                               {"camion": cam.immatriculation, "type": payload.type})
    db.commit()
    return _intervention_dict(db, i)


@router.post("/interventions/{intervention_id}/terminer")
def terminer_intervention(intervention_id: uuid.UUID, payload: InterventionFinIn,
                          db: Session = Depends(get_db),
                          user: models.Utilisateur = Depends(get_current_user)):
    """Remise en service (PROC-KL-06) : clôt l'intervention, libère le camion."""
    i = db.get(models.InterventionCamion, intervention_id)
    if not i:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intervention introuvable.")
    roles = assert_acces_societe(db, user, i.societe_id)
    assert_role(roles, ROLES)
    if i.statut == "terminee":
        raise HTTPException(status.HTTP_409_CONFLICT, "Déjà terminée.")
    i.statut = "terminee"
    i.date_fin = date.today()
    if payload.cout_reel is not None:
        i.cout_reel = payload.cout_reel
    elif i.requisition_id:
        rows = db.execute(
            select(func.coalesce(func.sum(models.Justification.montant_justifie_usd), 0))
            .join(models.Avance, models.Avance.id == models.Justification.avance_id)
            .join(models.OrdreDepense, models.OrdreDepense.id == models.Avance.ordre_depense_id)
            .where(models.OrdreDepense.requisition_id == i.requisition_id)).scalar()
        i.cout_reel = round(float(rows or 0), 2) or None
    cam = db.get(models.Camion, i.camion_id)
    if i.immobilise:
        autres = db.execute(select(models.InterventionCamion).where(
            models.InterventionCamion.camion_id == cam.id,
            models.InterventionCamion.statut != "terminee",
            models.InterventionCamion.immobilise.is_(True),
            models.InterventionCamion.id != i.id)).scalars().first()
        if not autres:
            cam.statut = "disponible"
            cam.motif_immobilisation = None
            cam.immobilise_depuis = None
    services.enregistrer_audit(db, user.id, "FIN", "intervention", i.id, None,
                               {"numero": i.numero, "cout_reel": float(i.cout_reel or 0)})
    db.commit()
    return _intervention_dict(db, i)


# ═══ Rentabilité ═════════════════════════════════════════════════════
@router.get("/rapport")
def rapport_transport(societe_id: uuid.UUID, debut: date | None = None, fin: date | None = None,
                      db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    """Rentabilité par camion et par contrat : recettes, frais de route réels,
    coûts de sous-traitance, maintenance, marge."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    q = select(models.Course).where(models.Course.societe_id == societe_id,
                                    models.Course.statut.in_(["livree", "facturee"]))
    if debut:
        q = q.where(models.Course.date_course >= debut)
    if fin:
        q = q.where(models.Course.date_course <= fin)
    courses = db.execute(q).scalars().all()

    par_camion: dict = {}
    par_contrat: dict = {}
    tot = {"courses": 0, "recettes": 0.0, "frais": 0.0, "sous_traitance": 0.0, "tonnage": 0.0}
    for c in courses:
        cam = db.get(models.Camion, c.camion_id)
        rec, fr, st = _recette(c), _frais_course(db, c), float(c.st_cout or 0)
        k = cam.immatriculation if cam else "?"
        e = par_camion.setdefault(k, {"camion": k, "type": cam.type if cam else "?",
                                      "courses": 0, "tonnage": 0.0, "recettes": 0.0,
                                      "frais": 0.0, "sous_traitance": 0.0, "maintenance": 0.0})
        e["courses"] += 1
        e["tonnage"] = round(e["tonnage"] + float(c.tonnage_livre or 0), 2)
        e["recettes"] = round(e["recettes"] + rec, 2)
        e["frais"] = round(e["frais"] + fr, 2)
        e["sous_traitance"] = round(e["sous_traitance"] + st, 2)
        if c.contrat_id:
            ctr = db.get(models.ContratTransport, c.contrat_id)
            k2 = ctr.libelle if ctr else "?"
            e2 = par_contrat.setdefault(k2, {"contrat": k2, "courses": 0, "recettes": 0.0,
                                             "frais": 0.0, "sous_traitance": 0.0})
            e2["courses"] += 1
            e2["recettes"] = round(e2["recettes"] + rec, 2)
            e2["frais"] = round(e2["frais"] + fr, 2)
            e2["sous_traitance"] = round(e2["sous_traitance"] + st, 2)
        tot["courses"] += 1
        tot["recettes"] = round(tot["recettes"] + rec, 2)
        tot["frais"] = round(tot["frais"] + fr, 2)
        tot["sous_traitance"] = round(tot["sous_traitance"] + st, 2)
        tot["tonnage"] = round(tot["tonnage"] + float(c.tonnage_livre or 0), 2)

    # maintenance par camion (interventions terminées de la période)
    qi = select(models.InterventionCamion).where(
        models.InterventionCamion.societe_id == societe_id,
        models.InterventionCamion.cout_reel.is_not(None))
    if debut:
        qi = qi.where(models.InterventionCamion.date_signalement >= debut)
    if fin:
        qi = qi.where(models.InterventionCamion.date_signalement <= fin)
    maintenance_tot = 0.0
    for i in db.execute(qi).scalars():
        cam = db.get(models.Camion, i.camion_id)
        k = cam.immatriculation if cam else "?"
        if k in par_camion:
            par_camion[k]["maintenance"] = round(par_camion[k]["maintenance"] + float(i.cout_reel), 2)
        maintenance_tot = round(maintenance_tot + float(i.cout_reel), 2)

    for e in par_camion.values():
        e["marge"] = round(e["recettes"] - e["frais"] - e["sous_traitance"] - e["maintenance"], 2)
    for e in par_contrat.values():
        e["marge"] = round(e["recettes"] - e["frais"] - e["sous_traitance"], 2)
    tot["maintenance"] = maintenance_tot
    tot["marge"] = round(tot["recettes"] - tot["frais"] - tot["sous_traitance"] - maintenance_tot, 2)
    return {"total": tot,
            "par_camion": sorted(par_camion.values(), key=lambda x: -x["recettes"]),
            "par_contrat": sorted(par_contrat.values(), key=lambda x: -x["recettes"])}
