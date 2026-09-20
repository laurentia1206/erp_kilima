"""Module Hôtellerie (Guest House Relax) — chambres, réservations, séjours,
folio et check-out facturé.

Le folio (la note du séjour) regroupe : les nuitées (calculées), les extras
saisis à la réception (blanchisserie, divers…) et les tickets restaurant/bar
envoyés « sur la chambre » par le POS (déjà facturés — affichés sur la note,
exclus de la facture d'hébergement). Le check-out génère la facture de vente
(D 411 / C produit hébergement / C TVA) ; l'encaissement passe par le circuit
de règlement existant (/ventes/factures/<id>/reglement).
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.comptabilite import services as comptabilite
from apps.groupe import services as intersociete_lib
from core import services as services
from core.auth import assert_acces_societe, assert_role
from core.erreurs import refus
from apps.hotel.models import Chambre, LigneSejour, Sejour
from apps.commercial.models import Facture, LigneFacture
from core.models import Societe, Tiers
from core.views import _societe_param
from apps.stocks.catalogue import normaliser, verifier_doublon, verrouiller_catalogue, tiers_visibles

ROLES = {"RECEPTIONNISTE", "CAISSIER_CENTRAL", "COMPTABLE", "DFI", "DG"}
ETATS_CHAMBRE = ("libre", "occupee", "sale", "nettoyage", "maintenance")
SOURCES = ("directe", "telephone", "entreprise", "en_ligne")
STATUTS_OCCUPANTS = ("reservee", "arrivee")


def _acces(request, societe_id):
    roles = assert_acces_societe(request.user, societe_id)
    assert_role(roles, ROLES)
    return roles


# ═══ Chambres & housekeeping ═════════════════════════════════════════

def _chambre_dict(c: Chambre, sejour=None) -> dict:
    d = {"id": str(c.id), "numero": c.numero, "categorie": c.categorie,
         "tarif_nuit_usd": float(c.tarif_nuit_usd or 0), "capacite": c.capacite,
         "etat": c.etat, "note": c.note, "actif": bool(c.actif)}
    if sejour is not None:
        d["sejour"] = sejour
    return d


def _sejour_en_cours(chambre_id):
    return Sejour.objects.filter(chambre_id=chambre_id, statut="arrivee").first()


@api_view(["GET", "POST"])
def chambres(request):
    sid = _societe_param(request)
    _acces(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        numero = (payload.get("numero") or "").strip()
        if not numero:
            return refus({"detail": "numero requis."}, status=422)
        if Chambre.objects.filter(societe_id=sid, numero__iexact=numero,
                                  actif=True).exists():
            return refus({"detail": f"La chambre {numero} existe déjà."}, status=409)
        with transaction.atomic():
            c = Chambre.objects.create(
                societe_id=sid, numero=numero,
                categorie=(payload.get("categorie") or "").strip() or None,
                tarif_nuit_usd=payload.get("tarif_nuit_usd") or 0,
                capacite=payload.get("capacite") or 2,
                note=(payload.get("note") or "").strip() or None,
                created_by=request.user.id, created_at=services.maintenant())
            services.enregistrer_audit(request.user.id, "INSERT", "chambre", c.id,
                                       None, {"numero": numero})
        return Response(_chambre_dict(c), status=201)
    out = []
    for c in Chambre.objects.filter(societe_id=sid).order_by("numero"):
        sej = _sejour_en_cours(c.id)
        out.append(_chambre_dict(c, {
            "id": str(sej.id), "numero": sej.numero, "client": sej.client_nom,
            "date_arrivee": sej.date_arrivee.isoformat(),
            "date_depart_prevue": sej.date_depart_prevue.isoformat()}
            if sej else None))
    return Response(out)


@api_view(["PATCH"])
def maj_chambre(request, chambre_id):
    c = Chambre.objects.filter(id=chambre_id).first()
    if not c:
        return refus({"detail": "Chambre introuvable."}, status=404)
    _acces(request, c.societe_id)
    payload = request.data or {}
    avant = _chambre_dict(c)
    if "etat" in payload:
        etat = payload["etat"]
        if etat not in ETATS_CHAMBRE:
            return refus({"detail": f"etat : {', '.join(ETATS_CHAMBRE)}."},
                         status=422)
        if c.etat == "occupee" and etat != "occupee" and _sejour_en_cours(c.id):
            return refus({"detail": "La chambre est occupée — faites d'abord le "
                                    "check-out du séjour."}, status=409)
        if etat == "occupee" and not _sejour_en_cours(c.id):
            return refus({"detail": "« Occupée » se fait par le check-in d'un "
                                    "séjour."}, status=409)
        c.etat = etat
    if "numero" in payload:
        numero = (payload["numero"] or "").strip()
        if not numero:
            return refus({"detail": "numero requis."}, status=422)
        c.numero = numero
    if "categorie" in payload:
        c.categorie = (payload["categorie"] or "").strip() or None
    if "tarif_nuit_usd" in payload:
        c.tarif_nuit_usd = payload["tarif_nuit_usd"] or 0
    if "capacite" in payload:
        c.capacite = payload["capacite"] or 2
    if "note" in payload:
        c.note = (payload["note"] or "").strip() or None
    if "actif" in payload:
        if payload["actif"] is False and _sejour_en_cours(c.id):
            return refus({"detail": "Chambre occupée — check-out d'abord."},
                         status=409)
        c.actif = bool(payload["actif"])
    with transaction.atomic():
        c.save()
        services.enregistrer_audit(request.user.id, "UPDATE", "chambre", c.id,
                                   avant, _chambre_dict(c))
    return Response(_chambre_dict(c))


# ═══ Séjours (réservations, check-in/out) ════════════════════════════

def _sejour_dict(s: Sejour) -> dict:
    chambre = Chambre.objects.filter(id=s.chambre_id).first()
    fac = Facture.objects.filter(id=s.facture_id).first() if s.facture_id else None
    return {"id": str(s.id), "numero": s.numero,
            "chambre_id": str(s.chambre_id),
            "chambre": chambre.numero if chambre else None,
            "tiers_id": str(s.tiers_id) if s.tiers_id else None,
            "client_nom": s.client_nom, "client_telephone": s.client_telephone,
            "nb_personnes": s.nb_personnes,
            "date_arrivee": s.date_arrivee.isoformat(),
            "date_depart_prevue": s.date_depart_prevue.isoformat(),
            "date_depart": s.date_depart.isoformat() if s.date_depart else None,
            "tarif_nuit_usd": float(s.tarif_nuit_usd or 0),
            "statut": s.statut, "source": s.source, "note": s.note,
            "facture": fac.numero if fac else None,
            "facture_id": str(s.facture_id) if s.facture_id else None}


def _chevauchement(chambre_id, arrivee, depart, exclure_id=None):
    """Séjour occupant la chambre sur [arrivee, depart) — le jour du départ
    est libre pour une nouvelle arrivée."""
    q = Sejour.objects.filter(chambre_id=chambre_id,
                              statut__in=STATUTS_OCCUPANTS,
                              date_arrivee__lt=depart,
                              date_depart_prevue__gt=arrivee)
    if exclure_id:
        q = q.exclude(id=exclure_id)
    return q.first()


def _lire_dates(payload):
    try:
        arrivee = date.fromisoformat(payload.get("date_arrivee"))
        depart = date.fromisoformat(payload.get("date_depart_prevue"))
    except (TypeError, ValueError):
        return None, None, refus({"detail": "date_arrivee et date_depart_prevue "
                                            "requises (YYYY-MM-DD)."}, status=422)
    if depart <= arrivee:
        return None, None, refus({"detail": "La date de départ doit être après "
                                            "l'arrivée (1 nuit minimum)."},
                                 status=422)
    return arrivee, depart, None


@transaction.atomic
def _tiers_du_sejour(sejour, sid, user_id):
    """Le tiers client du séjour — créé à la volée depuis le nom si besoin."""
    if sejour.tiers_id:
        return Tiers.objects.filter(id=sejour.tiers_id).first()
    nom = sejour.client_nom.strip()
    verrouiller_catalogue(sid)
    candidats = [t for t in tiers_visibles(sid).filter(type="client", actif=True)
                 if normaliser(t.nom) == normaliser(nom)]
    if len(candidats) > 1:
        from rest_framework.exceptions import ValidationError
        raise ValidationError('Plusieurs clients portent ce nom. Sélectionnez la fiche exacte avant de poursuivre.')
    t = candidats[0] if candidats else None
    if not t:
        code = f"CLI-{nom.upper()[:12]}-{sejour.numero[-4:]}"
        t = Tiers.objects.create(societe_id=sid, type="client",
                                 code=code[:32], nom=nom[:255])
    sejour.tiers_id = t.id
    sejour.save(update_fields=["tiers_id"])
    return t


@api_view(["GET", "POST"])
@transaction.atomic
def clients(request):
    """La réception peut retrouver/créer les clients qu'elle crée déjà au check-in."""
    from apps.commercial.views import _tiers_dict
    sid = _societe_param(request)
    _acces(request, sid)
    if request.method == 'GET':
        return Response([_tiers_dict(t) for t in tiers_visibles(sid).filter(type='client').order_by('nom')])
    payload = request.data or {}
    if not str(payload.get('code') or '').strip() or len(str(payload.get('nom') or '').strip()) < 2:
        return refus({'detail':'Code et nom du client requis.'}, status=422)
    verrouiller_catalogue(sid)
    verifier_doublon(tiers_visibles(sid), payload, 'nom')
    t = Tiers.objects.create(societe_id=sid, type='client', code=payload['code'].strip().upper(), nom=payload['nom'].strip())
    services.enregistrer_audit(request.user.id, 'INSERT', 'tiers', t.id, None, {'nom':t.nom})
    return Response(_tiers_dict(t), status=201)


