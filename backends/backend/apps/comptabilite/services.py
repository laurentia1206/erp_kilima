"""Moteur de comptabilisation OHADA — portage exact de backend/app/comptabilite.py.

Cœur : `post_ecriture` crée une écriture ÉQUILIBRÉE (contrôle D=C avant toute
insertion). Mêmes numéros (ECR par journal/année via sequence_compteur, préfixe
ECR_<code>), mêmes conventions de colonnes que le moteur SQLAlchemy.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from rest_framework.exceptions import ValidationError

from core import services as services
from apps.comptabilite.models import Compte, Ecriture, Exercice, Journal, LigneEcriture
from core.models import SequenceCompteur

# Comptes OHADA par défaut (paramétrables via la table `parametre`, clé compte.<cle>)
DEFAUT = {
    "compte_avance": "409", "compte_caisse": "571", "compte_charge": "605",
    "compte_attente": "471", "compte_client": "411", "compte_fournisseur": "401",
    "tva_deductible": "4452", "tva_collectee": "4431", "variation_stock": "603",
    "fournisseur_fnp": "408", "ecart_manquant": "658", "ecart_excedent": "758",
    "compte_banque": "521", "compte_mobile_money": "522",
    "compte_vente_transport": "706", "compte_sous_traitance": "612",
    "compte_vente_location": "7073", "compte_vente_hebergement": "7062",
    "manquants_charge": "658", "manquants_produit": "758",
}


def _compte(cle: str, societe_id) -> str:
    return services.get_parametre(f"compte.{cle}", societe_id, DEFAUT[cle])


_TYPES_PERSONNEL = {"agent", "personnel", "employe", "employé", "salarie", "salarié",
                    "staff", "cadre"}
_TYPES_FOURNISSEUR = {"fournisseur", "supplier", "prestataire"}


def _compte_avance_tiers(tiers, societe_id) -> str:
    """Compte d'avance au débit selon le bénéficiaire : auxiliaire du tiers,
    sinon 421 (personnel), sinon 409 (fournisseur), sinon défaut."""
    if tiers and tiers.compte_auxiliaire:
        return tiers.compte_auxiliaire
    t = (tiers.type or "").lower() if tiers else ""
    if t in _TYPES_PERSONNEL:
        return services.get_parametre("compte.compte_avance_personnel", societe_id, "421")
    if t in _TYPES_FOURNISSEUR:
        return services.get_parametre("compte.compte_avance_fournisseur", societe_id, "409")
    return _compte("compte_avance", societe_id)


def _lignes_normalisees(lignes: list[dict]) -> list[dict]:
    """Valide les montants qui seront réellement stockés, ligne par ligne."""
    if len(lignes) < 2:
        raise ValidationError({"detail": "Une écriture doit contenir au moins deux lignes."})
    resultat = []
    for ligne in lignes:
        if ligne.get("sens") not in {"D", "C"} or not str(ligne.get("compte") or "").strip():
            raise ValidationError({"detail": "Chaque ligne exige un compte et un sens D ou C."})
        try:
            montant = Decimal(str(ligne.get("montant_usd")))
            if not montant.is_finite() or montant < 0:
                raise InvalidOperation
            montant = montant.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if montant >= Decimal("10000000000000000"):
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError({"detail": "Montant comptable invalide : nombre positif ou nul attendu."})
        resultat.append({**ligne, "montant_usd": montant})
    d = sum((l["montant_usd"] for l in resultat if l["sens"] == "D"), Decimal(0))
    c = sum((l["montant_usd"] for l in resultat if l["sens"] == "C"), Decimal(0))
    if d != c:
        raise ValidationError({"detail": f"Écriture déséquilibrée : D {d} ≠ C {c}."})
    return resultat


def assert_equilibree(lignes: list[dict]) -> None:
    _lignes_normalisees(lignes)


def get_or_create_exercice(societe_id, jour: date) -> Exercice:
    ex = Exercice.objects.filter(societe_id=societe_id, annee=jour.year).first()
    if ex is None:
        ex = Exercice.objects.create(societe_id=societe_id, annee=jour.year,
                                     date_debut=date(jour.year, 1, 1),
                                     date_fin=date(jour.year, 12, 31), statut="ouvert")
    return ex


def get_or_create_journal(societe_id, code: str, libelle: str, type_: str) -> Journal:
    j = Journal.objects.filter(societe_id=societe_id, code=code).first()
    if j is None:
        j = Journal.objects.create(societe_id=societe_id, code=code,
                                   libelle=libelle, type=type_)
    return j


def _next_compteur(societe_id, type_piece: str, annee: int) -> int:
    with transaction.atomic():
        c = (SequenceCompteur.objects.select_for_update()
             .filter(societe_id=societe_id, type_piece=type_piece, annee=annee).first())
        if c is None:
            c = SequenceCompteur.objects.create(societe_id=societe_id, type_piece=type_piece,
                                                annee=annee, dernier_numero=0)
        c.dernier_numero += 1
        c.save(update_fields=["dernier_numero"])
        return c.dernier_numero


@transaction.atomic
def post_ecriture(societe_id, journal_code: str, journal_libelle: str, journal_type: str,
                  jour: date, libelle: str, lignes: list[dict], type_operation: str,
                  source_type: str, source_id, numero_piece: str | None, created_by,
                  statut: str = "valide") -> Ecriture:
    """Crée une écriture équilibrée — signature alignée sur le moteur FastAPI
    (le paramètre societe y est l'objet Societe ; ici l'id suffit)."""
    lignes = _lignes_normalisees(lignes)
    exercice = get_or_create_exercice(societe_id, jour)
    if exercice.statut != "ouvert" or not exercice.date_debut <= jour <= exercice.date_fin:
        raise ValidationError({"detail": "Cet exercice est fermé ou la date est hors exercice."})
    journal = get_or_create_journal(societe_id, journal_code, journal_libelle, journal_type)
    if not journal.actif:
        raise ValidationError({"detail": "Ce journal comptable est désactivé."})
    seq = _next_compteur(societe_id, f"ECR_{journal_code}", jour.year)
    numero = f"{journal_code}-{jour.year}-{seq:05d}"

    ecr = Ecriture.objects.create(
        societe_id=societe_id, exercice_id=exercice.id, journal_id=journal.id,
        numero=numero, date_ecriture=jour, numero_piece=numero_piece, libelle=libelle,
        type_operation=type_operation, source_type=source_type, source_id=source_id,
        statut=statut, created_by=created_by, created_at=services.maintenant())
    for i, l in enumerate(lignes):
        LigneEcriture.objects.create(
            ecriture_id=ecr.id, societe_id=societe_id, ordre=i, sens=l["sens"],
            compte_numero=l["compte"], tiers_id=l.get("tiers_id"),
            montant_usd=round(l["montant_usd"], 2),
            devise_origine=l.get("devise_origine", "USD"),
            montant_origine=l.get("montant_origine"), taux_jour=l.get("taux_jour"),
            libelle_ligne=l.get("libelle"))
    services.enregistrer_audit(created_by, "INSERT", "ecriture", ecr.id, None,
                               {"numero": numero, "type": type_operation})
    return ecr


def comptabiliser_operation_caisse(societe_id, sens: str, montant_usd, libelle: str,
                                   source_id, numero_piece: str, created_by,
                                   nature: str = "", devise: str = "USD",
                                   montant_origine=None, tiers_id=None) -> Ecriture:
    """Opération de caisse manuelle : la contrepartie va en 471 (à reclasser).

    entrée : D 571 (caisse)   / C 471 (à reclasser)
    sortie : D 471 (à reclasser) / C 571 (caisse)
    """
    caisse_acct = _compte("compte_caisse", societe_id)
    attente_acct = _compte("compte_attente", societe_id)
    lib = libelle or nature or ("Encaissement" if sens == "entree" else "Sortie de caisse")
    ligne_caisse = {"sens": "D" if sens == "entree" else "C", "compte": caisse_acct,
                    "montant_usd": montant_usd, "devise_origine": devise,
                    "montant_origine": montant_origine, "tiers_id": tiers_id, "libelle": lib}
    ligne_attente = {"sens": "C" if sens == "entree" else "D", "compte": attente_acct,
                     "montant_usd": montant_usd, "libelle": f"À reclasser — {lib}"}
    lignes = [ligne_caisse, ligne_attente] if sens == "entree" else [ligne_attente, ligne_caisse]
    return post_ecriture(societe_id, "CA", "Caisse", "caisse", date.today(),
                         lib, lignes, "operation_caisse", "mouvement_caisse", source_id,
                         numero_piece, created_by, statut="en_attente")


def comptabiliser_transfert(transfert, compte_dest: str, compte_source: str,
                            libelle: str, created_by,
                            montant_recu_usd: float | None = None) -> Ecriture:
    """Virement interne : D destination / C source (en attente) ; l'écart émis/reçu
    va en 658 (manquant) ou 758 (excédent)."""
    emis = round(float(transfert.montant_usd), 2)
    recu = round(float(montant_recu_usd), 2) if montant_recu_usd is not None else emis
    lignes = [
        {"sens": "D", "compte": compte_dest, "montant_usd": recu, "libelle": libelle,
         "devise_origine": transfert.devise, "montant_origine": transfert.montant},
        {"sens": "C", "compte": compte_source, "montant_usd": emis, "libelle": libelle},
    ]
    ecart = round(emis - recu, 2)
    if ecart > 0:      # manquant : la destination reçoit moins que déclaré → charge
        lignes.append({"sens": "D", "compte": _compte("ecart_manquant", transfert.societe_id),
                       "montant_usd": ecart,
                       "libelle": f"Manquant de caisse — {transfert.numero}"})
    elif ecart < 0:    # excédent : la destination reçoit plus que déclaré → produit
        lignes.append({"sens": "C", "compte": _compte("ecart_excedent", transfert.societe_id),
                       "montant_usd": -ecart,
                       "libelle": f"Excédent de caisse — {transfert.numero}"})
    return post_ecriture(transfert.societe_id, "VI", "Virements internes", "od", date.today(),
                         f"Transfert {transfert.numero} — {libelle}", lignes,
                         "transfert", "transfert", transfert.id, transfert.numero, created_by,
                         statut="en_attente")


# ── Comptabilisations du cycle commercial (portage exact) ────────────
def comptabiliser_facture(facture, lignes_facture, created_by,
                          frais_objs=None, statut: str = "valide") -> Ecriture:
    """Achat : D 60x + D TVA / C 401 (+ frais avec leur propre contrepartie).
    Vente : D 411 / C produits + C TVA."""
    from apps.stocks.models import Article
    from core.models import Tiers
    societe_id = facture.societe_id
    tiers = Tiers.objects.filter(id=facture.tiers_id).first()
    lignes: list[dict] = []

    def _art(aid):
        return Article.objects.filter(id=aid).first() if aid else None

    if facture.type == "achat":
        by_achat: dict[str, float] = {}
        goods_ht = goods_tva = 0.0
        for l in lignes_facture:
            art = _art(l.article_id)
            compte = (art.compte_achat if art else None) or _compte("compte_charge", societe_id)
            by_achat[compte] = by_achat.get(compte, 0.0) + float(l.montant_ht)
            goods_ht += float(l.montant_ht)
            goods_tva += float(l.montant_tva)
        for compte, ht in by_achat.items():
            lignes.append({"sens": "D", "compte": compte, "montant_usd": round(ht, 2),
                           "libelle": f"Achat {facture.numero}"})
        if round(goods_tva, 2):
            lignes.append({"sens": "D", "compte": _compte("tva_deductible", societe_id),
                           "montant_usd": round(goods_tva, 2),
                           "libelle": f"TVA déductible {facture.numero}"})
        goods_ttc = round(goods_ht + goods_tva, 2)
        if goods_ttc:
            lignes.append({"sens": "C", "compte": _compte("compte_fournisseur", societe_id),
                           "montant_usd": goods_ttc, "tiers_id": tiers.id,
                           "libelle": f"Fournisseur {tiers.nom} — {facture.numero}"})

        for f in (frais_objs or []):
            fht = round(float(f.montant_ht), 2)
            ftva = round(float(f.montant_tva or 0), 2)
            lignes.append({"sens": "D", "compte": f.compte, "montant_usd": fht,
                           "libelle": f"{f.libelle} — {facture.numero}"})
            if ftva:
                lignes.append({"sens": "D", "compte": _compte("tva_deductible", societe_id),
                               "montant_usd": ftva,
                               "libelle": f"TVA déductible frais {facture.numero}"})
            fttc = round(fht + ftva, 2)
            if f.mode == "credit":
                ft = Tiers.objects.filter(id=f.tiers_id).first() if f.tiers_id else tiers
                lignes.append({"sens": "C", "compte": _compte("compte_fournisseur", societe_id),
                               "montant_usd": fttc, "tiers_id": ft.id if ft else None,
                               "libelle": f"Frais {f.libelle} — {ft.nom if ft else ''}"})
            else:   # banque | caisse : contrepartie trésorerie
                cpt = f.compte_reglement or _compte("compte_caisse", societe_id)
                lignes.append({"sens": "C", "compte": cpt, "montant_usd": fttc,
                               "libelle": f"Règlement frais {f.libelle} — {facture.numero}"})
        jcode, jlib, jtyp = "AC", "Achats", "achat"
        lib = f"Facture achat {facture.numero} — {tiers.nom}"
    else:
        ttc = round(float(facture.total_ttc), 2)
        tva = round(float(facture.total_tva), 2)
        lignes.append({"sens": "D", "compte": _compte("compte_client", societe_id),
                       "montant_usd": ttc, "tiers_id": tiers.id,
                       "libelle": f"Client {tiers.nom} — {facture.numero}"})
        by_compte: dict[str, float] = {}
        for l in lignes_facture:
            art = _art(l.article_id)
            compte = (art.compte_vente if art else None) or "701"
            by_compte[compte] = by_compte.get(compte, 0.0) + float(l.montant_ht)
        for compte, ht in by_compte.items():
            lignes.append({"sens": "C", "compte": compte, "montant_usd": round(ht, 2),
                           "libelle": f"Vente {facture.numero}"})
        if tva:
            lignes.append({"sens": "C", "compte": _compte("tva_collectee", societe_id),
                           "montant_usd": tva, "libelle": f"TVA collectée {facture.numero}"})
        jcode, jlib, jtyp = "VE", "Ventes", "vente"
        lib = f"Facture vente {facture.numero} — {tiers.nom}"

    return post_ecriture(societe_id, jcode, jlib, jtyp, facture.date_facture, lib, lignes,
                         f"facture_{facture.type}", "facture", facture.id, facture.numero,
                         created_by, statut=statut)


def comptabiliser_reception(reception, goods_par_compte: dict, frais_par_compte: dict,
                            frais_objs, created_by, statut="valide") -> Ecriture:
    """Réception : marchandises D 31 / C 408 ; frais avec leur contrepartie
    propre puis incorporés au stock (D 31 / C 603)."""
    from apps.commercial.models import Commande
    from core.models import Tiers
    societe_id = reception.societe_id
    cmd = Commande.objects.filter(id=reception.commande_id).first()
    fnp = _compte("fournisseur_fnp", societe_id)
    fournisseur = _compte("compte_fournisseur", societe_id)
    var = _compte("variation_stock", societe_id)
    tva_ded = _compte("tva_deductible", societe_id)
    lignes: list[dict] = []

    goods_total = round(sum(goods_par_compte.values()), 2)
    for cpt, v in goods_par_compte.items():
        if round(v, 2):
            lignes.append({"sens": "D", "compte": cpt, "montant_usd": round(v, 2),
                           "libelle": f"Réception {reception.numero}"})
    if goods_total:
        lignes.append({"sens": "C", "compte": fnp, "montant_usd": goods_total,
                       "libelle": f"Réception non facturée {reception.numero}"})

    for f in (frais_objs or []):
        fht = round(float(f.montant_ht), 2)
        ftva = round(float(f.montant_tva or 0), 2)
        lignes.append({"sens": "D", "compte": f.compte, "montant_usd": fht,
                       "libelle": f"{f.libelle} — {reception.numero}"})
        if ftva:
            lignes.append({"sens": "D", "compte": tva_ded, "montant_usd": ftva,
                           "libelle": f"TVA déductible frais {reception.numero}"})
        fttc = round(fht + ftva, 2)
        if f.mode == "credit":
            tid = f.tiers_id or (cmd.tiers_id if cmd else None)
            lignes.append({"sens": "C", "compte": fournisseur, "montant_usd": fttc,
                           "tiers_id": tid, "libelle": f"Frais {f.libelle}"})
        else:   # banque | caisse
            cpt = f.compte_reglement or _compte("compte_caisse", societe_id)
            lignes.append({"sens": "C", "compte": cpt, "montant_usd": fttc,
                           "libelle": f"Règlement frais {f.libelle}"})

    frais_total = round(sum(frais_par_compte.values()), 2)
    for cpt, v in frais_par_compte.items():
        if round(v, 2):
            lignes.append({"sens": "D", "compte": cpt, "montant_usd": round(v, 2),
                           "libelle": f"Frais incorporés {reception.numero}"})
    if frais_total:
        lignes.append({"sens": "C", "compte": var, "montant_usd": frais_total,
                       "libelle": f"Incorporation frais {reception.numero}"})

    return post_ecriture(societe_id, "AC", "Achats", "achat", reception.date_reception,
                         f"Réception {reception.numero}", lignes,
                         "reception", "reception", reception.id, reception.numero,
                         created_by, statut=statut)


def comptabiliser_facture_reception(facture, reception, created_by,
                                    statut="valide") -> Ecriture:
    """Facture fournisseur d'une réception : D 601 + D TVA + D 408 / C 401 + C 603."""
    from apps.stocks.models import Article
    from apps.commercial.models import LigneReception
    from core.models import Tiers
    societe_id = facture.societe_id
    tiers = Tiers.objects.filter(id=facture.tiers_id).first()
    fnp = _compte("fournisseur_fnp", societe_id)
    var = _compte("variation_stock", societe_id)

    rec_lignes = list(LigneReception.objects.filter(reception_id=reception.id))
    goods_ht = round(sum(float(l.montant_ht) for l in rec_lignes), 2)
    goods_tva = round(sum(round(float(l.montant_ht) * float(l.taux_tva) / 100, 2)
                          for l in rec_lignes), 2)
    goods_ttc = round(goods_ht + goods_tva, 2)

    lignes: list[dict] = []
    by_achat: dict[str, float] = {}
    for l in rec_lignes:
        art = Article.objects.filter(id=l.article_id).first() if l.article_id else None
        compte = (art.compte_achat if art else None) or "601"
        by_achat[compte] = by_achat.get(compte, 0.0) + float(l.montant_ht)
    for compte, ht in by_achat.items():
        lignes.append({"sens": "D", "compte": compte, "montant_usd": round(ht, 2),
                       "libelle": f"Achat {facture.numero}"})
    if goods_tva:
        lignes.append({"sens": "D", "compte": _compte("tva_deductible", societe_id),
                       "montant_usd": goods_tva, "libelle": f"TVA déductible {facture.numero}"})
    lignes.append({"sens": "D", "compte": fnp, "montant_usd": goods_ht,
                   "libelle": f"Solde réception {reception.numero}"})
    lignes.append({"sens": "C", "compte": _compte("compte_fournisseur", societe_id),
                   "montant_usd": goods_ttc, "tiers_id": tiers.id,
                   "libelle": f"Fournisseur {tiers.nom} — {facture.numero}"})
    lignes.append({"sens": "C", "compte": var, "montant_usd": goods_ht,
                   "libelle": f"Variation stock {reception.numero}"})
    return post_ecriture(societe_id, "AC", "Achats", "achat", facture.date_facture,
                         f"Facture réception {facture.numero} — {tiers.nom}", lignes,
                         "facture_achat", "facture", facture.id, facture.numero,
                         created_by, statut=statut)


