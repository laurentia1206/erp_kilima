"""Phase 0 — auth & lecture de base (parité exacte avec backend/app/routers/auth.py
et le /api/societes de lecture.py)."""
from __future__ import annotations

from rest_framework.decorators import action
from core.viewsets import MetierModelViewSet, MetierViewSet
from core.models import Societe
from core.serializers import SocieteSerializer
from core.models import Tiers
from core.serializers import TiersSerializer
from core.models import TauxChange
from core.serializers import TauxChangeSerializer
from apps.tresorerie.models import CompteBancaire
from core.serializers import CompteBancaireSerializer

from datetime import datetime, timezone

import bcrypt
from rest_framework.views import APIView
from rest_framework.response import Response

from .auth import creer_token
from .models import Utilisateur, UtilisateurSociete


class LoginView(APIView):
    'POST /api/auth/login — form-urlencoded username/password (comme OAuth2).'
    http_method_names = ['post', 'options']
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        """POST /api/auth/login — form-urlencoded username/password (comme OAuth2)."""
        from core.audit import security_event, identity_fingerprint
        username = request.data.get("username", "")
        password = request.data.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str):
            security_event(request._request, 'CONNEXION_ECHEC', details={'raison':'formulaire_invalide'})
            return Response({"detail": "Email et mot de passe doivent être du texte."}, status=400)
        username = username.strip()
        user = Utilisateur.objects.filter(email=username).first()
        try:
            ok = bool(user) and bcrypt.checkpw(password.encode("utf-8")[:72], user.password_hash.encode("utf-8"))
        except (ValueError, TypeError):
            ok = False
        if not ok:
            security_event(request._request, 'CONNEXION_ECHEC', user, {'raison':'identifiants_invalides','identifiant_empreinte':identity_fingerprint(username)})
            return Response({"detail": "Email ou mot de passe incorrect."}, status=401)
        if not user.actif:
            security_event(request._request, 'CONNEXION_ECHEC', user, {'raison':'compte_desactive'})
            return Response({"detail": "Compte désactivé."}, status=403)
        # datetime naïf (UTC) — cohérent avec USE_TZ=False et le stockage SQLAlchemy
        request._request.audit_actor=user.id
        Utilisateur.objects.filter(id=user.id).update(
            last_login=datetime.now(timezone.utc).replace(tzinfo=None))
        security_event(request._request, 'CONNEXION_REUSSIE', user)
        return Response({"access_token": creer_token(user.id,user.password_hash), "token_type": "bearer"})

login = LoginView.as_view()


class LogoutView(APIView):
    """Trace la déconnexion volontaire ; le client supprime ensuite son jeton local."""
    http_method_names = ['post', 'options']

    def post(self, request):
        from .audit import security_event
        security_event(request._request, 'DECONNEXION', request.user)
        return Response({'ok': True})


class MeView(APIView):
    http_method_names = ['get', 'options']

    def get(self, request):
        u = request.user
        from .permissions import est_super_admin, ACTIONS
        from .models import PermissionModule, SuperAdministrateur
        return Response({"id": str(u.id), "email": u.email, "nom": u.nom, "prenom": u.prenom,
            'super_administrateur':est_super_admin(u),
            'changer_mot_de_passe':SuperAdministrateur.objects.filter(utilisateur=u,changer_mot_de_passe=True).exists(),
            'permissions':{r.module:{a:getattr(r,a) for a in ACTIONS} for r in PermissionModule.objects.filter(utilisateur=u)}})

me = MeView.as_view()


def _societe_param(request):
    sid = request.query_params.get("societe_id")
    if not sid:
        # même corps 422 que la validation Pydantic de FastAPI
        from .erreurs import Parametre422
        raise Parametre422({"detail": [{"type": "missing",
                                        "loc": ["query", "societe_id"],
                                        "msg": "Field required", "input": None}]})
    return sid


class TiersViewSet(MetierModelViewSet):
    """Ressource Tiers ; contrats HTTP et validations métier conservés."""
    queryset = Tiers.objects.none()
    serializer_class = TiersSerializer

    def list(self, request):
        """GET /api/tiers — parité avec lecture.py (tiers actifs, société + groupe)."""
        from django.db.models import Q
        from .auth import assert_acces_societe
        from .models import Tiers
        sid = _societe_param(request)
        assert_acces_societe(request.user, sid)
        q = Tiers.objects.filter(Q(societe_id=sid) | Q(societe_id__isnull=True), actif=True)
        type_ = request.query_params.get("type")
        if type_:
            q = q.filter(type=type_)
        return Response([{"id": str(t.id), "code": t.code, "nom": t.nom, "type": t.type,
                          "societe_id":str(t.societe_id) if t.societe_id else None, "actif":bool(t.actif)}
                         for t in q])


