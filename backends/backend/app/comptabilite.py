"""Moteur de comptabilisation OHADA — génère les écritures à partir des
événements du circuit de décaissement (versement d'avance, justification).

Réutilise la logique de partie double validée dans app.domain.comptabilite.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, services
from .domain.comptabilite import LigneCompta, assert_equilibree

# Comptes OHADA par défaut (paramétrables via la table `parametre`)
DEFAUT = {
    "compte_avance": "409",   # avances versées (fournisseurs débiteurs / personnel)
    "compte_caisse": "571",   # caisse
    "compte_charge": "605",   # autres achats (charge par défaut)
    "compte_attente": "471",  # compte d'attente — à reclasser par le comptable
    "compte_client": "411",   # clients
    "compte_fournisseur": "401",  # fournisseurs
    "tva_deductible": "4452",     # TVA récupérable sur achats
    "tva_collectee": "4431",      # TVA facturée sur ventes
    "variation_stock": "603",     # variation des stocks (inventaire permanent)
    "fournisseur_fnp": "408",     # fournisseurs, factures non parvenues (réception avant facture)
    "ecart_manquant": "658",      # manquant de caisse (charge) — cession de fonds
    "ecart_excedent": "758",      # excédent de caisse (produit) — cession de fonds
    "compte_banque": "521",       # banque (encaissements POS carte/virement)
    "compte_mobile_money": "522", # mobile money (M-Pesa, Airtel Money, Orange Money)
    "compte_vente_transport": "706",   # produits des services de transport
    "compte_sous_traitance": "612",    # sous-traitance transport (camions tiers)
    "manquants_charge": "658",         # manquants transport supportés (chez le transporteur)
    "manquants_produit": "758",        # indemnité manquants reçue (chez l'acheteur)
}


def _compte(db: Session, cle: str, societe_id: uuid.UUID) -> str:
    return services.get_parametre(db, f"compte.{cle}", societe_id, DEFAUT[cle])


# Types de tiers → compte d'avance : 421 (personnel) vs 409 (fournisseur)
_TYPES_PERSONNEL = {"agent", "personnel", "employe", "employé", "salarie", "salarié", "staff", "cadre"}
_TYPES_FOURNISSEUR = {"fournisseur", "supplier", "prestataire"}


def _compte_avance_tiers(db: Session, tiers, societe_id: uuid.UUID) -> str:
    """Compte d'avance à porter au débit selon le bénéficiaire :
    - compte auxiliaire du tiers s'il est défini ;
    - sinon 421 « Personnel, avances et acomptes » pour un agent/employé ;
    - sinon 409 « Fournisseurs débiteurs » pour un fournisseur ;
    - sinon compte d'avance par défaut (409).
    """
    if tiers and tiers.compte_auxiliaire:
        return tiers.compte_auxiliaire
    t = (tiers.type or "").lower() if tiers else ""
    if t in _TYPES_PERSONNEL:
        return services.get_parametre(db, "compte.compte_avance_personnel", societe_id, "421")
    if t in _TYPES_FOURNISSEUR:
        return services.get_parametre(db, "compte.compte_avance_fournisseur", societe_id, "409")
    return _compte(db, "compte_avance", societe_id)


def get_or_create_exercice(db: Session, societe_id: uuid.UUID, jour: date) -> models.Exercice:
    ex = db.execute(
        select(models.Exercice).where(
            models.Exercice.societe_id == societe_id, models.Exercice.annee == jour.year)
    ).scalar_one_or_none()
    if ex is None:
        ex = models.Exercice(societe_id=societe_id, annee=jour.year,
                             date_debut=date(jour.year, 1, 1), date_fin=date(jour.year, 12, 31),
                             statut="ouvert")
        db.add(ex)
        db.flush()
    return ex


def get_or_create_journal(db: Session, societe_id: uuid.UUID, code: str,
                          libelle: str, type_: str) -> models.Journal:
    j = db.execute(
        select(models.Journal).where(
            models.Journal.societe_id == societe_id, models.Journal.code == code)
    ).scalar_one_or_none()
    if j is None:
        j = models.Journal(societe_id=societe_id, code=code, libelle=libelle, type=type_)
        db.add(j)
        db.flush()
    return j


def post_ecriture(db: Session, societe: models.Societe, journal_code: str, journal_libelle: str,
                  journal_type: str, jour: date, libelle: str, lignes: list[dict],
                  type_operation: str, source_type: str, source_id: uuid.UUID,
                  numero_piece: str | None, created_by, statut: str = "valide") -> models.Ecriture:
    """Crée une écriture équilibrée (contrôle D=C avant insertion).

    statut='en_attente' : pièce générée automatiquement, à valider/reclasser par le comptable.
    """
    assert_equilibree([LigneCompta(l["sens"], l["compte"], l["montant_usd"]) for l in lignes])

    exercice = get_or_create_exercice(db, societe.id, jour)
    journal = get_or_create_journal(db, societe.id, journal_code, journal_libelle, journal_type)
    numero = f"{journal_code}-{jour.year}-{_seq(db, societe.id, journal_code, jour.year):05d}"

    ecr = models.Ecriture(
        societe_id=societe.id, exercice_id=exercice.id, journal_id=journal.id,
        numero=numero, date_ecriture=jour, numero_piece=numero_piece, libelle=libelle,
        type_operation=type_operation, source_type=source_type, source_id=source_id,
        statut=statut, created_by=created_by,
    )
    for i, l in enumerate(lignes):
        ecr.lignes.append(models.LigneEcriture(
            societe_id=societe.id, ordre=i, sens=l["sens"], compte_numero=l["compte"],
            tiers_id=l.get("tiers_id"), montant_usd=l["montant_usd"],
            devise_origine=l.get("devise_origine", "USD"),
            montant_origine=l.get("montant_origine"), taux_jour=l.get("taux_jour"),
            libelle_ligne=l.get("libelle"),
        ))
    db.add(ecr)
    db.flush()
    services.enregistrer_audit(db, created_by, "INSERT", "ecriture", ecr.id, None,
                               {"numero": numero, "type": type_operation})
    return ecr


def _seq(db: Session, societe_id, journal_code, annee) -> int:
    """Compteur d'écriture par journal/année (réutilise sequence_compteur)."""
    return _next_compteur(db, societe_id, f"ECR_{journal_code}", annee)