def comptabiliser_vente_pos(facture, lignes_facture, encaissements: list[dict],
                            created_by, statut: str = "valide") -> Ecriture:
    """Vente POS fractionnée : D trésorerie/411 / C 70x + C TVA."""
    from apps.stocks.models import Article
    societe_id = facture.societe_id
    tva = round(float(facture.total_tva), 2)
    lignes = [{"sens": "D", "compte": e["compte"], "montant_usd": round(e["montant_usd"], 2),
               "libelle": e.get("libelle") or f"Encaissement POS {facture.numero}",
               "tiers_id": e.get("tiers_id"), "devise_origine": e.get("devise", "USD"),
               "montant_origine": e.get("montant"), "taux_jour": e.get("taux")}
              for e in encaissements if round(e["montant_usd"], 2) != 0]
    by_compte: dict[str, float] = {}
    for l in lignes_facture:
        art = Article.objects.filter(id=l.article_id).first() if l.article_id else None
        compte = (art.compte_vente if art else None) or "701"
        by_compte[compte] = by_compte.get(compte, 0.0) + float(l.montant_ht)
    for compte, ht in by_compte.items():
        lignes.append({"sens": "C", "compte": compte, "montant_usd": round(ht, 2),
                       "libelle": f"Vente POS {facture.numero}"})
    if tva:
        lignes.append({"sens": "C", "compte": _compte("tva_collectee", societe_id),
                       "montant_usd": tva, "libelle": f"TVA collectée {facture.numero}"})
    return post_ecriture(societe_id, "VE", "Ventes", "vente", facture.date_facture,
                         f"Vente POS {facture.numero}", lignes, "vente_pos", "facture",
                         facture.id, facture.numero, created_by, statut=statut)