def _session_ouverte(caisse_id):
    from .models import SessionCaisse
    return SessionCaisse.objects.filter(caisse_id=caisse_id, statut="ouverte").first()


def _soldes(sess):
    """Solde théorique par devise = fond initial + entrées − sorties (session)."""
    from .models import MouvementCaisse
    soldes = {"USD": float(sess.fond_initial_usd), "CDF": float(sess.fond_initial_cdf)}
    for m in MouvementCaisse.objects.filter(session_id=sess.id).values("devise", "sens", "montant"):
        soldes.setdefault(m["devise"], 0.0)
        soldes[m["devise"]] += float(m["montant"]) if m["sens"] == "entree" else -float(m["montant"])
    return {k: round(v, 2) for k, v in soldes.items()}


class ListerCaissesView(APIView):
    'GET /api/caisses — avec état de session et soldes temps réel (parité).'
    http_method_names = ['get', 'options']

    def get(self, request):
        """GET /api/caisses — avec état de session et soldes temps réel (parité)."""
        from .auth import assert_acces_societe
        from .models import Caisse
        sid = _societe_param(request)
        assert_acces_societe(request.user, sid)
        out = []
        for c in Caisse.objects.filter(societe_id=sid, actif=True):
            sess = _session_ouverte(c.id)
            out.append({"id": str(c.id), "libelle": c.libelle, "compte": c.compte_comptable,
                        "est_principale": bool(c.est_principale),
                        "session_ouverte": sess is not None,
                        "ouverte_depuis": sess.date_ouverture.isoformat() if sess and sess.date_ouverture else None,
                        "soldes": _soldes(sess) if sess else None})
        return Response(out)

lister_caisses = ListerCaissesView.as_view()


class CompteBancaireViewSet(MetierModelViewSet):
    """Ressource CompteBancaire ; contrats HTTP et validations métier conservés."""
    queryset = CompteBancaire.objects.none()
    serializer_class = CompteBancaireSerializer

    def list(self, request):
        from .auth import assert_acces_societe
        from .models import CompteBancaire
        sid = _societe_param(request)
        assert_acces_societe(request.user, sid)
        return Response([{"id": str(b.id),
                          "libelle": f"{b.banque} — {b.numero_compte or ''}".strip(" —"),
                          "devise": b.devise}
                         for b in CompteBancaire.objects.filter(societe_id=sid, actif=True)])


class ListerOrdresView(APIView):
    http_method_names = ['get', 'options']

    def get(self, request):
        from .auth import assert_acces_societe
        from .models import OrdreDepense, Requisition, Tiers
        sid = _societe_param(request)
        assert_acces_societe(request.user, sid)
        q = OrdreDepense.objects.filter(societe_id=sid)
        statut = request.query_params.get("statut")
        if statut:
            q = q.filter(statut=statut)
        out = []
        for o in q.order_by("-created_at"):
            benef = Tiers.objects.filter(id=o.beneficiaire_tiers_id).first()
            req = Requisition.objects.filter(id=o.requisition_id).first()
            paye = float(o.montant_paye_usd or 0)
            out.append({"id": str(o.id), "numero": o.numero, "devise": o.devise,
                        "requisition_numero": req.numero if req else None,
                        "requisition_objet": req.objet if req else None,
                        "montant_autorise_usd": float(o.montant_autorise_usd),
                        "montant_paye_usd": round(paye, 2),
                        "reste_usd": round(float(o.montant_autorise_usd) - paye, 2),
                        "palier_applique": o.palier_applique, "statut": o.statut,
                        "mode_paiement": o.mode_paiement, "mode_decaissement": o.mode_decaissement,
                        "motif": o.motif, "beneficiaire": benef.nom if benef else None,
                        "beneficiaire_tiers_id": str(o.beneficiaire_tiers_id)})
        return Response(out)

lister_ordres = ListerOrdresView.as_view()