def _next_compteur(db: Session, societe_id, type_piece, annee) -> int:
    c = db.execute(
        select(models.SequenceCompteur).where(
            models.SequenceCompteur.societe_id == societe_id,
            models.SequenceCompteur.type_piece == type_piece,
            models.SequenceCompteur.annee == annee).with_for_update()
    ).scalar_one_or_none()
    if c is None:
        c = models.SequenceCompteur(societe_id=societe_id, type_piece=type_piece,
                                    annee=annee, dernier_numero=0)
        db.add(c)
        db.flush()
    c.dernier_numero += 1
    return c.dernier_numero


# ── Schémas d'écriture par événement ─────────────────────────────────
def comptabiliser_versement_avance(db: Session, avance: models.Avance,
                                   ordre: models.OrdreDepense, tiers: models.Tiers,
                                   compte_credit: str, created_by,
                                   journal_code: str = "CA", journal_libelle: str = "Caisse",
                                   journal_type: str = "caisse") -> models.Ecriture:
    """D 421|409 (avance au bénéficiaire) / C 571 (caisse) ou 521 (banque) — sortie de fonds.

    Écriture mécanique (le compte du bénéficiaire et la trésorerie sont connus) :
    enregistrée directement en 'valide'. Le travail d'imputation du comptable se
    fait à la justification. La ligne d'avance porte le tiers → suivi par personne
    dans le grand livre auxiliaire, lettrable à la justification.
    """
    societe = db.get(models.Societe, avance.societe_id)
    compte_av = _compte_avance_tiers(db, tiers, societe.id)
    montant = avance.montant_avance_usd
    req = db.get(models.Requisition, ordre.requisition_id) if ordre.requisition_id else None
    objet = f" — {req.objet}" if req and req.objet else ""
    lignes = [
        {"sens": "D", "compte": compte_av, "montant_usd": montant, "tiers_id": tiers.id,
         "devise_origine": avance.devise, "montant_origine": avance.montant_avance,
         "libelle": f"Avance à {tiers.nom} ({ordre.numero}){objet}"},
        {"sens": "C", "compte": compte_credit, "montant_usd": montant,
         "libelle": f"Sortie de fonds — avance {avance.numero} à {tiers.nom}"},
    ]
    return post_ecriture(db, societe, journal_code, journal_libelle, journal_type, date.today(),
                         f"Versement d'avance à {tiers.nom} — {ordre.numero}{objet}", lignes,
                         "versement_avance", "avance", avance.id, ordre.numero, created_by,
                         statut="valide")


