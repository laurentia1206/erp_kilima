"""Paramétrage & administration — portage exact de backend/app/routers/config.py
et de pieces_jointes.py.

Rôles (avec héritage, rôles système protégés), sociétés (création avec plan
SYSCOHADA + caisse principale, archivage, suppression si sans activité),
paliers de validation, paramètres, agents et affectations, pièces jointes.

⚠ La table utilisateur_societe a une CLÉ PRIMAIRE COMPOSITE (utilisateur_id,
societe_id, role_id) que l'ORM Django ne sait pas écrire proprement : toutes
les insertions/suppressions passent par du SQL brut (lecture via le modèle OK).
"""
from __future__ import annotations

from rest_framework.decorators import action
from core.viewsets import MetierModelViewSet, MetierViewSet
from core.models import Role
from core.serializers import RoleSerializer
from core.models import Societe
from core.serializers import SocieteSerializer
from apps.approbations.models import PalierValidation
from core.serializers import PalierValidationSerializer
from core.models import Parametre
from core.serializers import ParametreSerializer
from core.models import Tiers
from core.serializers import TiersSerializer
from core.models import Utilisateur
from core.serializers import UtilisateurSerializer
from core.models import UtilisateurSociete
from core.serializers import UtilisateurSocieteSerializer
from core.models import PieceJointe
from core.serializers import PieceJointeSerializer

import re
import uuid as uuidlib
from pathlib import Path

import bcrypt
from django.conf import settings as dj_settings
from django.db import connection, transaction
from django.http import FileResponse
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, ValidationError

from . import plan_syscohada, services
from .erreurs import refus
from .models import (Avance, Caisse, Commande, Course, Devis, Ecriture, Facture,
                     MouvementStock, PalierApprobateur, PalierValidation, Parametre,
                     PieceJointe, Requisition, Role, Societe, Utilisateur,
                     UtilisateurSociete)

ADMIN_ROLES = {"DFI", "PRESIDENT", "ADMIN_SYS"}
NIVEAUX = {"demande": ("requisition", "demande"),
           "sortie_fonds": ("ordre_depense", "sortie_fonds")}
# Rôles de base du système — non supprimables
ROLES_SYSTEME = {"DFI", "DG", "ADMIN", "PRESIDENT", "CAISSIER_CENTRAL",
                 "CAISSIER_VENDEUR", "COMPTABLE", "DT", "ADMIN_SYS", "ASSISTANT_TECH", "RH", "DRH", "RESP_EQUIPE"}

UPLOADS = dj_settings.FASTAPI_DIR / "uploads"
MAX_OCTETS = 10 * 1024 * 1024  # 10 Mo


def _est_admin(user) -> bool:
    codes = set(UtilisateurSociete.objects.filter(utilisateur_id=user.id)
                .values_list("role__code", flat=True))
    return bool(codes & ADMIN_ROLES)


def _hex(v) -> str:
    """UUID → forme stockée en base (32 hex sans tirets, comme SQLAlchemy)."""
    return uuidlib.UUID(str(v)).hex


def _inserer_affectation(utilisateur_id, societe_id, role_id, site_id=None):
    """INSERT direct (PK composite hors de portée de l'ORM Django)."""
    with connection.cursor() as cur:
        cur.execute("INSERT INTO utilisateur_societe (utilisateur_id, societe_id, "
                    "role_id, site_id) VALUES (%s, %s, %s, %s)",
                    [_hex(utilisateur_id), _hex(societe_id), _hex(role_id),
                     _hex(site_id) if site_id else None])


def _supprimer_affectation(utilisateur_id, societe_id, role_id):
    with connection.cursor() as cur:
        cur.execute("DELETE FROM utilisateur_societe WHERE utilisateur_id=%s "
                    "AND societe_id=%s AND role_id=%s",
                    [_hex(utilisateur_id), _hex(societe_id), _hex(role_id)])


# ── Rôles ────────────────────────────────────────────────────────────