def comptabiliser_retour_pos(avoir, lignes_avoir, remboursements: list[dict],
                             created_by, statut: str = "valide") -> Ecriture:
    """Retour client (avoir POS) : D 70x + D TVA / C trésorerie ou C 411."""
    from apps.stocks.models import Article
    societe_id = avoir.societe_id
    tva = round(float(avoir.total_tva), 2)
    lignes = []
    by_compte: dict[str, float] = {}
    for l in lignes_avoir:
        art = Article.objects.filter(id=l.article_id).first() if l.article_id else None
        compte = (art.compte_vente if art else None) or "701"
        by_compte[compte] = by_compte.get(compte, 0.0) + float(l.montant_ht)
    for compte, ht in by_compte.items():
        lignes.append({"sens": "D", "compte": compte, "montant_usd": round(ht, 2),
                       "libelle": f"Retour POS {avoir.numero}"})
    if tva:
        lignes.append({"sens": "D", "compte": _compte("tva_collectee", societe_id),
                       "montant_usd": tva, "libelle": f"TVA sur retour {avoir.numero}"})
    for r in remboursements:
        if round(r["montant_usd"], 2) != 0:
            lignes.append({"sens": "C", "compte": r["compte"],
                           "montant_usd": round(r["montant_usd"], 2),
                           "libelle": r.get("libelle") or f"Remboursement {avoir.numero}",
                           "tiers_id": r.get("tiers_id")})
    return post_ecriture(societe_id, "VE", "Ventes", "vente", avoir.date_facture,
                         f"Retour POS {avoir.numero}", lignes, "retour_pos", "facture",
                         avoir.id, avoir.numero, created_by, statut=statut)