def comptabiliser_paiement_direct(db: Session, ordre: models.OrdreDepense,
                                  req_lignes, compte_credit: str, created_by,
                                  journal_code: str = "CA", journal_libelle: str = "Caisse",
                                  journal_type: str = "caisse") -> models.Ecriture:
    """Paiement sur justificatif déjà fourni : D charges (par ligne) / C 571|521.
    Aucune avance à justifier n'est créée."""
    societe = db.get(models.Societe, ordre.societe_id)
    charge_defaut = _compte(db, "compte_charge", societe.id)
    tiers = db.get(models.Tiers, ordre.beneficiaire_tiers_id)
    nom = tiers.nom if tiers else ""
    req = db.get(models.Requisition, ordre.requisition_id) if ordre.requisition_id else None
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
    return post_ecriture(db, societe, journal_code, journal_libelle, journal_type, date.today(),
                         f"Paiement direct à {nom} — {ordre.numero}{objet}", lignes,
                         "paiement_direct", "ordre_depense", ordre.id, ordre.numero, created_by,
                         statut="en_attente")


def comptabiliser_transfert(db: Session, transfert, compte_dest: str, compte_source: str,
                            libelle: str, created_by, montant_recu_usd: float | None = None) -> models.Ecriture:
    """Virement interne : D compte destination / C compte source (en attente).

    Si `montant_recu_usd` diffère du montant émis (cas d'une cession de caisse POS où
    le caissier principal reçoit physiquement plus ou moins que déclaré), l'écart est
    constaté : le manquant en charge (658), l'excédent en produit (758). La source est
    toujours créditée du montant émis (les fonds l'ont quittée) ; la destination reçoit
    le montant réellement encaissé."""
    societe = db.get(models.Societe, transfert.societe_id)
    emis = round(float(transfert.montant_usd), 2)
    recu = round(float(montant_recu_usd), 2) if montant_recu_usd is not None else emis
    lignes = [
        {"sens": "D", "compte": compte_dest, "montant_usd": recu, "libelle": libelle,
         "devise_origine": transfert.devise, "montant_origine": transfert.montant},
        {"sens": "C", "compte": compte_source, "montant_usd": emis, "libelle": libelle},
    ]
    ecart = round(emis - recu, 2)
    if ecart > 0:      # manquant : la destination reçoit moins que déclaré → charge
        lignes.append({"sens": "D", "compte": _compte(db, "ecart_manquant", societe.id),
                       "montant_usd": ecart, "libelle": f"Manquant de caisse — {transfert.numero}"})
    elif ecart < 0:    # excédent : la destination reçoit plus que déclaré → produit
        lignes.append({"sens": "C", "compte": _compte(db, "ecart_excedent", societe.id),
                       "montant_usd": -ecart, "libelle": f"Excédent de caisse — {transfert.numero}"})
    return post_ecriture(db, societe, "VI", "Virements internes", "od", date.today(),
                         f"Transfert {transfert.numero} — {libelle}", lignes,
                         "transfert", "transfert", transfert.id, transfert.numero, created_by,
                         statut="en_attente")


def comptabiliser_operation_caisse(db: Session, societe: models.Societe, sens: str,
                                   montant_usd, libelle: str, source_id: uuid.UUID,
                                   numero_piece: str, created_by, nature: str = "",
                                   devise: str = "USD", montant_origine=None,
                                   tiers_id=None) -> models.Ecriture:
    """Opération de caisse manuelle (encaissement / sortie).

    La contrepartie n'est pas connue au moment de la saisie caisse : on l'impute
    sur un compte d'attente (471) que le comptable reclasse ensuite vers le vrai
    compte (produit 7xx, client 41x, charge 6xx, fournisseur 40x…).

    entrée : D 571 (caisse)   / C 471 (à reclasser)
    sortie : D 471 (à reclasser) / C 571 (caisse)
    """
    caisse_acct = _compte(db, "compte_caisse", societe.id)
    attente_acct = _compte(db, "compte_attente", societe.id)
    lib = libelle or nature or ("Encaissement" if sens == "entree" else "Sortie de caisse")
    ligne_caisse = {"sens": "D" if sens == "entree" else "C", "compte": caisse_acct,
                    "montant_usd": montant_usd, "devise_origine": devise,
                    "montant_origine": montant_origine, "tiers_id": tiers_id, "libelle": lib}
    ligne_attente = {"sens": "C" if sens == "entree" else "D", "compte": attente_acct,
                     "montant_usd": montant_usd,
                     "libelle": f"À reclasser — {lib}"}
    lignes = [ligne_caisse, ligne_attente] if sens == "entree" else [ligne_attente, ligne_caisse]
    return post_ecriture(db, societe, "CA", "Caisse", "caisse", date.today(),
                         lib, lignes, "operation_caisse", "mouvement_caisse", source_id,
                         numero_piece, created_by, statut="en_attente")