class RoleViewSet(MetierModelViewSet):
    """Ressource Role ; contrats HTTP et validations métier conservés."""
    queryset = Role.objects.none()
    serializer_class = RoleSerializer
    lookup_url_kwarg = 'role_id'

    def list(self, request):
        return self._traiter_roles(request)


    def create(self, request):
        return self._traiter_roles(request)


    def _traiter_roles(self, request):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        if request.method == "POST":
            payload = request.data or {}
            code = (payload.get("code") or "").strip().upper().replace(" ", "_")
            if not (2 <= len(code) <= 30):
                return refus({"detail": "Code : 2 à 30 caractères."}, status=400)
            if Role.objects.filter(code=code).exists():
                return refus({"detail": f"Le rôle {code} existe déjà."}, status=409)
            herite = (payload.get("herite_de") or "").strip().upper() or None
            if herite and not Role.objects.filter(code=herite).exists():
                return refus({"detail": f"Rôle de base {herite} inconnu."}, status=400)
            r = Role.objects.create(code=code, libelle=(payload.get("libelle") or "").strip(),
                                    niveau=0, herite_de=herite)
            services.enregistrer_audit(request.user.id, "INSERT", "role", None, None,
                                       {"code": code, "herite_de": herite})
            return Response({"id": str(r.id), "code": r.code, "libelle": r.libelle,
                             "herite_de": r.herite_de}, status=201)
        # même particularité que FastAPI : le dict role_id→code écrase les doublons,
        # nb_affectations compte donc les rôles utilisés (0/1), pas les affectations
        usages = dict(UtilisateurSociete.objects.values_list("role_id", "role__code"))
        nb = {}
        for _, code in usages.items():
            nb[code] = nb.get(code, 0) + 1
        return Response([{"id": str(r.id), "code": r.code, "libelle": r.libelle,
                          "herite_de": r.herite_de, "systeme": r.code in ROLES_SYSTEME,
                          "nb_affectations": nb.get(r.code, 0)}
                         for r in Role.objects.all().order_by("-niveau")])


    def partial_update(self, request, role_id):
        return self._traiter_role_detail(request, role_id)


    def destroy(self, request, role_id):
        return self._traiter_role_detail(request, role_id)


    def _traiter_role_detail(self, request, role_id):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        r = Role.objects.filter(id=role_id).first()
        if not r:
            return refus({"detail": "Rôle introuvable."}, status=404)
        if request.method == "DELETE":
            if r.code in ROLES_SYSTEME:
                return refus({"detail": "Les rôles système ne se suppriment pas."},
                             status=409)
            if UtilisateurSociete.objects.filter(role_id=r.id).exists():
                return refus({"detail": "Rôle affecté à des agents — retirez d'abord les "
                                        "affectations."}, status=409)
            code = r.code
            r.delete()
            services.enregistrer_audit(request.user.id, "DELETE", "role", role_id,
                                       {"code": code}, None)
            return Response({"ok": True})
        if r.code in ROLES_SYSTEME:
            return refus({"detail": "Les rôles système ne se modifient pas."}, status=409)
        payload = request.data or {}
        if payload.get("libelle"):
            r.libelle = payload["libelle"].strip()
        if payload.get("herite_de") is not None:
            herite = payload["herite_de"].strip().upper() or None
            if herite == r.code:
                return refus({"detail": "Un rôle ne peut pas hériter de lui-même."},
                             status=400)
            if herite and not Role.objects.filter(code=herite).exists():
                return refus({"detail": f"Rôle de base {herite} inconnu."}, status=400)
            r.herite_de = herite
        r.save()
        return Response({"ok": True})


# ── Sociétés ─────────────────────────────────────────────────────────


