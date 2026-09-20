"""Centre d'approbation : ce qui attend la validation de l'utilisateur connecté."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, services
from ..database import get_db
from ..deps import get_current_user
from ..domain.workflow import resolve_palier

router = APIRouter(prefix="/api/approbations", tags=["centre d'approbation"])


def _societes_et_roles(db: Session, user: models.Utilisateur) -> dict:
    """{societe_id: {'roles': set, 'code':, 'nom':}} pour l'utilisateur."""
    rows = db.execute(
        select(models.Societe.id, models.Societe.code, models.Societe.nom, models.Role.code)
        .join(models.UtilisateurSociete, models.UtilisateurSociete.societe_id == models.Societe.id)
        .join(models.Role, models.Role.id == models.UtilisateurSociete.role_id)
        .where(models.UtilisateurSociete.utilisateur_id == user.id)
    ).all()
    out: dict = {}
    for sid, code, nom, role_code in rows:
        e = out.setdefault(sid, {"roles": set(), "code": code, "nom": nom})
        e["roles"].add(role_code)
    return out


@router.get("")
def centre_approbation(db: Session = Depends(get_db),
                       user: models.Utilisateur = Depends(get_current_user)):
    contexte = _societes_et_roles(db, user)
    requisitions: list[dict] = []
    ordres: list[dict] = []
    a_emettre: list[dict] = []

    for sid, info in contexte.items():
        mes_roles = info["roles"]

        # 0) Réquisitions validées à transformer en ordre de dépense (DFI)
        if "DFI" in mes_roles:
            for r in db.execute(
                select(models.Requisition).where(
                    models.Requisition.societe_id == sid,
                    models.Requisition.statut == "demande_validee")
            ).scalars().all():
                a_emettre.append({
                    "id": str(r.id), "numero": r.numero, "societe": info["code"],
                    "objet": r.objet, "devise": r.devise,
                    "montant_total_usd": float(r.montant_total_usd)})

        # 1) Réquisitions dont la DEMANDE attend validation (palier selon le montant)
        reqs = db.execute(
            select(models.Requisition).where(
                models.Requisition.societe_id == sid,
                models.Requisition.statut.in_(["soumise", "en_attente_info"]))
        ).scalars().all()
        for r in reqs:
            if r.initiateur_id == user.id:
                continue  # pas d'auto-validation
            palier = services.palier_pour_montant(db, "requisition", "demande", sid, r.montant_total_usd)
            if not palier:
                continue
            roles_requis = {a.role_code for a in palier.approbateurs}
            if not (mes_roles & roles_requis):
                continue
            decisions = services.decisions_par_role(db, "requisition", r.id, "demande")
            a_agir = {rc for rc in (mes_roles & roles_requis)
                      if decisions.get(rc) not in ("valide", "rejete")}
            if a_agir:
                requisitions.append({
                    "id": str(r.id), "numero": r.numero, "societe": info["code"],
                    "objet": r.objet, "priorite": r.priorite, "devise": r.devise,
                    "montant_total_usd": float(r.montant_total_usd),
                    "etape": "demande",
                    "roles_requis": sorted(roles_requis),
                    "mes_roles_a_agir": sorted(a_agir),
                })

        # 2) Ordres de dépense dont la SORTIE DE FONDS attend validation
        paliers_sf = services.load_paliers(db, "ordre_depense", "sortie_fonds", sid)
        if paliers_sf:
            odps = db.execute(
                select(models.OrdreDepense).where(
                    models.OrdreDepense.societe_id == sid,
                    models.OrdreDepense.statut == "a_valider")
            ).scalars().all()
            for o in odps:
                palier = resolve_palier(o.montant_autorise_usd, paliers_sf)
                roles_requis = {a.role_code for a in palier.approbateurs}
                if not (mes_roles & roles_requis):
                    continue
                decisions = services.decisions_par_role(db, "ordre_depense", o.id, "sortie_fonds")
                a_agir = {rc for rc in (mes_roles & roles_requis)
                          if decisions.get(rc) not in ("valide", "rejete")}
                if a_agir:
                    ordres.append({
                        "id": str(o.id), "numero": o.numero, "societe": info["code"],
                        "motif": o.motif, "devise": o.devise,
                        "montant_autorise_usd": float(o.montant_autorise_usd),
                        "palier": palier.libelle, "etape": "sortie_fonds",
                        "roles_requis": sorted(roles_requis),
                        "mes_roles_a_agir": sorted(a_agir),
                    })

    return {
        "utilisateur": user.email,
        "total": len(requisitions) + len(ordres) + len(a_emettre),
        "requisitions": requisitions,
        "ordres_depense": ordres,
        "a_emettre": a_emettre,
    }
