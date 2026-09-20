"""Aides intersociétés partagées — portage des fonctions utilitaires de
backend/app/routers/intersociete.py appelées par le module commercial :
tiers réciproque, facture miroir, commande client miroir (PO), demande de
course, synthèse de réception PO.
"""
from __future__ import annotations

from apps.comptabilite import services as comptabilite
from core import services as services
from apps.stocks.models import Article, MouvementStock
from apps.commercial.models import Commande, Devis, Facture, LigneCommande, LigneDevis, LigneFacture
from apps.transport.models import Course
from apps.groupe.models import LigneReceptionInter, ReceptionInter
from core.models import Societe, Tiers


def _statut_piece(societe_id, sens: str) -> str:
    """Revue comptable : par défaut TOUTE pièce venant des modules arrive
    « en attente » et le comptable la valide (Pièces en attente).
    Désactivable par société via compta.revue_achats / compta.revue_ventes = 0."""
    key = "compta.revue_achats" if sens == "achat" else "compta.revue_ventes"
    return "en_attente" if services.get_parametre(key, societe_id, "1") == "1" \
        else "valide"


def tiers_reciproque(societe_cible_id, societe_source: Societe, type_: str) -> Tiers:
    """Dans la société cible, retrouve (ou crée) le tiers représentant la source."""
    t = Tiers.objects.filter(societe_id=societe_cible_id,
                             societe_liee_id=societe_source.id, type=type_).first()
    if not t:
        t = Tiers.objects.create(societe_id=societe_cible_id, type=type_,
                                 code=societe_source.code, nom=societe_source.nom,
                                 intra_groupe=True, societe_liee_id=societe_source.id)
    return t


def creer_facture_miroir(fac_vente: Facture, user_id) -> Facture | None:
    """Facture d'achat miroir chez la société acheteuse (client lié au groupe)."""
    client = Tiers.objects.filter(id=fac_vente.tiers_id).first()
    if not client or not client.societe_liee_id or fac_vente.type != "vente":
        return None
    cible_id = client.societe_liee_id
    societe_cible = Societe.objects.filter(id=cible_id).first()
    societe_vendeuse = Societe.objects.filter(id=fac_vente.societe_id).first()
    if not societe_cible or str(cible_id) == str(fac_vente.societe_id):
        return None
    fournisseur = tiers_reciproque(cible_id, societe_vendeuse, "fournisseur")

    jour = fac_vente.date_facture
    numero = services.next_numero("facture_achat", jour.year, societe_cible.code, cible_id)
    statut_piece = _statut_piece(cible_id, "achat")
    fac_achat = Facture.objects.create(
        societe_id=cible_id, type="achat", numero=numero, tiers_id=fournisseur.id,
        date_facture=jour, echeance=fac_vente.echeance, reference=fac_vente.numero,
        statut="validee" if statut_piece == "valide" else "en_attente",
        intra_groupe=True, facture_liee_id=fac_vente.id, created_by=user_id,
        created_at=services.maintenant())
    fac_vente.intra_groupe = True
    fac_vente.facture_liee_id = fac_achat.id
    fac_vente.save(update_fields=["intra_groupe", "facture_liee_id"])
    # Vente issue d'un PO : le stock est entré à la réception physique de l'acheteur.
    stock_deja_recu = False
    if fac_vente.devis_id:
        dv_origine = Devis.objects.filter(id=fac_vente.devis_id).first()
        stock_deja_recu = bool(dv_origine and dv_origine.commande_origine_id)

    lignes_vente = list(LigneFacture.objects.filter(facture_id=fac_vente.id))
    codes_vendeur = {}
    for lv in lignes_vente:
        if lv.article_id and lv.article_id not in codes_vendeur:
            a = Article.objects.filter(id=lv.article_id).first()
            codes_vendeur[lv.article_id] = a.code if a else None

    total_ht = total_tva = 0.0
    stock_par_compte: dict[str, float] = {}
    lm_list = []
    for lv in lignes_vente:
        ht, tva = float(lv.montant_ht), float(lv.montant_tva)
        qte = float(lv.qte)
        art_cible = None
        code = codes_vendeur.get(lv.article_id)
        if code:
            art_cible = Article.objects.filter(societe_id=cible_id, code=code).first()
        lm = LigneFacture.objects.create(
            facture_id=fac_achat.id, article_id=art_cible.id if art_cible else None,
            designation=lv.designation, qte=qte,
            prix_unitaire=round(ht / qte, 4) if qte else 0,
            taux_tva=float(lv.taux_tva), montant_ht=ht, montant_tva=tva, cout_entree=ht)
        lm_list.append(lm)
        total_ht += ht
        total_tva += tva
        if art_cible and art_cible.gere_stock and not stock_deja_recu:
            from apps.stocks import services as stock_lib
            stock_lib.entree(art_cible, stock_lib.depot_central(cible_id),
                             qte, ht, "achat", numero, jour=jour)
            stock_par_compte[art_cible.compte_stock] = round(
                stock_par_compte.get(art_cible.compte_stock, 0.0) + ht, 2)
    fac_achat.total_ht = round(total_ht, 2)
    fac_achat.total_tva = round(total_tva, 2)
    fac_achat.total_ttc = round(total_ht + total_tva, 2)
    ecr = comptabilite.comptabiliser_facture(fac_achat, lm_list, user_id,
                                             statut=statut_piece)
    fac_achat.ecriture_id = ecr.id
    fac_achat.save()
    for compte_stock, val in stock_par_compte.items():
        if val > 0:
            comptabilite.comptabiliser_variation_stock(fac_achat, compte_stock, val,
                                                       entree=True, created_by=user_id)
    services.enregistrer_audit(user_id, "MIROIR", "facture", fac_achat.id, None,
                               {"numero": numero, "origine": fac_vente.numero,
                                "societe": societe_cible.code})
    return fac_achat