def comptabiliser_facture(db: Session, facture, lignes_facture, created_by,
                          frais_objs=None, statut: str = "valide") -> models.Ecriture:
    """Facture d'achat : D 60x (marchandises HT) + D TVA / C 401 (fournisseur X) — puis,
    pour CHAQUE frais accessoire, D 6085 (HT) [+ D TVA] / C sa propre contrepartie
    (fournisseur Y à crédit, banque, ou caisse). Le stock est incorporé à part (603/31).
    Facture de vente : D 411 / C produits + C TVA."""
    societe = db.get(models.Societe, facture.societe_id)
    tiers = db.get(models.Tiers, facture.tiers_id)
    lignes: list[dict] = []

    if facture.type == "achat":
        # ── Marchandises (fournisseur X) : HT + TVA marchandises / C 401 ──
        by_achat: dict[str, float] = {}
        goods_ht = goods_tva = 0.0
        for l in lignes_facture:
            art = db.get(models.Article, l.article_id) if l.article_id else None
            compte = (art.compte_achat if art else None) or _compte(db, "compte_charge", societe.id)
            by_achat[compte] = by_achat.get(compte, 0.0) + float(l.montant_ht)
            goods_ht += float(l.montant_ht)
            goods_tva += float(l.montant_tva)
        for compte, ht in by_achat.items():
            lignes.append({"sens": "D", "compte": compte, "montant_usd": round(ht, 2),
                           "libelle": f"Achat {facture.numero}"})
        if round(goods_tva, 2):
            lignes.append({"sens": "D", "compte": _compte(db, "tva_deductible", societe.id),
                           "montant_usd": round(goods_tva, 2), "libelle": f"TVA déductible {facture.numero}"})
        goods_ttc = round(goods_ht + goods_tva, 2)
        if goods_ttc:
            lignes.append({"sens": "C", "compte": _compte(db, "compte_fournisseur", societe.id),
                           "montant_usd": goods_ttc, "tiers_id": tiers.id,
                           "libelle": f"Fournisseur {tiers.nom} — {facture.numero}"})

        # ── Frais accessoires : chacun avec SA contrepartie ──
        for f in (frais_objs or []):
            fht = round(float(f.montant_ht), 2)
            ftva = round(float(f.montant_tva or 0), 2)
            lignes.append({"sens": "D", "compte": f.compte, "montant_usd": fht,
                           "libelle": f"{f.libelle} — {facture.numero}"})
            if ftva:
                lignes.append({"sens": "D", "compte": _compte(db, "tva_deductible", societe.id),
                               "montant_usd": ftva, "libelle": f"TVA déductible frais {facture.numero}"})
            fttc = round(fht + ftva, 2)
            if f.mode == "credit":
                ft = db.get(models.Tiers, f.tiers_id) if f.tiers_id else tiers
                lignes.append({"sens": "C", "compte": _compte(db, "compte_fournisseur", societe.id),
                               "montant_usd": fttc, "tiers_id": ft.id if ft else None,
                               "libelle": f"Frais {f.libelle} — {ft.nom if ft else ''}"})
            else:   # banque | caisse : contrepartie trésorerie
                cpt = f.compte_reglement or _compte(db, "compte_caisse", societe.id)
                lignes.append({"sens": "C", "compte": cpt, "montant_usd": fttc,
                               "libelle": f"Règlement frais {f.libelle} — {facture.numero}"})
        jcode, jlib, jtyp, lib = "AC", "Achats", "achat", f"Facture achat {facture.numero} — {tiers.nom}"
    else:
        ttc = round(float(facture.total_ttc), 2)
        tva = round(float(facture.total_tva), 2)
        lignes.append({"sens": "D", "compte": _compte(db, "compte_client", societe.id),
                       "montant_usd": ttc, "tiers_id": tiers.id,
                       "libelle": f"Client {tiers.nom} — {facture.numero}"})
        by_compte = {}
        for l in lignes_facture:
            art = db.get(models.Article, l.article_id) if l.article_id else None
            compte = (art.compte_vente if art else None) or "701"
            by_compte[compte] = by_compte.get(compte, 0.0) + float(l.montant_ht)
        for compte, ht in by_compte.items():
            lignes.append({"sens": "C", "compte": compte, "montant_usd": round(ht, 2),
                           "libelle": f"Vente {facture.numero}"})
        if tva:
            lignes.append({"sens": "C", "compte": _compte(db, "tva_collectee", societe.id),
                           "montant_usd": tva, "libelle": f"TVA collectée {facture.numero}"})
        jcode, jlib, jtyp, lib = "VE", "Ventes", "vente", f"Facture vente {facture.numero} — {tiers.nom}"

    return post_ecriture(db, societe, jcode, jlib, jtyp, facture.date_facture, lib, lignes,
                         f"facture_{facture.type}", "facture", facture.id, facture.numero,
                         created_by, statut=statut)