class SocieteViewSet(MetierModelViewSet):
    """Ressource Societe ; contrats HTTP et validations métier conservés."""
    queryset = Societe.objects.none()
    serializer_class = SocieteSerializer
    lookup_url_kwarg = 'societe_id'

    def list(self, request):
        return self._traiter_societes_config(request)


    def create(self, request):
        return self._traiter_societes_config(request)


    def _traiter_societes_config(self, request):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        if request.method == "POST":
            payload = request.data or {}
            code = (payload.get("code") or "").strip().upper()
            if not (2 <= len(code) <= 6):
                return refus({"detail": "Code société : 2 à 6 caractères."}, status=400)
            if Societe.objects.filter(code=code).exists():
                return refus({"detail": f"Le code {code} existe déjà."}, status=409)
            with transaction.atomic():
                s = Societe.objects.create(
                    code=code, nom=(payload.get("nom") or "").strip(),
                    # la colonne ville est NOT NULL avec défaut SQLAlchemy "Likasi"
                    ville=(payload.get("ville") or "").strip() or "Likasi",
                    rccm=(payload.get("rccm") or "").strip() or None,
                    id_nat=(payload.get("id_nat") or "").strip() or None,
                    created_at=services.maintenant())
                plan_syscohada.charger_plan(s.id)
                Caisse.objects.create(societe_id=s.id,
                                      libelle=f"Caisse principale {s.code}",
                                      compte_comptable="571", est_principale=True)
                # le créateur garde la main (mêmes rôles qu'ailleurs)
                mes_roles = set(UtilisateurSociete.objects.filter(
                    utilisateur_id=request.user.id).values_list("role_id", flat=True))
                for rid in mes_roles:
                    _inserer_affectation(request.user.id, s.id, rid)
                services.enregistrer_audit(request.user.id, "INSERT", "societe", s.id, None,
                                           {"code": code})
            return Response({"id": str(s.id), "code": s.code, "nom": s.nom}, status=201)
        rows = Societe.objects.all().order_by("code")
        return Response([{"id": None, "code": "GRP", "nom": "Groupe (par défaut)",
                          "actif": True}] +
                        [{"id": str(s.id), "code": s.code, "nom": s.nom, "ville": s.ville,
                          "rccm": s.rccm, "id_nat": s.id_nat, "actif": bool(s.actif)}
                         for s in rows])


    def partial_update(self, request, societe_id):
        return self._traiter_societe_detail(request, societe_id)


    def destroy(self, request, societe_id):
        return self._traiter_societe_detail(request, societe_id)


    def _traiter_societe_detail(self, request, societe_id):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        s = Societe.objects.filter(id=societe_id).first()
        if not s:
            return refus({"detail": "Société introuvable."}, status=404)
        if request.method == "DELETE":
            temoins = [Ecriture, Facture, Requisition, Course, Devis, Commande,
                       MouvementStock, Avance]
            for m in temoins:
                if m.objects.filter(societe_id=societe_id).exists():
                    return refus({"detail": f"Suppression impossible : la société a de "
                                            f"l'activité ({m._meta.db_table}). Archivez-la "
                                            f"plutôt — les données seront conservées."},
                                 status=409)
            with transaction.atomic():
                # purge générique : toute table utilisateur portant une colonne societe_id
                hexid = _hex(societe_id)
                with connection.cursor() as cur:
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                "AND name NOT LIKE 'sqlite_%'")
                    tables = [t for (t,) in cur.fetchall() if t != "societe"]
                    for t in tables:
                        cur.execute(f"PRAGMA table_info({t})")
                        if any(col[1] == "societe_id" for col in cur.fetchall()):
                            cur.execute(f"DELETE FROM {t} WHERE societe_id=%s", [hexid])
                    cur.execute("DELETE FROM utilisateur_societe WHERE societe_id=%s",
                                [hexid])
                code = s.code
                s.delete()
                services.enregistrer_audit(request.user.id, "DELETE", "societe", societe_id,
                                           {"code": code}, None)
            return Response({"ok": True})
        payload = request.data or {}
        for f in ("nom", "ville", "rccm", "id_nat"):
            v = payload.get(f)
            if v is not None:
                setattr(s, f, v.strip() or None)
        if payload.get("actif") is not None:
            s.actif = payload["actif"]
        s.save()
        services.enregistrer_audit(request.user.id, "UPDATE", "societe", s.id, None,
                                   {"nom": s.nom, "actif": bool(s.actif)})
        return Response({"id": str(s.id), "code": s.code, "nom": s.nom,
                         "actif": bool(s.actif)})


# ── Grille de validation ─────────────────────────────────────────────
def _palier_dict(p: PalierValidation) -> dict:
    appro = (PalierApprobateur.objects.filter(palier_id=p.id)
             .select_related("role").order_by("ordre"))
    return {
        "id": str(p.id), "societe_id": str(p.societe_id) if p.societe_id else None,
        "type_document": p.type_document, "etape": p.etape,
        "montant_min_usd": float(p.montant_min_usd),
        "montant_max_usd": float(p.montant_max_usd)
        if p.montant_max_usd is not None else None,
        "libelle": p.libelle,
        "approbateurs": [{"role_code": a.role.code, "mode": a.mode} for a in appro],
    }