def creer_devis_miroir_commande(cmd: Commande, user_id) -> Devis | None:
    """PO intersociété : la commande d'achat apparaît chez le vendeur comme
    commande client à prendre en charge (devis « envoyé »)."""
    fournisseur = Tiers.objects.filter(id=cmd.tiers_id).first()
    if not fournisseur or not fournisseur.societe_liee_id:
        return None
    vendeur_id = fournisseur.societe_liee_id
    societe_vendeuse = Societe.objects.filter(id=vendeur_id).first()
    societe_acheteuse = Societe.objects.filter(id=cmd.societe_id).first()
    if not societe_vendeuse or str(vendeur_id) == str(cmd.societe_id):
        return None
    client = tiers_reciproque(vendeur_id, societe_acheteuse, "client")
    d = Devis.objects.create(
        societe_id=vendeur_id,
        numero=services.next_numero("devis", cmd.date_commande.year,
                                    societe_vendeuse.code, vendeur_id),
        tiers_id=client.id, date_devis=cmd.date_commande,
        validite=cmd.date_livraison_prevue, statut="envoye",
        conditions=f"Commande {cmd.numero} de {societe_acheteuse.nom}"
                   + (f" — livraison : {cmd.destination}" if cmd.destination else ""),
        commande_origine_id=cmd.id, created_by=user_id, created_at=services.maintenant())
    total_ht = total_tva = 0.0
    for i, lc in enumerate(LigneCommande.objects.filter(commande_id=cmd.id)):
        code = None
        if lc.article_id:
            a = Article.objects.filter(id=lc.article_id).first()
            code = a.code if a else None
        art_v = Article.objects.filter(societe_id=vendeur_id, code=code).first() \
            if code else None
        ht = round(float(lc.qte) * float(lc.prix_unitaire), 2)
        tva = round(ht * float(lc.taux_tva) / 100, 2)
        total_ht += ht
        total_tva += tva
        LigneDevis.objects.create(
            devis_id=d.id, ordre=i, article_id=art_v.id if art_v else None,
            designation=lc.designation, qte=float(lc.qte),
            prix_unitaire=float(lc.prix_unitaire), taux_tva=float(lc.taux_tva),
            montant_ht=ht, montant_tva=tva)
    d.total_ht = round(total_ht, 2)
    d.total_tva = round(total_tva, 2)
    d.total_ttc = round(total_ht + total_tva, 2)
    d.save(update_fields=["total_ht", "total_tva", "total_ttc"])
    cmd.devis_lie_id = d.id
    cmd.intra_groupe = True
    cmd.save(update_fields=["devis_lie_id", "intra_groupe"])
    services.enregistrer_audit(user_id, "MIROIR", "devis", d.id, None,
                               {"numero": d.numero, "commande": cmd.numero})
    return d