def comptabiliser_stock_sortie(societe_id, stock_par_compte: dict, ref: str, jour,
                               source_type: str, source_id, created_by,
                               statut: str = "valide") -> Ecriture:
    """Sortie de stock générique (livraison client) : D 603 (coût des ventes) / C 3x."""
    var = _compte("variation_stock", societe_id)
    total = round(sum(stock_par_compte.values()), 2)
    lignes = [{"sens": "D", "compte": var, "montant_usd": total,
               "libelle": f"Coût des ventes {ref}"}]
    lignes += [{"sens": "C", "compte": cpt, "montant_usd": round(v, 2),
                "libelle": f"Sortie stock {ref}"}
               for cpt, v in stock_par_compte.items()]
    return post_ecriture(societe_id, "STK", "Stocks", "od", jour, f"Sortie stock — {ref}",
                         lignes, "variation_stock", source_type, source_id, ref,
                         created_by, statut=statut)


def comptabiliser_variation_stock(facture, compte_stock: str, valeur: float,
                                  entree: bool, created_by,
                                  statut: str = "valide") -> Ecriture:
    """Inventaire permanent : entrée D 3x / C 603 ; sortie D 603 / C 3x."""
    var = _compte("variation_stock", facture.societe_id)
    m = round(valeur, 2)
    if entree:
        lignes = [{"sens": "D", "compte": compte_stock, "montant_usd": m,
                   "libelle": f"Entrée stock {facture.numero}"},
                  {"sens": "C", "compte": var, "montant_usd": m,
                   "libelle": f"Variation stock {facture.numero}"}]
    else:
        lignes = [{"sens": "D", "compte": var, "montant_usd": m,
                   "libelle": f"Coût des ventes {facture.numero}"},
                  {"sens": "C", "compte": compte_stock, "montant_usd": m,
                   "libelle": f"Sortie stock {facture.numero}"}]
    return post_ecriture(facture.societe_id, "STK", "Stocks", "od", facture.date_facture,
                         f"Variation de stock — {facture.numero}", lignes,
                         "variation_stock", "facture", facture.id, facture.numero,
                         created_by, statut=statut)