class EtatComptableViewSet(MetierViewSet):
    """Ressource EtatComptable ; contrats HTTP et validations métier conservés."""

    @action(detail=False, methods=['get'])
    def balance(self, request):
        """GET /api/comptabilite/balance — parité stricte avec compta.py (N \\ N-1)."""
        from datetime import date as _date
        from .auth import assert_acces_societe, assert_role
        from .models import Compte, LigneEcriture
        sid = _societe_param(request)
        roles = assert_acces_societe(request.user, sid)
        assert_role(roles, {"COMPTABLE", "DFI"})
        annee = int(request.query_params.get("annee") or _date.today().year)
        statut = request.query_params.get("statut")
        classe = request.query_params.get("classe")

        q = LigneEcriture.objects.filter(societe_id=sid).values_list(
            "compte_numero", "sens", "montant_usd", "ecriture__date_ecriture")
        if statut:
            q = q.filter(ecriture__statut=statut)
        intitules = dict(Compte.objects.filter(societe_id=sid).values_list("numero", "intitule"))

        agg: dict = {}
        for compte, sens, montant, dte in q:
            an = dte.year
            if an not in (annee, annee - 1):
                continue
            a = agg.setdefault(compte, {"compte": compte, "debit": 0.0, "credit": 0.0, "solde_n1": 0.0})
            m = float(montant)
            if an == annee:
                a["debit" if sens == "D" else "credit"] += m
            else:
                a["solde_n1"] += m if sens == "D" else -m

        lignes, td, tc = [], 0.0, 0.0
        for a in agg.values():
            if classe and not a["compte"].startswith(classe):
                continue
            solde = a["debit"] - a["credit"]
            lignes.append({
                "compte": a["compte"], "intitule": intitules.get(a["compte"], ""),
                "debit": round(a["debit"], 2), "credit": round(a["credit"], 2),
                "solde_debiteur": round(solde, 2) if solde > 0 else 0.0,
                "solde_crediteur": round(-solde, 2) if solde < 0 else 0.0,
                "solde_n1": round(a["solde_n1"], 2),
            })
            td += a["debit"]
            tc += a["credit"]
        lignes.sort(key=lambda x: x["compte"])
        return Response({"annee": annee, "lignes": lignes, "total_debit": round(td, 2),
                         "total_credit": round(tc, 2), "equilibre": round(td, 2) == round(tc, 2)})


class TauxChangeViewSet(MetierModelViewSet):
    """Ressource TauxChange ; contrats HTTP et validations métier conservés."""
    queryset = TauxChange.objects.none()
    serializer_class = TauxChangeSerializer

    def create(self, request):
        """POST /api/taux — réservé DFI/Président (parité avec taux.py)."""
        from .models import Role, TauxChange, UtilisateurSociete
        from . import services
        est_dfi = UtilisateurSociete.objects.filter(
            utilisateur_id=request.user.id,
            role_id__in=Role.objects.filter(code__in=["DFI", "PRESIDENT"]).values("id")).exists()
        if not est_dfi:
            return Response({"detail": "Seul le DFI peut définir le taux du jour."}, status=403)
        d = request.data
        date_taux, devise, taux_usd = d.get("date_taux"), d.get("devise", "CDF"), d.get("taux_usd")
        if not date_taux or not taux_usd:
            return Response({"detail": "date_taux et taux_usd requis."}, status=422)
        existant = TauxChange.objects.filter(date_taux=date_taux, devise=devise).first()
        if existant:
            ancienne = float(existant.taux_usd)
            existant.taux_usd = taux_usd
            existant.defini_par_id = request.user.id
            existant.save(update_fields=["taux_usd", "defini_par_id"])
            services.enregistrer_audit(request.user.id, "UPDATE", "taux_change", existant.id,
                                       {"taux_usd": ancienne}, {"taux_usd": float(taux_usd)})
            return Response({"message": "Taux mis à jour", "id": str(existant.id)})
        t = TauxChange.objects.create(date_taux=date_taux, devise=devise,
                                      taux_usd=taux_usd, defini_par_id=request.user.id,
                                      created_at=services.maintenant())
        services.enregistrer_audit(request.user.id, "INSERT", "taux_change", t.id, None,
                                   {"taux_usd": float(taux_usd)})
        return Response({"message": "Taux défini", "id": str(t.id)}, status=201)


class SocieteViewSet(MetierModelViewSet):
    """Ressource Societe ; contrats HTTP et validations métier conservés."""
    queryset = Societe.objects.none()
    serializer_class = SocieteSerializer

    def list(self, request):
        rows = (UtilisateurSociete.objects.filter(utilisateur_id=request.user.id)
                .values_list("societe_id", "societe__code", "societe__nom", "role__code"))
        out: dict = {}
        for sid, code, nom, role in rows:
            e = out.setdefault(str(sid), {"id": str(sid), "code": code, "nom": nom, "roles": []})
            e["roles"].append(role)
        from .permissions import est_super_admin
        from .auth import roles_pour_societe
        if est_super_admin(request.user):
            out={}
        else:
            for entry in out.values(): entry['roles']=sorted(roles_pour_societe(request.user,entry['id']))
        return Response(list(out.values()))


# Anciens points d’entrée conservés pour les intégrations existantes.
lister_tiers = TiersViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='tiers')
lister_banques = CompteBancaireViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='compte_bancaire')
balance = EtatComptableViewSet.as_view({'get': 'balance'}, http_method_names=['get', 'options'], detail=False, basename='etat_comptable')
definir_taux = TauxChangeViewSet.as_view({'post': 'create'}, http_method_names=['post', 'options'], detail=False, basename='taux_change')
mes_societes = SocieteViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='societe')