def comptabiliser_reception(db: Session, reception, goods_par_compte: dict, frais_par_compte: dict,
                            frais_objs, created_by, statut="valide") -> models.Ecriture:
    """Réception de marchandises. Deux flux distincts :

    • MARCHANDISES → pont fournisseur : D 31 (prix) / C 408 (factures non parvenues,
      fournisseur X — provisoire jusqu'à la facture).
    • FRAIS accessoires → chacun avec SA propre contrepartie réelle :
      D 6085 (HT) [+ D 4452 TVA] / C 401 (fournisseur Y du frais) | 571 | 521,
      puis incorporation au stock D 31 (quote-part) / C 603.

    Ainsi un frais n'est jamais collé à la dette du fournisseur des marchandises : il
    correspond toujours à une vraie dette ou à une vraie sortie de fonds."""
    societe = db.get(models.Societe, reception.societe_id)
    cmd = db.get(models.Commande, reception.commande_id)
    fnp = _compte(db, "fournisseur_fnp", societe.id)
    fournisseur = _compte(db, "compte_fournisseur", societe.id)
    var = _compte(db, "variation_stock", societe.id)
    tva_ded = _compte(db, "tva_deductible", societe.id)
    lignes: list[dict] = []

    # ── Marchandises → 408 (fournisseur X, provisoire) ──
    goods_total = round(sum(goods_par_compte.values()), 2)
    for cpt, v in goods_par_compte.items():
        if round(v, 2):
            lignes.append({"sens": "D", "compte": cpt, "montant_usd": round(v, 2),
                           "libelle": f"Réception {reception.numero}"})
    if goods_total:
        lignes.append({"sens": "C", "compte": fnp, "montant_usd": goods_total,
                       "libelle": f"Réception non facturée {reception.numero}"})

    # ── Frais accessoires → contrepartie propre ──
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
            tid = f.tiers_id or (cmd.tiers_id if cmd else None)   # défaut = fournisseur des marchandises
            lignes.append({"sens": "C", "compte": fournisseur, "montant_usd": fttc,
                           "tiers_id": tid, "libelle": f"Frais {f.libelle}"})
        else:   # banque | caisse
            cpt = f.compte_reglement or _compte(db, "compte_caisse", societe.id)
            lignes.append({"sens": "C", "compte": cpt, "montant_usd": fttc,
                           "libelle": f"Règlement frais {f.libelle}"})

    # ── Incorporation des frais au coût du stock (D 31 / C 603) ──
    frais_total = round(sum(frais_par_compte.values()), 2)
    for cpt, v in frais_par_compte.items():
        if round(v, 2):
            lignes.append({"sens": "D", "compte": cpt, "montant_usd": round(v, 2),
                           "libelle": f"Frais incorporés {reception.numero}"})
    if frais_total:
        lignes.append({"sens": "C", "compte": var, "montant_usd": frais_total,
                       "libelle": f"Incorporation frais {reception.numero}"})

    return post_ecriture(db, societe, "AC", "Achats", "achat", reception.date_reception,
                         f"Réception {reception.numero}", lignes,
                         "reception", "reception", reception.id, reception.numero,
                         created_by, statut=statut)