@api_view(["GET", "POST"])
def sejours(request):
    sid = _societe_param(request)
    _acces(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        chambre = Chambre.objects.filter(id=payload.get("chambre_id")).first()
        if not chambre or str(chambre.societe_id) != str(sid) or not chambre.actif:
            return refus({"detail": "Chambre invalide."}, status=400)
        client_nom = (payload.get("client_nom") or "").strip()
        if payload.get('tiers_id'):
            client = tiers_visibles(sid).filter(id=payload['tiers_id'], type='client', actif=True).first()
            if not client:
                return refus({'detail':'Choisissez un client actif de cette société.'}, status=422)
            client_nom = client.nom
        if len(client_nom) < 2:
            return refus({"detail": "client_nom requis."}, status=422)
        arrivee, depart, erreur = _lire_dates(payload)
        if erreur:
            return erreur
        source = payload.get("source", "directe")
        if source not in SOURCES:
            return refus({"detail": f"source : {', '.join(SOURCES)}."}, status=422)
        occupe = _chevauchement(chambre.id, arrivee, depart)
        if occupe:
            return refus({"detail": f"La chambre {chambre.numero} est prise sur "
                                    f"ces dates ({occupe.numero} — "
                                    f"{occupe.client_nom})."}, status=409)
        walk_in = bool(payload.get("arrivee_immediate"))
        if walk_in and arrivee != date.today():
            return refus({"detail": "Arrivée immédiate : la date d'arrivée doit "
                                    "être aujourd'hui."}, status=422)
        if walk_in and chambre.etat in ("maintenance", "nettoyage", "sale"):
            return refus({"detail": f"Chambre {chambre.numero} : "
                                    f"{chambre.etat} — remettez-la disponible "
                                    f"avant le check-in."}, status=409)
        societe = Societe.objects.filter(id=sid).first()
        tarif = payload.get("tarif_nuit_usd")
        with transaction.atomic():
            s = Sejour.objects.create(
                societe_id=sid,
                numero=services.next_numero("sejour", date.today().year,
                                            societe.code, societe.id),
                chambre_id=chambre.id,
                tiers_id=payload.get("tiers_id") or None,
                client_nom=client_nom,
                client_telephone=(payload.get("client_telephone") or "").strip()
                or None,
                nb_personnes=payload.get("nb_personnes") or 1,
                date_arrivee=arrivee, date_depart_prevue=depart,
                tarif_nuit_usd=tarif if tarif is not None
                else chambre.tarif_nuit_usd,
                statut="arrivee" if walk_in else "reservee",
                source=source,
                note=(payload.get("note") or "").strip() or None,
                created_by=request.user.id, created_at=services.maintenant())
            if walk_in:
                chambre.etat = "occupee"
                chambre.save(update_fields=["etat"])
                _tiers_du_sejour(s, sid, request.user.id)
            services.enregistrer_audit(request.user.id, "INSERT", "sejour", s.id,
                                       None, {"numero": s.numero,
                                              "client": client_nom,
                                              "statut": s.statut})
        return Response(_sejour_dict(s), status=201)
    q = Sejour.objects.filter(societe_id=sid)
    statut = request.query_params.get("statut")
    if statut:
        q = q.filter(statut=statut)
    du, au = request.query_params.get("du"), request.query_params.get("au")
    if du:
        q = q.filter(date_depart_prevue__gte=du)
    if au:
        q = q.filter(date_arrivee__lte=au)
    return Response([_sejour_dict(s)
                     for s in q.order_by("-date_arrivee", "-created_at")[:300]])


@api_view(["PATCH"])
def maj_sejour(request, sejour_id):
    s = Sejour.objects.filter(id=sejour_id).first()
    if not s:
        return refus({"detail": "Séjour introuvable."}, status=404)
    _acces(request, s.societe_id)
    if s.statut not in ("reservee", "arrivee"):
        return refus({"detail": f"Séjour {s.statut} — non modifiable."}, status=409)
    payload = request.data or {}
    avant = _sejour_dict(s)
    if 'tiers_id' in payload:
        client = tiers_visibles(s.societe_id).filter(id=payload['tiers_id'], type='client', actif=True).first()
        if not client:
            return refus({'detail':'Choisissez un client actif de cette société.'}, status=422)
        # Une identité déjà liée à un séjour ne se remplace pas implicitement.
        if s.tiers_id and str(s.tiers_id) != str(client.id):
            return refus({'detail':'Ce séjour est déjà lié à un autre client.'}, status=409)
        s.tiers_id = client.id
    if "date_arrivee" in payload or "date_depart_prevue" in payload:
        if s.statut == "arrivee" and "date_arrivee" in payload:
            return refus({"detail": "Client déjà arrivé — la date d'arrivée est "
                                    "figée."}, status=409)
        melange = {"date_arrivee": payload.get("date_arrivee",
                                               s.date_arrivee.isoformat()),
                   "date_depart_prevue": payload.get(
                       "date_depart_prevue", s.date_depart_prevue.isoformat())}
        arrivee, depart, erreur = _lire_dates(melange)
        if erreur:
            return erreur
        occupe = _chevauchement(s.chambre_id, arrivee, depart, exclure_id=s.id)
        if occupe:
            return refus({"detail": f"Chambre prise sur ces dates "
                                    f"({occupe.numero})."}, status=409)
        s.date_arrivee, s.date_depart_prevue = arrivee, depart
    for champ in ("client_nom", "client_telephone", "note"):
        if champ in payload:
            valeur = (payload[champ] or "").strip() or None
            if champ == "client_nom" and not valeur:
                return refus({"detail": "client_nom requis."}, status=422)
            setattr(s, champ, valeur)
    if 'tiers_id' in payload and s.tiers_id:
        client = Tiers.objects.filter(id=s.tiers_id).first()
        if client:
            s.client_nom = client.nom
    if "nb_personnes" in payload:
        s.nb_personnes = payload["nb_personnes"] or 1
    if "tarif_nuit_usd" in payload:
        s.tarif_nuit_usd = payload["tarif_nuit_usd"] or 0
    with transaction.atomic():
        s.save()
        services.enregistrer_audit(request.user.id, "UPDATE", "sejour", s.id,
                                   avant, _sejour_dict(s))
    return Response(_sejour_dict(s))


@api_view(["POST"])
def checkin(request, sejour_id):
    s = Sejour.objects.filter(id=sejour_id).first()
    if not s:
        return refus({"detail": "Séjour introuvable."}, status=404)
    _acces(request, s.societe_id)
    if s.statut != "reservee":
        return refus({"detail": f"Séjour {s.statut} — check-in impossible."},
                     status=409)
    chambre = Chambre.objects.filter(id=s.chambre_id).first()
    if chambre.etat in ("sale", "nettoyage", "maintenance"):
        return refus({"detail": f"Chambre {chambre.numero} : {chambre.etat} — "
                                f"remettez-la disponible avant le check-in."},
                     status=409)
    if _sejour_en_cours(chambre.id):
        return refus({"detail": f"Chambre {chambre.numero} déjà occupée."},
                     status=409)
    with transaction.atomic():
        s.statut = "arrivee"
        if s.date_arrivee != date.today():
            s.date_arrivee = date.today()
            if s.date_depart_prevue <= s.date_arrivee:
                s.date_depart_prevue = s.date_arrivee + timedelta(days=1)
        s.save()
        chambre.etat = "occupee"
        chambre.save(update_fields=["etat"])
        _tiers_du_sejour(s, s.societe_id, request.user.id)
        services.enregistrer_audit(request.user.id, "CHECKIN", "sejour", s.id,
                                   None, {"numero": s.numero})
    return Response(_sejour_dict(s))


@api_view(["POST"])
def annuler_sejour(request, sejour_id):
    s = Sejour.objects.filter(id=sejour_id).first()
    if not s:
        return refus({"detail": "Séjour introuvable."}, status=404)
    _acces(request, s.societe_id)
    if s.statut != "reservee":
        return refus({"detail": "Seule une réservation (avant arrivée) peut être "
                                "annulée ou déclarée no-show."}, status=409)
    no_show = bool((request.data or {}).get("no_show"))
    with transaction.atomic():
        s.statut = "no_show" if no_show else "annulee"
        s.save(update_fields=["statut"])
        services.enregistrer_audit(request.user.id, "UPDATE", "sejour", s.id,
                                   None, {"numero": s.numero, "statut": s.statut})
    return Response(_sejour_dict(s))


# ═══ Folio ═══════════════════════════════════════════════════════════

def _nuits(s: Sejour) -> int:
    fin = s.date_depart or s.date_depart_prevue
    return max(1, (fin - s.date_arrivee).days)


def _folio_data(s: Sejour) -> dict:
    from apps.commercial.views import _reglement_facture
    nuits = _nuits(s)
    montant_nuitees = round(nuits * float(s.tarif_nuit_usd or 0), 2)
    lignes = list(LigneSejour.objects.filter(sejour_id=s.id)
                  .order_by("date_ligne", "created_at"))
    extras = [ln for ln in lignes if not ln.facture_pos_id]
    tickets = [ln for ln in lignes if ln.facture_pos_id]
    total_extras = round(sum(float(ln.montant_usd or 0) for ln in extras), 2)
    total_tickets = round(sum(float(ln.montant_usd or 0) for ln in tickets), 2)

    tickets_out = []
    solde_tickets = 0.0
    for ln in tickets:
        fac_pos = Facture.objects.filter(id=ln.facture_pos_id).first()
        solde = _reglement_facture(fac_pos)["solde_du_usd"] if fac_pos else 0.0
        solde_tickets = round(solde_tickets + solde, 2)
        tickets_out.append({"id": str(ln.id),
                            "date": ln.date_ligne.isoformat(),
                            "designation": ln.designation,
                            "montant_usd": float(ln.montant_usd),
                            "origine": ln.origine,
                            "facture_pos_id": str(ln.facture_pos_id),
                            "solde_du_usd": solde})
    facture_sejour = None
    solde_sejour = 0.0
    if s.facture_id:
        fac = Facture.objects.filter(id=s.facture_id).first()
        if fac:
            sit = _reglement_facture(fac)
            solde_sejour = sit["solde_du_usd"]
            facture_sejour = {"id": str(fac.id), "numero": fac.numero,
                              "total_ht": float(fac.total_ht or 0),
                              "total_tva": float(fac.total_tva or 0),
                              "total_ttc": float(fac.total_ttc or 0),
                              "paye_usd": sit.get("regle_usd", 0.0),
                              "solde_du_usd": solde_sejour}
    return {"sejour": _sejour_dict(s), "nuits": nuits,
            "montant_nuitees": montant_nuitees,
            "extras": [{"id": str(ln.id), "date": ln.date_ligne.isoformat(),
                        "designation": ln.designation, "qte": float(ln.qte),
                        "prix_unitaire": float(ln.prix_unitaire),
                        "montant_usd": float(ln.montant_usd),
                        "origine": ln.origine} for ln in extras],
            "tickets_pos": tickets_out,
            "total_extras": total_extras,
            "total_tickets_pos": total_tickets,
            "total_a_facturer": round(montant_nuitees + total_extras, 2),
            "total_note": round(montant_nuitees + total_extras + total_tickets, 2),
            "facture_sejour": facture_sejour,
            "solde_du_usd": round(solde_sejour + solde_tickets, 2)}


@api_view(["GET"])
def folio(request, sejour_id):
    s = Sejour.objects.filter(id=sejour_id).first()
    if not s:
        return refus({"detail": "Séjour introuvable."}, status=404)
    _acces(request, s.societe_id)
    return Response(_folio_data(s))


@api_view(["POST"])
def ajouter_ligne(request, sejour_id):
    s = Sejour.objects.filter(id=sejour_id).first()
    if not s:
        return refus({"detail": "Séjour introuvable."}, status=404)
    _acces(request, s.societe_id)
    if s.statut != "arrivee":
        return refus({"detail": "Les extras s'ajoutent sur un séjour en cours."},
                     status=409)
    payload = request.data or {}
    designation = (payload.get("designation") or "").strip()
    if len(designation) < 2:
        return refus({"detail": "designation requise."}, status=422)
    try:
        qte = round(float(payload.get("qte", 1)), 2)
        prix = round(float(payload.get("prix_unitaire")), 2)
        if qte <= 0 or prix < 0:
            raise ValueError
    except (TypeError, ValueError):
        return refus({"detail": "qte > 0 et prix_unitaire >= 0 requis."},
                     status=422)
    origine = payload.get("origine", "divers")
    with transaction.atomic():
        ln = LigneSejour.objects.create(
            sejour_id=s.id, date_ligne=date.today(), designation=designation,
            qte=qte, prix_unitaire=prix, montant_usd=round(qte * prix, 2),
            origine=origine[:16], created_by=request.user.id,
            created_at=services.maintenant())
        services.enregistrer_audit(request.user.id, "INSERT", "ligne_sejour",
                                   ln.id, None, {"sejour": s.numero,
                                                 "designation": designation})
    return Response(_folio_data(s), status=201)


@api_view(["DELETE"])
def supprimer_ligne(request, sejour_id, ligne_id):
    s = Sejour.objects.filter(id=sejour_id).first()
    ln = LigneSejour.objects.filter(id=ligne_id, sejour_id=sejour_id).first()
    if not s or not ln:
        return refus({"detail": "Ligne introuvable."}, status=404)
    _acces(request, s.societe_id)
    if s.statut != "arrivee":
        return refus({"detail": "Séjour clôturé — note figée."}, status=409)
    if ln.facture_pos_id:
        return refus({"detail": "Ticket POS déjà facturé — annulez-le côté POS "
                                "(retour) si besoin."}, status=409)
    with transaction.atomic():
        services.enregistrer_audit(request.user.id, "DELETE", "ligne_sejour",
                                   ligne_id, {"designation": ln.designation}, None)
        ln.delete()
    return Response(_folio_data(s))


@api_view(["POST"])
def checkout(request, sejour_id):
    """Départ : facture d'hébergement (nuitées + extras), chambre à nettoyer.
    L'encaissement se fait ensuite par le règlement de facture existant."""
    s = Sejour.objects.filter(id=sejour_id).first()
    if not s:
        return refus({"detail": "Séjour introuvable."}, status=404)
    _acces(request, s.societe_id)
    if s.statut != "arrivee":
        return refus({"detail": "Seul un séjour en cours peut faire son "
                                "check-out."}, status=409)
    s.date_depart = date.today()
    if s.date_depart < s.date_arrivee:
        return refus({"detail": "Date de départ avant l'arrivée ?"}, status=409)
    tiers = _tiers_du_sejour(s, s.societe_id, request.user.id)
    donnees = _folio_data(s)
    societe = Societe.objects.filter(id=s.societe_id).first()
    chambre = Chambre.objects.filter(id=s.chambre_id).first()
    jour = date.today()
    taux_tva = float(services.get_parametre("tva.taux_defaut", s.societe_id, "16"))
    with transaction.atomic():
        numero = services.next_numero("facture_vente", jour.year,
                                      societe.code, societe.id)
        fac = Facture.objects.create(
            societe_id=s.societe_id, type="vente", numero=numero,
            tiers_id=tiers.id, date_facture=jour,
            reference=s.numero, statut="validee",
            created_by=request.user.id, created_at=services.maintenant())
        lignes_payload = [{
            "designation": f"Hébergement chambre {chambre.numero} — "
                           f"{donnees['nuits']} nuit(s) du "
                           f"{s.date_arrivee.strftime('%d/%m')} au "
                           f"{s.date_depart.strftime('%d/%m/%Y')}",
            "qte": donnees["nuits"], "pu": float(s.tarif_nuit_usd or 0)}]
        for extra in donnees["extras"]:
            lignes_payload.append({"designation": extra["designation"],
                                   "qte": extra["qte"],
                                   "pu": extra["prix_unitaire"]})
        total_ht = total_tva = 0.0
        for lp in lignes_payload:
            ht = round(float(lp["qte"]) * float(lp["pu"]), 2)
            tva = round(ht * taux_tva / 100, 2)
            LigneFacture.objects.create(
                facture_id=fac.id, article_id=None,
                designation=lp["designation"][:255], qte=lp["qte"],
                prix_unitaire=lp["pu"], taux_tva=taux_tva,
                montant_ht=ht, montant_tva=tva)
            total_ht = round(total_ht + ht, 2)
            total_tva = round(total_tva + tva, 2)
        fac.total_ht = total_ht
        fac.total_tva = total_tva
        fac.total_ttc = round(total_ht + total_tva, 2)
        lignes_ecr = [{"sens": "D",
                       "compte": comptabilite._compte("compte_client",
                                                      s.societe_id),
                       "montant_usd": float(fac.total_ttc), "tiers_id": tiers.id,
                       "libelle": f"Séjour {s.numero} — {tiers.nom}"},
                      {"sens": "C",
                       "compte": comptabilite._compte("compte_vente_hebergement",
                                                      s.societe_id),
                       "montant_usd": total_ht,
                       "libelle": f"Hébergement {s.numero}"}]
        if total_tva:
            lignes_ecr.append({"sens": "C",
                               "compte": comptabilite._compte("tva_collectee",
                                                              s.societe_id),
                               "montant_usd": total_tva,
                               "libelle": f"TVA collectée {numero}"})
        statut_piece = intersociete_lib._statut_piece(s.societe_id, "vente")
        ecr = comptabilite.post_ecriture(
            s.societe_id, "VE", "Ventes", "vente", jour,
            f"Facture séjour {numero} — {tiers.nom}", lignes_ecr,
            "facture_vente", "facture", fac.id, numero,
            request.user.id, statut=statut_piece)
        fac.ecriture_id = ecr.id
        fac.save()
        s.statut = "terminee"
        s.facture_id = fac.id
        s.save()
        chambre.etat = "sale"
        chambre.save(update_fields=["etat"])
        services.enregistrer_audit(request.user.id, "CHECKOUT", "sejour", s.id,
                                   None, {"numero": s.numero,
                                          "facture": numero,
                                          "total_ttc": float(fac.total_ttc)})
    return Response({"sejour": _sejour_dict(s),
                     "facture": {"id": str(fac.id), "numero": numero,
                                 "total_ht": total_ht, "total_tva": total_tva,
                                 "total_ttc": float(fac.total_ttc)},
                     "tickets_pos_a_encaisser": donnees["tickets_pos"],
                     "total_note": round(float(fac.total_ttc)
                                         + donnees["total_tickets_pos"], 2)},
                    status=201)


# ═══ Planning & rapport d'occupation ═════════════════════════════════

@api_view(["GET"])
def planning(request):
    """Grille chambres x jours : qui occupe/réserve quoi sur la période."""
    sid = _societe_param(request)
    _acces(request, sid)
    try:
        du = date.fromisoformat(request.query_params.get("du"))
    except (TypeError, ValueError):
        du = date.today()
    try:
        nb_jours = min(31, max(7, int(request.query_params.get("jours", 14))))
    except ValueError:
        nb_jours = 14
    au = du + timedelta(days=nb_jours)
    sejours_l = list(Sejour.objects.filter(societe_id=sid,
                                           statut__in=STATUTS_OCCUPANTS,
                                           date_arrivee__lt=au,
                                           date_depart_prevue__gt=du))
    out = []
    for c in Chambre.objects.filter(societe_id=sid, actif=True).order_by("numero"):
        occ = [{"sejour_id": str(s.id), "numero": s.numero,
                "client": s.client_nom, "statut": s.statut,
                "du": s.date_arrivee.isoformat(),
                "au": s.date_depart_prevue.isoformat()}
               for s in sejours_l if s.chambre_id == c.id]
        out.append({**_chambre_dict(c), "occupations": occ})
    return Response({"du": du.isoformat(), "jours": nb_jours, "chambres": out})


@api_view(["GET"])
def rapport_hotel(request):
    """Taux d'occupation, nuitées, revenus — indicateurs standard (ADR, RevPAR)."""
    sid = _societe_param(request)
    _acces(request, sid)
    try:
        du = date.fromisoformat(request.query_params.get("du"))
        au = date.fromisoformat(request.query_params.get("au"))
    except (TypeError, ValueError):
        au = date.today()
        du = au.replace(day=1)
    if au < du:
        du, au = au, du
    nb_chambres = Chambre.objects.filter(societe_id=sid, actif=True).count()
    jours = (au - du).days + 1
    capacite = nb_chambres * jours
    sejours_l = list(Sejour.objects.filter(
        societe_id=sid, statut__in=["arrivee", "terminee"],
        date_arrivee__lte=au))
    nuitees = 0
    revenu = 0.0
    for s in sejours_l:
        fin = s.date_depart or s.date_depart_prevue
        # day-use (arrivée = départ) : facturé et compté 1 nuit minimum
        fin = max(fin, s.date_arrivee + timedelta(days=1))
        debut = max(s.date_arrivee, du)
        fin_bornee = min(fin, au + timedelta(days=1))
        n = max(0, (fin_bornee - debut).days)
        nuitees += n
        revenu = round(revenu + n * float(s.tarif_nuit_usd or 0), 2)
    return Response({
        "du": du.isoformat(), "au": au.isoformat(),
        "nb_chambres": nb_chambres, "nuitees_vendues": nuitees,
        "taux_occupation_pct": round(nuitees / capacite * 100, 1)
        if capacite else 0.0,
        "revenu_hebergement_usd": revenu,
        "adr_usd": round(revenu / nuitees, 2) if nuitees else 0.0,
        "revpar_usd": round(revenu / capacite, 2) if capacite else 0.0})
