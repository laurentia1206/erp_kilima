"""Module de PARAMÉTRAGE (réservé DFI / Président / Admin système).

Permet de configurer, par société :
- la grille de validation des 2 niveaux (demande, sortie de fonds) ;
- les seuils et délais (table `parametre`) ;
- les intervenants (affectations utilisateur ↔ société ↔ rôle).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import models, services
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/api/config", tags=["paramétrage"])

ADMIN_ROLES = {"DFI", "PRESIDENT", "ADMIN_SYS"}

# Niveaux ↔ (type_document, etape)
NIVEAUX = {
    "demande": ("requisition", "demande"),          # Niveau 1
    "sortie_fonds": ("ordre_depense", "sortie_fonds"),  # Niveau 2
}


def assert_admin(db: Session, user: models.Utilisateur):
    roles = db.execute(
        select(models.Role.code)
        .join(models.UtilisateurSociete, models.UtilisateurSociete.role_id == models.Role.id)
        .where(models.UtilisateurSociete.utilisateur_id == user.id)
    ).scalars().all()
    if not (set(roles) & ADMIN_ROLES):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Accès paramétrage réservé au DFI / Président / Admin.")


# ── Référentiels ─────────────────────────────────────────────────────
# Rôles de base du système — non supprimables (utilisés dans les contrôles d'accès)
ROLES_SYSTEME = {"DFI", "DG", "ADMIN", "PRESIDENT", "CAISSIER_CENTRAL", "CAISSIER_VENDEUR",
                 "COMPTABLE", "DT", "ADMIN_SYS", "ASSISTANT_TECH"}


@router.get("/roles")
def roles(db: Session = Depends(get_db), user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    usages = dict(db.execute(
        select(models.UtilisateurSociete.role_id,
               models.Role.code).join(models.Role, models.Role.id == models.UtilisateurSociete.role_id)
    ).all())
    nb = {}
    for _, code in usages.items():
        nb[code] = nb.get(code, 0) + 1
    return [{"id": str(r.id), "code": r.code, "libelle": r.libelle,
             "herite_de": r.herite_de, "systeme": r.code in ROLES_SYSTEME,
             "nb_affectations": nb.get(r.code, 0)}
            for r in db.execute(select(models.Role).order_by(models.Role.niveau.desc())).scalars()]


class RoleIn(BaseModel):
    code: str
    libelle: str
    herite_de: str | None = None      # rôle de base dont il hérite les droits d'accès


@router.post("/roles", status_code=status.HTTP_201_CREATED)
def creer_role(payload: RoleIn, db: Session = Depends(get_db),
               user: models.Utilisateur = Depends(get_current_user)):
    """Rôle personnalisé (magasinier, logisticien, superviseur…). L'héritage
    détermine les ÉCRANS accessibles ; sans héritage, le rôle est purement
    organisationnel (approbations, affichage)."""
    assert_admin(db, user)
    code = payload.code.strip().upper().replace(" ", "_")
    if not (2 <= len(code) <= 30):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code : 2 à 30 caractères.")
    if db.execute(select(models.Role).where(models.Role.code == code)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Le rôle {code} existe déjà.")
    herite = (payload.herite_de or "").strip().upper() or None
    if herite and not db.execute(select(models.Role).where(models.Role.code == herite)).scalars().first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Rôle de base {herite} inconnu.")
    r = models.Role(code=code, libelle=payload.libelle.strip(), niveau=0, herite_de=herite)
    db.add(r)
    services.enregistrer_audit(db, user.id, "INSERT", "role", None, None,
                               {"code": code, "herite_de": herite})
    db.commit()
    return {"id": str(r.id), "code": r.code, "libelle": r.libelle, "herite_de": r.herite_de}


class RoleMaj(BaseModel):
    libelle: str | None = None
    herite_de: str | None = None


@router.patch("/roles/{role_id}")
def maj_role(role_id: uuid.UUID, payload: RoleMaj, db: Session = Depends(get_db),
             user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    r = db.get(models.Role, role_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rôle introuvable.")
    if r.code in ROLES_SYSTEME:
        raise HTTPException(status.HTTP_409_CONFLICT, "Les rôles système ne se modifient pas.")
    if payload.libelle:
        r.libelle = payload.libelle.strip()
    if payload.herite_de is not None:
        herite = payload.herite_de.strip().upper() or None
        if herite == r.code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Un rôle ne peut pas hériter de lui-même.")
        if herite and not db.execute(select(models.Role).where(models.Role.code == herite)).scalars().first():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Rôle de base {herite} inconnu.")
        r.herite_de = herite
    db.commit()
    return {"ok": True}


@router.delete("/roles/{role_id}")
def supprimer_role(role_id: uuid.UUID, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    r = db.get(models.Role, role_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rôle introuvable.")
    if r.code in ROLES_SYSTEME:
        raise HTTPException(status.HTTP_409_CONFLICT, "Les rôles système ne se suppriment pas.")
    utilise = db.execute(select(models.UtilisateurSociete).where(
        models.UtilisateurSociete.role_id == r.id)).scalars().first()
    if utilise:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Rôle affecté à des agents — retirez d'abord les affectations.")
    db.delete(r)
    services.enregistrer_audit(db, user.id, "DELETE", "role", role_id, {"code": r.code}, None)
    db.commit()
    return {"ok": True}


@router.get("/societes")
def societes_config(db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    rows = db.execute(select(models.Societe).order_by(models.Societe.code)).scalars().all()
    return [{"id": None, "code": "GRP", "nom": "Groupe (par défaut)", "actif": True}] + \
           [{"id": str(s.id), "code": s.code, "nom": s.nom, "ville": s.ville,
             "rccm": s.rccm, "id_nat": s.id_nat, "actif": bool(s.actif)} for s in rows]


class SocieteMaj(BaseModel):
    nom: str | None = None
    ville: str | None = None
    rccm: str | None = None
    id_nat: str | None = None
    actif: bool | None = None          # False = archivée (invisible partout, données conservées)


@router.patch("/societes/{societe_id}")
def maj_societe(societe_id: uuid.UUID, payload: SocieteMaj, db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    s = db.get(models.Societe, societe_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Société introuvable.")
    for f in ("nom", "ville", "rccm", "id_nat"):
        v = getattr(payload, f)
        if v is not None:
            setattr(s, f, v.strip() or None)
    if payload.actif is not None:
        s.actif = payload.actif
    services.enregistrer_audit(db, user.id, "UPDATE", "societe", s.id, None,
                               {"nom": s.nom, "actif": bool(s.actif)})
    db.commit()
    return {"id": str(s.id), "code": s.code, "nom": s.nom, "actif": bool(s.actif)}


@router.delete("/societes/{societe_id}")
def supprimer_societe(societe_id: uuid.UUID, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    """Suppression définitive — UNIQUEMENT si la société n'a aucune activité
    (aucune écriture, facture, réquisition, course, caisse mouvementée…).
    Sinon, archivez-la (elle disparaît des écrans, les données restent)."""
    assert_admin(db, user)
    s = db.get(models.Societe, societe_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Société introuvable.")
    temoins = [models.Ecriture, models.Facture, models.Requisition, models.Course,
               models.Devis, models.Commande, models.MouvementStock, models.Avance]
    for m in temoins:
        if db.execute(select(m).where(m.societe_id == societe_id)).scalars().first():
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Suppression impossible : la société a de l'activité ({m.__tablename__}). "
                                "Archivez-la plutôt — les données seront conservées.")
    # purge des données de paramétrage (générique : toute table portant societe_id)
    from sqlalchemy import delete as sqldelete
    for mapper in models.Base.registry.mappers:
        cls = mapper.class_
        if cls is models.Societe:
            continue
        if "societe_id" in {c.key for c in mapper.columns}:
            db.execute(sqldelete(cls).where(cls.societe_id == societe_id))
    db.execute(sqldelete(models.UtilisateurSociete).where(
        models.UtilisateurSociete.societe_id == societe_id))
    db.delete(s)
    services.enregistrer_audit(db, user.id, "DELETE", "societe", societe_id, {"code": s.code}, None)
    db.commit()
    return {"ok": True}


# ── Grille de validation ─────────────────────────────────────────────
class ApprobateurIn(BaseModel):
    role_code: str
    mode: str = "conjoint"


class PalierIn(BaseModel):
    societe_id: uuid.UUID | None = None
    niveau: str                       # 'demande' | 'sortie_fonds'
    montant_min_usd: float = 0
    montant_max_usd: float | None = None
    libelle: str | None = None
    approbateurs: list[ApprobateurIn]


def _palier_dict(db: Session, p: models.PalierValidation) -> dict:
    appro = sorted(p.approbateurs, key=lambda a: a.ordre)
    return {
        "id": str(p.id), "societe_id": str(p.societe_id) if p.societe_id else None,
        "type_document": p.type_document, "etape": p.etape,
        "montant_min_usd": float(p.montant_min_usd),
        "montant_max_usd": float(p.montant_max_usd) if p.montant_max_usd is not None else None,
        "libelle": p.libelle,
        "approbateurs": [{"role_code": a.role.code, "mode": a.mode} for a in appro],
    }


@router.get("/paliers")
def lister_paliers(societe_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    cond = (models.PalierValidation.societe_id == societe_id) if societe_id \
        else models.PalierValidation.societe_id.is_(None)
    rows = db.execute(select(models.PalierValidation).where(cond)
                      .order_by(models.PalierValidation.etape, models.PalierValidation.montant_min_usd)
                      ).scalars().all()
    out = {"demande": [], "sortie_fonds": []}
    for p in rows:
        d = _palier_dict(db, p)
        out.setdefault(p.etape, []).append(d)
    return out


def _set_approbateurs(db: Session, palier: models.PalierValidation, appros: list[ApprobateurIn]):
    db.execute(delete(models.PalierApprobateur)
               .where(models.PalierApprobateur.palier_id == palier.id))
    for i, a in enumerate(appros, start=1):
        rid = db.execute(select(models.Role.id).where(models.Role.code == a.role_code)).scalar_one_or_none()
        if not rid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Rôle inconnu : {a.role_code}")
        db.add(models.PalierApprobateur(palier_id=palier.id, role_id=rid, mode=a.mode, ordre=i))


@router.post("/paliers", status_code=status.HTTP_201_CREATED)
def creer_palier(payload: PalierIn, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    if payload.niveau not in NIVEAUX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Niveau invalide.")
    type_doc, etape = NIVEAUX[payload.niveau]
    p = models.PalierValidation(
        societe_id=payload.societe_id, type_document=type_doc, etape=etape,
        montant_min_usd=payload.montant_min_usd, montant_max_usd=payload.montant_max_usd,
        libelle=payload.libelle or "")
    db.add(p)
    db.flush()
    _set_approbateurs(db, p, payload.approbateurs)
    services.enregistrer_audit(db, user.id, "INSERT", "palier_validation", p.id, None,
                               {"niveau": payload.niveau})
    db.commit()
    return {"id": str(p.id)}


@router.put("/paliers/{palier_id}")
def modifier_palier(palier_id: uuid.UUID, payload: PalierIn, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    p = db.get(models.PalierValidation, palier_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Palier introuvable.")
    p.montant_min_usd = payload.montant_min_usd
    p.montant_max_usd = payload.montant_max_usd
    p.libelle = payload.libelle or ""
    _set_approbateurs(db, p, payload.approbateurs)
    services.enregistrer_audit(db, user.id, "UPDATE", "palier_validation", p.id, None, None)
    db.commit()
    return {"id": str(p.id)}


@router.delete("/paliers/{palier_id}")
def supprimer_palier(palier_id: uuid.UUID, db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    p = db.get(models.PalierValidation, palier_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Palier introuvable.")
    db.execute(delete(models.PalierApprobateur).where(models.PalierApprobateur.palier_id == p.id))
    db.delete(p)
    services.enregistrer_audit(db, user.id, "DELETE", "palier_validation", palier_id, None, None)
    db.commit()
    return {"ok": True}


# ── Seuils & délais ──────────────────────────────────────────────────
class ParametreUpdate(BaseModel):
    valeur: str


@router.get("/parametres")
def lister_parametres(societe_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    cond = (models.Parametre.societe_id == societe_id) if societe_id \
        else models.Parametre.societe_id.is_(None)
    rows = db.execute(select(models.Parametre).where(cond)
                      .order_by(models.Parametre.cle)).scalars().all()
    return [{"id": str(p.id), "cle": p.cle, "valeur": p.valeur, "description": p.description}
            for p in rows]


@router.put("/parametres/{parametre_id}")
def modifier_parametre(parametre_id: uuid.UUID, payload: ParametreUpdate,
                       db: Session = Depends(get_db),
                       user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    p = db.get(models.Parametre, parametre_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Paramètre introuvable.")
    ancienne = p.valeur
    p.valeur = payload.valeur
    p.updated_by = user.id
    services.enregistrer_audit(db, user.id, "UPDATE", "parametre", p.id,
                               {"valeur": ancienne}, {"valeur": payload.valeur})
    db.commit()
    return {"id": str(p.id), "valeur": p.valeur}


# ── Intervenants (affectations) ──────────────────────────────────────
class AffectationIn(BaseModel):
    utilisateur_id: uuid.UUID
    societe_id: uuid.UUID
    role_code: str


@router.get("/intervenants")
def lister_intervenants(societe_id: uuid.UUID, db: Session = Depends(get_db),
                        user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    rows = db.execute(
        select(models.Utilisateur.id, models.Utilisateur.nom, models.Utilisateur.email,
               models.Role.code, models.Role.libelle)
        .join(models.UtilisateurSociete, models.UtilisateurSociete.utilisateur_id == models.Utilisateur.id)
        .join(models.Role, models.Role.id == models.UtilisateurSociete.role_id)
        .where(models.UtilisateurSociete.societe_id == societe_id)
        .order_by(models.Role.niveau.desc())
    ).all()
    return [{"utilisateur_id": str(uid), "nom": nom, "email": email,
             "role_code": rc, "role_libelle": rl} for uid, nom, email, rc, rl in rows]


# ── Administration : sociétés & utilisateurs ─────────────────────────
class SocieteIn(BaseModel):
    code: str
    nom: str
    ville: str | None = None
    rccm: str | None = None
    id_nat: str | None = None


@router.post("/societes", status_code=status.HTTP_201_CREATED)
def creer_societe(payload: SocieteIn, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    """Crée une société du groupe : plan comptable SYSCOHADA chargé, caisse
    principale créée, et le créateur (admin) affecté avec ses rôles actuels."""
    assert_admin(db, user)
    code = payload.code.strip().upper()
    if not (2 <= len(code) <= 6):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code société : 2 à 6 caractères.")
    if db.execute(select(models.Societe).where(models.Societe.code == code)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Le code {code} existe déjà.")
    s = models.Societe(code=code, nom=payload.nom.strip(), ville=(payload.ville or "").strip() or None,
                       rccm=(payload.rccm or "").strip() or None,
                       id_nat=(payload.id_nat or "").strip() or None)
    db.add(s)
    db.flush()
    from ..plan_comptable import charger_plan
    charger_plan(db, s.id)
    db.add(models.Caisse(societe_id=s.id, libelle=f"Caisse principale {s.code}",
                         compte_comptable="571", est_principale=True))
    # le créateur garde la main sur la nouvelle société (mêmes rôles qu'ailleurs)
    mes_roles = {a.role_id for a in db.execute(select(models.UtilisateurSociete).where(
        models.UtilisateurSociete.utilisateur_id == user.id)).scalars()}
    for rid in mes_roles:
        db.add(models.UtilisateurSociete(utilisateur_id=user.id, societe_id=s.id, role_id=rid))
    services.enregistrer_audit(db, user.id, "INSERT", "societe", s.id, None, {"code": code})
    db.commit()
    return {"id": str(s.id), "code": s.code, "nom": s.nom}


class UtilisateurIn(BaseModel):
    nom: str
    prenom: str | None = None
    email: str
    password: str
    affectations: list[dict] = []      # [{societe_id, role_code}]


@router.post("/utilisateurs", status_code=status.HTTP_201_CREATED)
def creer_utilisateur(payload: UtilisateurIn, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    """Crée un agent avec ses affectations société ↔ rôle."""
    assert_admin(db, user)
    email = payload.email.strip().lower()
    if "@" not in email or len(payload.password) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Email valide et mot de passe d'au moins 6 caractères requis.")
    if db.execute(select(models.Utilisateur).where(models.Utilisateur.email == email)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"{email} existe déjà.")
    from .. import security
    u = models.Utilisateur(email=email, nom=payload.nom.strip(),
                           prenom=(payload.prenom or "").strip() or None,
                           password_hash=security.hash_password(payload.password))
    db.add(u)
    db.flush()
    roles_par_code = {r.code: r for r in db.execute(select(models.Role)).scalars()}
    n = 0
    for a in payload.affectations:
        role = roles_par_code.get(str(a.get("role_code", "")).upper())
        try:
            sid = uuid.UUID(str(a.get("societe_id")))
        except (ValueError, TypeError):
            continue
        if role and db.get(models.Societe, sid):
            db.add(models.UtilisateurSociete(utilisateur_id=u.id, societe_id=sid, role_id=role.id))
            n += 1
    services.enregistrer_audit(db, user.id, "INSERT", "utilisateur", u.id, None,
                               {"email": email, "affectations": n})
    db.commit()
    return {"id": str(u.id), "email": u.email, "nom": u.nom, "affectations": n}


class UtilisateurMaj(BaseModel):
    nom: str | None = None
    prenom: str | None = None
    email: str | None = None
    actif: bool | None = None
    password: str | None = None


@router.patch("/utilisateurs/{utilisateur_id}")
def maj_utilisateur(utilisateur_id: uuid.UUID, payload: UtilisateurMaj,
                    db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    """Modifier un agent (identité, email), le désactiver ou réinitialiser son mot de passe."""
    assert_admin(db, user)
    u = db.get(models.Utilisateur, utilisateur_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur introuvable.")
    if payload.nom:
        u.nom = payload.nom.strip()
    if payload.prenom is not None:
        u.prenom = payload.prenom.strip() or None
    if payload.email:
        email = payload.email.strip().lower()
        if "@" not in email:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email invalide.")
        deja = db.execute(select(models.Utilisateur).where(
            models.Utilisateur.email == email,
            models.Utilisateur.id != u.id)).scalars().first()
        if deja:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{email} est déjà utilisé.")
        u.email = email
    if payload.actif is not None:
        if u.id == user.id and not payload.actif:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Impossible de se désactiver soi-même.")
        u.actif = payload.actif
    if payload.password:
        if len(payload.password) < 6:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mot de passe : 6 caractères minimum.")
        from .. import security
        u.password_hash = security.hash_password(payload.password)
    services.enregistrer_audit(db, user.id, "UPDATE", "utilisateur", u.id, None,
                               {"actif": u.actif, "mdp_change": bool(payload.password)})
    db.commit()
    return {"ok": True}


@router.get("/utilisateurs")
def lister_utilisateurs(db: Session = Depends(get_db),
                        user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    socs = {s.id: s.code for s in db.execute(select(models.Societe)).scalars()}
    roles = {r.id: r.code for r in db.execute(select(models.Role)).scalars()}
    rows = db.execute(select(models.Utilisateur).order_by(models.Utilisateur.nom)).scalars().all()
    out = []
    for u in rows:
        affs = db.execute(select(models.UtilisateurSociete).where(
            models.UtilisateurSociete.utilisateur_id == u.id)).scalars().all()
        out.append({"id": str(u.id), "nom": u.nom, "prenom": u.prenom, "email": u.email,
                    "actif": bool(u.actif),
                    "affectations": sorted({f"{roles.get(a.role_id, '?')}@{socs.get(a.societe_id, '?')}"
                                            for a in affs})})
    return out


@router.post("/affectations", status_code=status.HTTP_201_CREATED)
def ajouter_affectation(payload: AffectationIn, db: Session = Depends(get_db),
                        user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    rid = db.execute(select(models.Role.id).where(models.Role.code == payload.role_code)).scalar_one_or_none()
    if not rid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Rôle inconnu.")
    exists = db.get(models.UtilisateurSociete, (payload.utilisateur_id, payload.societe_id, rid))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Affectation déjà existante.")
    db.add(models.UtilisateurSociete(utilisateur_id=payload.utilisateur_id,
                                     societe_id=payload.societe_id, role_id=rid))
    services.enregistrer_audit(db, user.id, "INSERT", "utilisateur_societe", payload.utilisateur_id,
                               None, {"role": payload.role_code})
    db.commit()
    return {"ok": True}


@router.delete("/affectations")
def retirer_affectation(payload: AffectationIn, db: Session = Depends(get_db),
                        user: models.Utilisateur = Depends(get_current_user)):
    assert_admin(db, user)
    rid = db.execute(select(models.Role.id).where(models.Role.code == payload.role_code)).scalar_one()
    db.execute(delete(models.UtilisateurSociete).where(
        models.UtilisateurSociete.utilisateur_id == payload.utilisateur_id,
        models.UtilisateurSociete.societe_id == payload.societe_id,
        models.UtilisateurSociete.role_id == rid))
    services.enregistrer_audit(db, user.id, "DELETE", "utilisateur_societe", payload.utilisateur_id,
                               {"role": payload.role_code}, None)
    db.commit()
    return {"ok": True}