def comptabiliser_facture_reception(db: Session, facture, reception, created_by,
                                    statut="valide") -> models.Ecriture:
    """Facture du fournisseur des MARCHANDISES (les frais ont déjà été reconnus, avec
    leur propre contrepartie, à la réception). Convention « toujours 601 » :
      D 601 (prix d'achat) + D 4452 (TVA marchandises) + D 408 (solde le provisoire)
      / C 401 (dette fournisseur X, TTC marchandises) + C 603 (incorporation marchandises)

    Fait apparaître la charge d'achat 601 au prix et solde le pont 408 alimenté à la
    réception. N'inclut plus les frais (eux ont leur propre pièce à la réception)."""
    societe = db.get(models.Societe, facture.societe_id)
    tiers = db.get(models.Tiers, facture.tiers_id)
    fnp = _compte(db, "fournisseur_fnp", societe.id)
    var = _compte(db, "variation_stock", societe.id)

    rec_lignes = db.execute(select(models.LigneReception).where(
        models.LigneReception.reception_id == reception.id)).scalars().all()
    goods_ht = round(sum(float(l.montant_ht) for l in rec_lignes), 2)
    goods_tva = round(sum(round(float(l.montant_ht) * float(l.taux_tva) / 100, 2) for l in rec_lignes), 2)
    goods_ttc = round(goods_ht + goods_tva, 2)

    lignes: list[dict] = []
    by_achat: dict[str, float] = {}
    for l in rec_lignes:
        art = db.get(models.Article, l.article_id) if l.article_id else None
        compte = (art.compte_achat if art else None) or "601"
        by_achat[compte] = by_achat.get(compte, 0.0) + float(l.montant_ht)
    for compte, ht in by_achat.items():
        lignes.append({"sens": "D", "compte": compte, "montant_usd": round(ht, 2),
                       "libelle": f"Achat {facture.numero}"})
    if goods_tva:
        lignes.append({"sens": "D", "compte": _compte(db, "tva_deductible", societe.id),
                       "montant_usd": goods_tva, "libelle": f"TVA déductible {facture.numero}"})
    lignes.append({"sens": "D", "compte": fnp, "montant_usd": goods_ht,
                   "libelle": f"Solde réception {reception.numero}"})
    lignes.append({"sens": "C", "compte": _compte(db, "compte_fournisseur", societe.id),
                   "montant_usd": goods_ttc, "tiers_id": tiers.id,
                   "libelle": f"Fournisseur {tiers.nom} — {facture.numero}"})
    lignes.append({"sens": "C", "compte": var, "montant_usd": goods_ht,
                   "libelle": f"Variation stock {reception.numero}"})
    return post_ecriture(db, societe, "AC", "Achats", "achat", facture.date_facture,
                         f"Facture réception {facture.numero} — {tiers.nom}", lignes,
                         "facture_achat", "facture", facture.id, facture.numero,
                         created_by, statut=statut)


def comptabiliser_vente_pos(db: Session, facture, lignes_facture, encaissements: list[dict],
                            created_by) -> models.Ecriture:
    """Vente en point de vente, règlement possiblement fractionné :
    D trésorerie (caisse/mobile money/banque) et/ou D 411 (part à crédit)
    / C 70x (HT net de remise) + C 4431 (TVA).

    `encaissements` : [{compte, montant_usd, libelle, devise?, montant?, taux?, tiers_id?}]
    — la somme doit faire le TTC (le POS a déjà retranché la monnaie rendue)."""
    societe = db.get(models.Societe, facture.societe_id)
    tva = round(float(facture.total_tva), 2)
    lignes = [{"sens": "D", "compte": e["compte"], "montant_usd": round(e["montant_usd"], 2),
               "libelle": e.get("libelle") or f"Encaissement POS {facture.numero}",
               "tiers_id": e.get("tiers_id"), "devise_origine": e.get("devise", "USD"),
               "montant_origine": e.get("montant"), "taux_jour": e.get("taux")}
              for e in encaissements if round(e["montant_usd"], 2) != 0]
    by_compte: dict[str, float] = {}
    for l in lignes_facture:
        art = db.get(models.Article, l.article_id) if l.article_id else None
        compte = (art.compte_vente if art else None) or "701"
        by_compte[compte] = by_compte.get(compte, 0.0) + float(l.montant_ht)
    for compte, ht in by_compte.items():
        lignes.append({"sens": "C", "compte": compte, "montant_usd": round(ht, 2),
                       "libelle": f"Vente POS {facture.numero}"})
    if tva:
        lignes.append({"sens": "C", "compte": _compte(db, "tva_collectee", societe.id),
                       "montant_usd": tva, "libelle": f"TVA collectée {facture.numero}"})
    return post_ecriture(db, societe, "VE", "Ventes", "vente", facture.date_facture,
                         f"Vente POS {facture.numero}", lignes, "vente_pos", "facture",
                         facture.id, facture.numero, created_by, statut="valide")