def _set_approbateurs(palier, appros):
    """Remplace les approbateurs — retourne None ou Response d'erreur."""
    PalierApprobateur.objects.filter(palier_id=palier.id).delete()
    for i, a in enumerate(appros, start=1):
        rid = Role.objects.filter(code=a.get("role_code")).values_list(
            "id", flat=True).first()
        if not rid:
            return refus({"detail": f"Rôle inconnu : {a.get('role_code')}"}, status=400)
        PalierApprobateur.objects.create(palier_id=palier.id, role_id=rid,
                                         mode=a.get("mode", "conjoint"), ordre=i)
    return None


class PalierViewSet(MetierModelViewSet):
    """Ressource Palier ; contrats HTTP et validations métier conservés."""
    queryset = PalierValidation.objects.none()
    serializer_class = PalierValidationSerializer
    lookup_url_kwarg = 'palier_id'

    def list(self, request):
        return self._traiter_paliers(request)


    def create(self, request):
        return self._traiter_paliers(request)


    def _traiter_paliers(self, request):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        if request.method == "POST":
            payload = request.data or {}
            if payload.get("niveau") not in NIVEAUX:
                return refus({"detail": "Niveau invalide."}, status=400)
            type_doc, etape = NIVEAUX[payload["niveau"]]
            with transaction.atomic():
                p = PalierValidation.objects.create(
                    societe_id=payload.get("societe_id"), type_document=type_doc,
                    etape=etape, montant_min_usd=payload.get("montant_min_usd", 0),
                    montant_max_usd=payload.get("montant_max_usd"),
                    libelle=payload.get("libelle") or "")
                err = _set_approbateurs(p, payload.get("approbateurs") or [])
                if err is not None:
                    return err
                services.enregistrer_audit(request.user.id, "INSERT", "palier_validation",
                                           p.id, None, {"niveau": payload["niveau"]})
            return Response({"id": str(p.id)}, status=201)
        societe_id = request.query_params.get("societe_id")
        q = PalierValidation.objects.filter(societe_id=societe_id) if societe_id \
            else PalierValidation.objects.filter(societe_id__isnull=True)
        out = {"demande": [], "sortie_fonds": []}
        for p in q.order_by("etape", "montant_min_usd"):
            out.setdefault(p.etape, []).append(_palier_dict(p))
        return Response(out)


    def update(self, request, palier_id):
        return self._traiter_palier_detail(request, palier_id)


    def destroy(self, request, palier_id):
        return self._traiter_palier_detail(request, palier_id)


    def _traiter_palier_detail(self, request, palier_id):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        p = PalierValidation.objects.filter(id=palier_id).first()
        if not p:
            return refus({"detail": "Palier introuvable."}, status=404)
        if request.method == "DELETE":
            with transaction.atomic():
                PalierApprobateur.objects.filter(palier_id=p.id).delete()
                p.delete()
                services.enregistrer_audit(request.user.id, "DELETE", "palier_validation",
                                           palier_id, None, None)
            return Response({"ok": True})
        payload = request.data or {}
        with transaction.atomic():
            p.montant_min_usd = payload.get("montant_min_usd", 0)
            p.montant_max_usd = payload.get("montant_max_usd")
            p.libelle = payload.get("libelle") or ""
            p.save()
            err = _set_approbateurs(p, payload.get("approbateurs") or [])
            if err is not None:
                return err
            services.enregistrer_audit(request.user.id, "UPDATE", "palier_validation",
                                       p.id, None, None)
        return Response({"id": str(p.id)})


# ── Seuils & délais ──────────────────────────────────────────────────