# ── Comptabilisations du décaissement (portage exact) ────────────────
def comptabiliser_versement_avance(avance, ordre, tiers, compte_credit: str, created_by,
                                   journal_code: str = "CA", journal_libelle: str = "Caisse",
                                   journal_type: str = "caisse") -> Ecriture:
    """D 421|409 (avance au bénéficiaire) / C 571|521 — sortie de fonds, 'valide'."""
    from apps.approbations.models import Requisition
    compte_av = _compte_avance_tiers(tiers, avance.societe_id)
    montant = avance.montant_avance_usd
    req = (Requisition.objects.filter(id=ordre.requisition_id).first()
           if ordre.requisition_id else None)
    objet = f" — {req.objet}" if req and req.objet else ""
    lignes = [
        {"sens": "D", "compte": compte_av, "montant_usd": montant, "tiers_id": tiers.id,
         "devise_origine": avance.devise, "montant_origine": avance.montant_avance,
         "libelle": f"Avance à {tiers.nom} ({ordre.numero}){objet}"},
        {"sens": "C", "compte": compte_credit, "montant_usd": montant,
         "libelle": f"Sortie de fonds — avance {avance.numero} à {tiers.nom}"},
    ]
    return post_ecriture(avance.societe_id, journal_code, journal_libelle, journal_type,
                         date.today(),
                         f"Versement d'avance à {tiers.nom} — {ordre.numero}{objet}", lignes,
                         "versement_avance", "avance", avance.id, ordre.numero, created_by,
                         statut="valide")