def comptabiliser_retour_pos(db: Session, avoir, lignes_avoir, remboursements: list[dict],
                             created_by) -> models.Ecriture:
    """Retour client (avoir POS) — écriture inverse de la vente :
    D 70x (HT repris) + D 4431 (TVA) / C trésorerie (remboursement espèces)
    ou C 411 (avoir porté au crédit du compte client)."""
    societe = db.get(models.Societe, avoir.societe_id)
    tva = round(float(avoir.total_tva), 2)
    lignes = []
    by_compte: dict[str, float] = {}
    for l in lignes_avoir:
        art = db.get(models.Article, l.article_id) if l.article_id else None
        compte = (art.compte_vente if art else None) or "701"
        by_compte[compte] = by_compte.get(compte, 0.0) + float(l.montant_ht)
    for compte, ht in by_compte.items():
        lignes.append({"sens": "D", "compte": compte, "montant_usd": round(ht, 2),
                       "libelle": f"Retour POS {avoir.numero}"})
    if tva:
        lignes.append({"sens": "D", "compte": _compte(db, "tva_collectee", societe.id),
                       "montant_usd": tva, "libelle": f"TVA sur retour {avoir.numero}"})
    for r in remboursements:
        if round(r["montant_usd"], 2) != 0:
            lignes.append({"sens": "C", "compte": r["compte"], "montant_usd": round(r["montant_usd"], 2),
                           "libelle": r.get("libelle") or f"Remboursement {avoir.numero}",
                           "tiers_id": r.get("tiers_id")})
    return post_ecriture(db, societe, "VE", "Ventes", "vente", avoir.date_facture,
                         f"Retour POS {avoir.numero}", lignes, "retour_pos", "facture",
                         avoir.id, avoir.numero, created_by, statut="valide")


def comptabiliser_stock_entree(db: Session, societe, stock_par_compte: dict, ref: str, jour,
                               source_type: str, source_id, created_by,
                               statut: str = "valide") -> models.Ecriture:
    """Entrée en stock générique (op. 2) : D 3x (coût) / C 603 (variation)."""
    var = _compte(db, "variation_stock", societe.id)
    total = round(sum(stock_par_compte.values()), 2)
    lignes = [{"sens": "D", "compte": cpt, "montant_usd": round(v, 2), "libelle": f"Entrée stock {ref}"}
              for cpt, v in stock_par_compte.items()]
    lignes.append({"sens": "C", "compte": var, "montant_usd": total, "libelle": f"Variation stock {ref}"})
    return post_ecriture(db, societe, "STK", "Stocks", "od", jour, f"Entrée stock — {ref}", lignes,
                         "variation_stock", source_type, source_id, ref, created_by, statut=statut)


def comptabiliser_stock_sortie(db: Session, societe, stock_par_compte: dict, ref: str, jour,
                               source_type: str, source_id, created_by,
                               statut: str = "valide") -> models.Ecriture:
    """Sortie de stock générique (livraison client) : D 603 (coût des ventes) / C 3x."""
    var = _compte(db, "variation_stock", societe.id)
    total = round(sum(stock_par_compte.values()), 2)
    lignes = [{"sens": "D", "compte": var, "montant_usd": total, "libelle": f"Coût des ventes {ref}"}]
    lignes += [{"sens": "C", "compte": cpt, "montant_usd": round(v, 2), "libelle": f"Sortie stock {ref}"}
               for cpt, v in stock_par_compte.items()]
    return post_ecriture(db, societe, "STK", "Stocks", "od", jour, f"Sortie stock — {ref}", lignes,
                         "variation_stock", source_type, source_id, ref, created_by, statut=statut)