class ParametreViewSet(MetierModelViewSet):
    """Ressource Parametre ; contrats HTTP et validations métier conservés."""
    queryset = Parametre.objects.none()
    serializer_class = ParametreSerializer
    lookup_url_kwarg = 'parametre_id'

    def list(self, request):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        societe_id = request.query_params.get("societe_id")
        q = Parametre.objects.filter(societe_id=societe_id) if societe_id \
            else Parametre.objects.filter(societe__isnull=True)
        return Response([{"id": str(p.id), "cle": p.cle, "valeur": p.valeur,
                          "description": p.description} for p in q.order_by("cle")])


    def update(self, request, parametre_id):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        p = Parametre.objects.filter(id=parametre_id).first()
        if not p:
            return refus({"detail": "Paramètre introuvable."}, status=404)
        ancienne = p.valeur
        p.valeur = (request.data or {}).get("valeur")
        p.save(update_fields=["valeur"])
        services.enregistrer_audit(request.user.id, "UPDATE", "parametre", p.id,
                                   {"valeur": ancienne}, {"valeur": p.valeur})
        return Response({"id": str(p.id), "valeur": p.valeur})


# ── Intervenants & agents ────────────────────────────────────────────
class IntervenantViewSet(MetierModelViewSet):
    """Ressource Intervenant ; contrats HTTP et validations métier conservés."""
    queryset = Tiers.objects.none()
    serializer_class = TiersSerializer

    def list(self, request):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        societe_id = request.query_params.get("societe_id")
        rows = (UtilisateurSociete.objects.filter(societe_id=societe_id)
                .select_related("utilisateur", "role").order_by("-role__niveau"))
        return Response([{"utilisateur_id": str(a.utilisateur.id), "nom": a.utilisateur.nom,
                          "email": a.utilisateur.email, "role_code": a.role.code,
                          "role_libelle": a.role.libelle} for a in rows])


class UtilisateurViewSet(MetierModelViewSet):
    """Ressource Utilisateur ; contrats HTTP et validations métier conservés."""
    queryset = Utilisateur.objects.none()
    serializer_class = UtilisateurSerializer
    lookup_url_kwarg = 'utilisateur_id'

    def list(self, request):
        return self._traiter_utilisateurs(request)


    def create(self, request):
        return self._traiter_utilisateurs(request)


    def _traiter_utilisateurs(self, request):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        if request.method == "POST":
            payload = request.data or {}
            email = (payload.get("email") or "").strip().lower()
            password = payload.get("password") or ""
            if "@" not in email or len(password) < 6:
                return refus({"detail": "Email valide et mot de passe d'au moins 6 "
                                        "caractères requis."}, status=400)
            if Utilisateur.objects.filter(email=email).exists():
                return refus({"detail": f"{email} existe déjà."}, status=409)
            with transaction.atomic():
                u = Utilisateur.objects.create(
                    email=email, nom=(payload.get("nom") or "").strip(),
                    prenom=(payload.get("prenom") or "").strip() or None,
                    password_hash=bcrypt.hashpw(password.encode("utf-8")[:72],
                                                bcrypt.gensalt()).decode("utf-8"),
                    created_at=services.maintenant())
                roles_par_code = {r.code: r for r in Role.objects.all()}
                n = 0
                for a in payload.get("affectations") or []:
                    role = roles_par_code.get(str(a.get("role_code", "")).upper())
                    try:
                        sid = uuidlib.UUID(str(a.get("societe_id")))
                    except (ValueError, TypeError):
                        continue
                    if role and Societe.objects.filter(id=sid).exists():
                        _inserer_affectation(u.id, sid, role.id)
                        n += 1
                services.enregistrer_audit(request.user.id, "INSERT", "utilisateur", u.id,
                                           None, {"email": email, "affectations": n})
            return Response({"id": str(u.id), "email": u.email, "nom": u.nom,
                             "affectations": n}, status=201)
        socs = dict(Societe.objects.values_list("id", "code"))
        roles_d = dict(Role.objects.values_list("id", "code"))
        out = []
        for u in Utilisateur.objects.all().order_by("nom"):
            affs = UtilisateurSociete.objects.filter(utilisateur_id=u.id)
            out.append({"id": str(u.id), "nom": u.nom, "prenom": u.prenom,
                        "email": u.email, "actif": bool(u.actif),
                        "affectations": sorted({f"{roles_d.get(a.role_id, '?')}"
                                                f"@{socs.get(a.societe_id, '?')}"
                                                for a in affs})})
        return Response(out)


    def partial_update(self, request, utilisateur_id):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        u = Utilisateur.objects.filter(id=utilisateur_id).first()
        if not u:
            return refus({"detail": "Utilisateur introuvable."}, status=404)
        payload = request.data or {}
        if payload.get("nom"):
            u.nom = payload["nom"].strip()
        if payload.get("prenom") is not None:
            u.prenom = payload["prenom"].strip() or None
        if payload.get("email"):
            email = payload["email"].strip().lower()
            if "@" not in email:
                return refus({"detail": "Email invalide."}, status=400)
            if Utilisateur.objects.filter(email=email).exclude(id=u.id).exists():
                return refus({"detail": f"{email} est déjà utilisé."}, status=409)
            u.email = email
        if payload.get("actif") is not None:
            if u.id == request.user.id and not payload["actif"]:
                return refus({"detail": "Impossible de se désactiver soi-même."},
                             status=400)
            u.actif = payload["actif"]
        if payload.get("password"):
            if len(payload["password"]) < 6:
                return refus({"detail": "Mot de passe : 6 caractères minimum."}, status=400)
            u.password_hash = bcrypt.hashpw(payload["password"].encode("utf-8")[:72],
                                            bcrypt.gensalt()).decode("utf-8")
        u.save()
        services.enregistrer_audit(request.user.id, "UPDATE", "utilisateur", u.id, None,
                                   {"actif": bool(u.actif),
                                    "mdp_change": bool(payload.get("password"))})
        return Response({"ok": True})