def creer_demande_course(cmd: Commande, user_id) -> Course | None:
    """PO avec transporteur du groupe : demande de course chez lui."""
    if not cmd.transporteur_societe_id:
        return None
    transporteur = Societe.objects.filter(id=cmd.transporteur_societe_id).first()
    societe_acheteuse = Societe.objects.filter(id=cmd.societe_id).first()
    fournisseur = Tiers.objects.filter(id=cmd.tiers_id).first()
    vendeur = Societe.objects.filter(id=fournisseur.societe_liee_id).first() \
        if fournisseur and fournisseur.societe_liee_id else None
    if not transporteur or str(transporteur.id) == str(cmd.societe_id):
        return None
    client = tiers_reciproque(transporteur.id, societe_acheteuse, "client")
    lignes_cmd = list(LigneCommande.objects.filter(commande_id=cmd.id))
    marchandise = ", ".join(l.designation for l in lignes_cmd)[:120] or "Marchandises"
    jour = cmd.date_livraison_prevue or cmd.date_commande
    qte_totale = round(sum(float(l.qte) for l in lignes_cmd), 3)
    unite = "unités"
    for lc in lignes_cmd:
        if lc.article_id:
            a2 = Article.objects.filter(id=lc.article_id).first()
            if a2 and a2.unite:
                unite = a2.unite
                break
    c = Course.objects.create(
        societe_id=transporteur.id,
        numero=services.next_numero("course", jour.year, transporteur.code,
                                    transporteur.id),
        date_course=jour, client_tiers_id=client.id, camion_id=None,
        origine=(vendeur.ville if vendeur and vendeur.ville
                 else (vendeur.nom if vendeur else "À préciser")),
        destination=cmd.destination or "À préciser",
        marchandise=marchandise,
        tonnage_prevu=qte_totale, unite=unite, tarif_mode="voyage", prix_unitaire=0,
        statut="demande", commande_origine_id=cmd.id, created_by=user_id,
        created_at=services.maintenant())
    services.enregistrer_audit(user_id, "DEMANDE", "course", c.id, None,
                               {"numero": c.numero, "commande": cmd.numero})
    return c


# ── Réception physique de l'acheteur (synthèse partagée) ─────────────
def _mapping_lignes_po(cmd: Commande) -> dict:
    """ligne_commande.id → ligne_devis correspondante (créées dans le même ordre)."""
    dv = Devis.objects.filter(id=cmd.devis_lie_id).first() if cmd.devis_lie_id else None
    if not dv:
        return {}
    lignes_dv = sorted(LigneDevis.objects.filter(devis_id=dv.id),
                       key=lambda x: int(x.ordre or 0))
    lignes_cmd = list(LigneCommande.objects.filter(commande_id=cmd.id))
    return {str(lc.id): lignes_dv[i] for i, lc in enumerate(lignes_cmd)
            if i < len(lignes_dv)}