def comptabiliser_paiement_direct(ordre, req_lignes, compte_credit: str, created_by,
                                  journal_code: str = "CA", journal_libelle: str = "Caisse",
                                  journal_type: str = "caisse") -> Ecriture:
    """Paiement sur justificatif : D charges (par ligne) / C 571|521 — 'en_attente'."""
    from apps.approbations.models import Requisition
    from core.models import Tiers
    charge_defaut = _compte("compte_charge", ordre.societe_id)
    tiers = Tiers.objects.filter(id=ordre.beneficiaire_tiers_id).first()
    nom = tiers.nom if tiers else ""
    req = (Requisition.objects.filter(id=ordre.requisition_id).first()
           if ordre.requisition_id else None)
    objet = f" — {req.objet}" if req and req.objet else ""
    lignes: list[dict] = []
    for l in req_lignes:
        lignes.append({"sens": "D", "compte": l.compte_impute or charge_defaut,
                       "montant_usd": l.montant_usd, "devise_origine": l.devise,
                       "montant_origine": l.montant,
                       "libelle": f"{l.description} ({ordre.numero})"})
    lignes.append({"sens": "C", "compte": compte_credit,
                   "montant_usd": ordre.montant_autorise_usd,
                   "libelle": f"Paiement direct à {nom} — {ordre.numero}"})
    return post_ecriture(ordre.societe_id, journal_code, journal_libelle, journal_type,
                         date.today(), f"Paiement direct à {nom} — {ordre.numero}{objet}",
                         lignes, "paiement_direct", "ordre_depense", ordre.id, ordre.numero,
                         created_by, statut="en_attente")