class AffectationViewSet(MetierModelViewSet):
    """Ressource Affectation ; contrats HTTP et validations métier conservés."""
    queryset = UtilisateurSociete.objects.none()
    serializer_class = UtilisateurSocieteSerializer

    def create(self, request):
        return self._traiter_affectations(request)


    def destroy(self, request):
        return self._traiter_affectations(request)


    def _traiter_affectations(self, request):
        if not _est_admin(request.user):
            return refus({"detail": "Accès paramétrage réservé au DFI / Président / "
                                    "Admin."}, status=403)
        payload = request.data or {}
        rid = Role.objects.filter(code=payload.get("role_code")).values_list(
            "id", flat=True).first()
        if not rid:
            return refus({"detail": "Rôle inconnu."}, status=400)
        if request.method == "DELETE":
            _supprimer_affectation(payload["utilisateur_id"], payload["societe_id"], rid)
            services.enregistrer_audit(request.user.id, "DELETE", "utilisateur_societe",
                                       payload["utilisateur_id"],
                                       {"role": payload["role_code"]}, None)
            return Response({"ok": True})
        if UtilisateurSociete.objects.filter(utilisateur_id=payload.get("utilisateur_id"),
                                             societe_id=payload.get("societe_id"),
                                             role_id=rid).exists():
            return refus({"detail": "Affectation déjà existante."}, status=409)
        _inserer_affectation(payload["utilisateur_id"], payload["societe_id"], rid)
        services.enregistrer_audit(request.user.id, "INSERT", "utilisateur_societe",
                                   payload["utilisateur_id"], None,
                                   {"role": payload["role_code"]})
        return Response({"ok": True}, status=201)