def _recu_cumule_po(cmd: Commande) -> dict:
    """ligne_commande.id → {bon, mauvais, manquant} cumulés (non annulées)."""
    out: dict = {}
    for r in ReceptionInter.objects.filter(commande_id=cmd.id).exclude(statut="annulee"):
        for l in LigneReceptionInter.objects.filter(reception_id=r.id):
            e = out.setdefault(str(l.ligne_commande_id),
                               {"bon": 0.0, "mauvais": 0.0, "manquant": 0.0})
            e["bon"] = round(e["bon"] + float(l.qte_bon), 3)
            e["mauvais"] = round(e["mauvais"] + float(l.qte_mauvais), 3)
            e["manquant"] = round(e["manquant"] + float(l.qte_manquante), 3)
    return out


def course_active(cmd_id):
    """La course « vivante » d'un PO : la plus récente non annulée (une course
    annulée en route est remplacée par une nouvelle demande) ; à défaut, la
    dernière quelle qu'elle soit (pour l'historique)."""
    c = (Course.objects.filter(commande_origine_id=cmd_id)
         .exclude(statut="annulee").order_by("-created_at").first())
    if c:
        return c
    return (Course.objects.filter(commande_origine_id=cmd_id)
            .order_by("-created_at").first())


def etapes_po(cmd: Commande) -> dict:
    """Fil d'avancement d'une commande intersociété — la même chronologie vue
    par les trois sociétés (acheteur, vendeur, transporteur), avec pour chaque
    étape : faite ou non, et QUI doit agir ensuite (demande de Laurent :
    « montrer pour chaque étape faite l'étape qui doit suivre »)."""
    dv = Devis.objects.filter(id=cmd.devis_lie_id).first() if cmd.devis_lie_id else None
    course = course_active(cmd.id)
    r = reception_po_resume(cmd)
    lignes_dv = list(LigneDevis.objects.filter(devis_id=dv.id)) if dv else []

    acheteur = Societe.objects.filter(id=cmd.societe_id).first()
    fournisseur = Tiers.objects.filter(id=cmd.tiers_id).first()
    vendeur = Societe.objects.filter(id=fournisseur.societe_liee_id).first() \
        if fournisseur and fournisseur.societe_liee_id else None
    transporteur = Societe.objects.filter(id=cmd.transporteur_societe_id).first() \
        if cmd.transporteur_societe_id else None
    n_ach = acheteur.nom if acheteur else "l'acheteur"
    n_ven = vendeur.nom if vendeur else "le vendeur"
    n_tra = transporteur.nom if transporteur else None

    annulee = cmd.statut == "annulee" or bool(dv and dv.statut == "annule")
    st_course = course.statut if course else None
    apres = ("validee", "en_cours", "arrivee", "receptionnee", "livree", "facturee")

    qte_total = sum(float(l.qte) for l in lignes_dv)
    charge_complet = qte_total > 0 and all(
        float(l.qte_livree) >= float(l.qte) - 1e-6 for l in lignes_dv)
    facture_complet = r["totaux"]["livre"] > 0 and all(
        float(l.qte_facturee) >= float(l.qte_livree) - 1e-6 for l in lignes_dv)

    etapes = [
        {"cle": "commande", "libelle": "Commande passée", "acteur": n_ach,
         "fait": True},
        {"cle": "prise_en_charge_vendeur",
         "libelle": "Prise en charge de la commande", "acteur": n_ven,
         "fait": bool(dv and dv.statut == "confirme")},
    ]
    if n_tra:
        etapes += [
            {"cle": "prise_en_charge_course",
             "libelle": "Prise en charge de la course (camion, chauffeur, tarif)",
             "acteur": n_tra,
             "fait": bool(course and st_course != "demande")},
            {"cle": "validation_fiche", "libelle": "Validation de la fiche de course",
             "acteur": n_tra, "fait": bool(course and st_course in apres)},
        ]
    etapes.append(
        {"cle": "chargement", "libelle": "Chargement de la marchandise",
         "acteur": n_ven, "fait": charge_complet})
    if n_tra:
        etapes += [
            {"cle": "depart", "libelle": "Départ du camion", "acteur": n_tra,
             "fait": bool(course and course.heure_depart)},
            {"cle": "arrivee", "libelle": "Arrivée à destination (déchargement)",
             "acteur": n_tra,
             "fait": bool(course and st_course in
                          ("arrivee", "receptionnee", "livree", "facturee"))},
        ]
    etapes.append(
        {"cle": "reception", "libelle": "Réception physique (bon / mauvais / manquant)",
         "acteur": n_ach, "fait": bool(r["complete"])})
    if n_tra:
        etapes += [
            {"cle": "confirmation_reception",
             "libelle": "Confirmation de la réception", "acteur": n_tra,
             "fait": bool(r["complete"] and r["toutes_confirmees"])},
            {"cle": "retour",
             "libelle": "Retour du camion (clôture de la course)", "acteur": n_tra,
             "fait": bool(course and st_course in ("livree", "facturee"))},
        ]
    etapes.append(
        {"cle": "facture_vendeur", "libelle": "Facturation de la marchandise",
         "acteur": n_ven, "fait": facture_complet})
    if n_tra:
        etapes.append(
            {"cle": "facture_transport", "libelle": "Facturation du transport",
             "acteur": n_tra, "fait": bool(course and st_course == "facturee")})

    prochaine = next(({"cle": e["cle"], "libelle": e["libelle"],
                       "acteur": e["acteur"]}
                      for e in etapes if not e["fait"]), None)
    return {"etapes": etapes, "prochaine": None if annulee else prochaine,
            "annulee": annulee, "terminee": prochaine is None and not annulee}