def comptabiliser_justification(justification, avance, created_by,
                                caisse_compte: str | None = None) -> Ecriture:
    """D charges [+ D caisse si solde rendu] / C 421|409 (apurement) — 'en_attente'."""
    from apps.tresorerie.models import JustificationLigne
    from core.models import Tiers
    tiers = Tiers.objects.filter(id=avance.beneficiaire_tiers_id).first()
    compte_av = _compte_avance_tiers(tiers, avance.societe_id)
    charge_defaut = _compte("compte_charge", avance.societe_id)

    lignes: list[dict] = []
    credit_total = justification.montant_justifie_usd
    for l in JustificationLigne.objects.filter(justification_id=justification.id):
        lignes.append({"sens": "D", "compte": l.compte_impute or charge_defaut,
                       "montant_usd": l.montant_usd, "devise_origine": l.devise,
                       "montant_origine": l.montant,
                       "libelle": f"{l.nature} — {tiers.nom} ({avance.numero})"})
    if justification.solde_retourne_usd and justification.solde_retourne_usd > 0:
        caisse_acct = caisse_compte or _compte("compte_caisse", avance.societe_id)
        lignes.append({"sens": "D", "compte": caisse_acct,
                       "montant_usd": justification.solde_retourne_usd,
                       "libelle": f"Retour de solde — avance {avance.numero} de {tiers.nom}"})
        credit_total = credit_total + justification.solde_retourne_usd
    lignes.append({"sens": "C", "compte": compte_av, "montant_usd": credit_total,
                   "tiers_id": tiers.id,
                   "libelle": f"Apurement avance {avance.numero} — {tiers.nom}"})

    return post_ecriture(avance.societe_id, "OD", "Opérations diverses", "od", date.today(),
                         f"Justification avance {avance.numero}", lignes,
                         "justification_avance", "justification", justification.id,
                         justification.numero, created_by, statut="en_attente")


def comptabiliser_stock_entree(societe_id, stock_par_compte: dict, ref: str, jour,
                               source_type: str, source_id, created_by,
                               statut: str = "valide") -> Ecriture:
    """Entrée en stock générique (op. 2) : D 3x (coût) / C 603 (variation)."""
    var = _compte("variation_stock", societe_id)
    total = round(sum(stock_par_compte.values()), 2)
    lignes = [{"sens": "D", "compte": cpt, "montant_usd": round(v, 2),
               "libelle": f"Entrée stock {ref}"} for cpt, v in stock_par_compte.items()]
    lignes.append({"sens": "C", "compte": var, "montant_usd": total,
                   "libelle": f"Variation stock {ref}"})
    return post_ecriture(societe_id, "STK", "Stocks", "od", jour, f"Entrée stock — {ref}",
                         lignes, "variation_stock", source_type, source_id, ref, created_by,
                         statut=statut)