def comptabiliser_variation_stock(db: Session, facture, compte_stock: str, valeur: float,
                                  entree: bool, created_by) -> models.Ecriture:
    """Inventaire permanent : entrée en stock D 3x / C 603 ; sortie D 603 / C 3x.
    Rend le résultat correct (charges = achats − Δstock)."""
    societe = db.get(models.Societe, facture.societe_id)
    var = _compte(db, "variation_stock", societe.id)
    m = round(valeur, 2)
    if entree:
        lignes = [{"sens": "D", "compte": compte_stock, "montant_usd": m, "libelle": f"Entrée stock {facture.numero}"},
                  {"sens": "C", "compte": var, "montant_usd": m, "libelle": f"Variation stock {facture.numero}"}]
    else:
        lignes = [{"sens": "D", "compte": var, "montant_usd": m, "libelle": f"Coût des ventes {facture.numero}"},
                  {"sens": "C", "compte": compte_stock, "montant_usd": m, "libelle": f"Sortie stock {facture.numero}"}]
    return post_ecriture(db, societe, "STK", "Stocks", "od", facture.date_facture,
                         f"Variation de stock — {facture.numero}", lignes,
                         "variation_stock", "facture", facture.id, facture.numero,
                         created_by, statut="valide")


def comptabiliser_justification(db: Session, justification: models.Justification,
                                avance: models.Avance, created_by,
                                caisse_compte: str | None = None) -> models.Ecriture:
    """D charges (par ligne) [+ D caisse si solde rendu] / C 421|409 (apurement avance).

    Apure le MÊME compte de bénéficiaire que le versement → le solde du tiers
    revient à zéro s'il justifie tout ; sinon le reliquat reste débiteur (à
    récupérer / retenir sur paie). C'est la pièce qui nécessite la validation du
    comptable (choix / éclatement des comptes de charge)."""
    societe = db.get(models.Societe, avance.societe_id)
    tiers = db.get(models.Tiers, avance.beneficiaire_tiers_id)
    compte_av = _compte_avance_tiers(db, tiers, societe.id)
    charge_defaut = _compte(db, "compte_charge", societe.id)

    lignes: list[dict] = []
    credit_total = justification.montant_justifie_usd
    for l in justification.lignes:
        lignes.append({"sens": "D", "compte": l.compte_impute or charge_defaut,
                       "montant_usd": l.montant_usd, "devise_origine": l.devise,
                       "montant_origine": l.montant,
                       "libelle": f"{l.nature} — {tiers.nom} ({avance.numero})"})
    if justification.solde_retourne_usd and justification.solde_retourne_usd > 0:
        caisse_acct = caisse_compte or _compte(db, "compte_caisse", societe.id)
        lignes.append({"sens": "D", "compte": caisse_acct,
                       "montant_usd": justification.solde_retourne_usd,
                       "libelle": f"Retour de solde — avance {avance.numero} de {tiers.nom}"})
        credit_total = credit_total + justification.solde_retourne_usd
    lignes.append({"sens": "C", "compte": compte_av, "montant_usd": credit_total,
                   "tiers_id": tiers.id,
                   "libelle": f"Apurement avance {avance.numero} — {tiers.nom}"})

    return post_ecriture(db, societe, "OD", "Opérations diverses", "od", date.today(),
                         f"Justification avance {avance.numero}", lignes,
                         "justification_avance", "justification", justification.id,
                         justification.numero, created_by, statut="en_attente")


def compute_balance(db: Session, societe_id: uuid.UUID) -> list[dict]:
    """Balance simple : par compte, total débit/crédit et solde (USD)."""
    rows = db.execute(
        select(models.LigneEcriture.compte_numero, models.LigneEcriture.sens,
               models.LigneEcriture.montant_usd)
        .where(models.LigneEcriture.societe_id == societe_id)
    ).all()
    agg: dict[str, dict] = {}
    for compte, sens, montant in rows:
        a = agg.setdefault(compte, {"compte": compte, "debit": 0.0, "credit": 0.0})
        if sens == "D":
            a["debit"] += float(montant)
        else:
            a["credit"] += float(montant)
    for a in agg.values():
        a["solde"] = round(a["debit"] - a["credit"], 2)
        a["debit"] = round(a["debit"], 2)
        a["credit"] = round(a["credit"], 2)
    return sorted(agg.values(), key=lambda x: x["compte"])