def reception_po_resume(cmd: Commande) -> dict:
    """Synthèse réception d'un PO — partagée acheteur/vendeur/transporteur."""
    mapping = _mapping_lignes_po(cmd)
    deja = _recu_cumule_po(cmd)
    lignes, tot = [], {"livre": 0.0, "bon": 0.0, "mauvais": 0.0, "manquant": 0.0}
    for lc in LigneCommande.objects.filter(commande_id=cmd.id):
        ld = mapping.get(str(lc.id))
        livre = float(ld.qte_livree) if ld else 0.0
        d = deja.get(str(lc.id), {"bon": 0.0, "mauvais": 0.0, "manquant": 0.0})
        a_recevoir = round(livre - d["bon"] - d["mauvais"] - d["manquant"], 3)
        lignes.append({"ligne_commande_id": str(lc.id), "designation": lc.designation,
                       "qte_commandee": float(lc.qte), "livre": livre,
                       "bon": d["bon"], "mauvais": d["mauvais"],
                       "manquant": d["manquant"],
                       "a_recevoir": max(a_recevoir, 0.0),
                       "prix_unitaire": float(lc.prix_unitaire)})
        tot["livre"] += livre
        tot["bon"] += d["bon"]
        tot["mauvais"] += d["mauvais"]
        tot["manquant"] += d["manquant"]
    tot = {k: round(v, 3) for k, v in tot.items()}
    complete = tot["livre"] > 0 and \
        tot["livre"] <= tot["bon"] + tot["mauvais"] + tot["manquant"] + 1e-6
    recs = [r for r in ReceptionInter.objects.filter(commande_id=cmd.id)
            .order_by("created_at") if r.statut != "annulee"]
    return {"lignes": lignes, "totaux": tot, "complete": complete,
            "a_receptionner": round(tot["livre"] - tot["bon"] - tot["mauvais"]
                                    - tot["manquant"], 3) > 0,
            "valeur_manquants_usd": round(sum(l["manquant"] * l["prix_unitaire"]
                                              for l in lignes), 2),
            "receptions": [{"id": str(r.id), "numero": r.numero,
                            "date": r.date_reception.isoformat(),
                            "statut": r.statut, "note": r.note} for r in recs],
            "toutes_confirmees": bool(recs) and all(r.statut == "confirmee" for r in recs)}