# ── Pièces jointes ───────────────────────────────────────────────────
def _safe(nom: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", nom)[:120] or "fichier"


def _autoriser_piece(user, document_type, document_id):
    """Les justificatifs héritent du périmètre société de leur document."""
    from .auth import assert_acces_societe
    from .models import DocumentFlotte, Reception, OrdreDepense, Justification
    modeles = {"requisition": Requisition, "ecriture": Ecriture, "commande": Commande,
               "reception": Reception, "document_flotte": DocumentFlotte,
               "facture": Facture, "devis": Devis, "course": Course,
               "avance": Avance, "ordre_depense": OrdreDepense}
    try:
        identifiant = uuidlib.UUID(str(document_id))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({"detail": "Identifiant de document invalide."})
    if document_type == "justification":
        doc = Justification.objects.filter(id=identifiant).first()
        parent = Avance.objects.filter(id=doc.avance_id).first() if doc else None
        sid = parent.societe_id if parent else None
    else:
        modele = modeles.get(document_type)
        if modele is None:
            raise ValidationError({"detail": "Type de document non pris en charge."})
        doc = modele.objects.filter(id=identifiant).first()
        sid = doc.societe_id if doc else None
    if sid is None:
        raise NotFound("Document introuvable.")
    assert_acces_societe(user, sid)


class PieceJointeViewSet(MetierModelViewSet):
    """Ressource PieceJointe ; contrats HTTP et validations métier conservés."""
    queryset = PieceJointe.objects.none()
    serializer_class = PieceJointeSerializer
    lookup_url_kwarg = 'piece_id'

    def list(self, request):
        return self._traiter_pieces_jointes(request)


    def create(self, request):
        return self._traiter_pieces_jointes(request)


    def _traiter_pieces_jointes(self, request):
        if request.method == "POST":
            f = request.FILES.get("file")
            document_type = request.data.get("document_type")
            document_id = request.data.get("document_id")
            if not f or not document_type or not document_id:
                return refus({"detail": "document_type, document_id et file requis."},
                             status=422)
            _autoriser_piece(request.user, document_type, document_id)
            if f.size > MAX_OCTETS:
                return refus({"detail": "Fichier trop volumineux (max 10 Mo)."}, status=413)
            data = f.read()
            if len(data) > MAX_OCTETS:
                return refus({"detail": "Fichier trop volumineux (max 10 Mo)."}, status=413)
            UPLOADS.mkdir(exist_ok=True)
            nom = _safe(f.name or "fichier")
            stockage = f"{uuidlib.uuid4().hex}_{nom}"
            (UPLOADS / stockage).write_bytes(data)
            pj = PieceJointe.objects.create(
                document_type=document_type, document_id=document_id, nom_fichier=nom,
                chemin_stockage=stockage, mime_type=f.content_type,
                taille_octets=len(data), uploaded_by=request.user.id,
                uploaded_at=services.maintenant())
            services.enregistrer_audit(request.user.id, "UPLOAD", document_type,
                                       document_id, None, {"piece": nom})
            return Response({"id": str(pj.id), "nom_fichier": nom,
                             "taille_octets": len(data)}, status=201)
        _autoriser_piece(request.user, request.query_params.get("document_type"),
                         request.query_params.get("document_id"))
        rows = PieceJointe.objects.filter(
            document_type=request.query_params.get("document_type"),
            document_id=request.query_params.get("document_id")).order_by("uploaded_at")
        return Response([{"id": str(p.id), "nom_fichier": p.nom_fichier,
                          "mime_type": p.mime_type, "taille_octets": p.taille_octets}
                         for p in rows])


    @action(detail=True, methods=['get'])
    def download(self, request, piece_id):
        pj = PieceJointe.objects.filter(id=piece_id).first()
        if not pj:
            return refus({"detail": "Pièce introuvable."}, status=404)
        _autoriser_piece(request.user, pj.document_type, pj.document_id)
        chemin = (UPLOADS / pj.chemin_stockage).resolve()
        if not chemin.is_relative_to(UPLOADS.resolve()) or not chemin.is_file():
            return refus({"detail": "Fichier absent du stockage."}, status=404)
        return FileResponse(open(chemin, "rb"), as_attachment=True,
                            filename=pj.nom_fichier,
                            content_type=pj.mime_type or "application/octet-stream")


# Anciens points d’entrée conservés pour les intégrations existantes.
roles = RoleViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='role')
role_detail = RoleViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}, http_method_names=['patch', 'delete', 'options'], detail=True, basename='role')
societes_config = SocieteViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='societe')
societe_detail = SocieteViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}, http_method_names=['patch', 'delete', 'options'], detail=True, basename='societe')
paliers = PalierViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='palier')
palier_detail = PalierViewSet.as_view({'put': 'update', 'delete': 'destroy'}, http_method_names=['put', 'delete', 'options'], detail=True, basename='palier')
parametres = ParametreViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='parametre')
modifier_parametre = ParametreViewSet.as_view({'put': 'update'}, http_method_names=['put', 'options'], detail=True, basename='parametre')
intervenants = IntervenantViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='intervenant')
utilisateurs = UtilisateurViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='utilisateur')
maj_utilisateur = UtilisateurViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='utilisateur')
affectations = AffectationViewSet.as_view({'post': 'create', 'delete': 'destroy'}, http_method_names=['post', 'delete', 'options'], detail=False, basename='affectation')
pieces_jointes = PieceJointeViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='piece_jointe')
telecharger_piece = PieceJointeViewSet.as_view({'get': 'download'}, http_method_names=['get', 'options'], detail=True, basename='piece_jointe')
