"""États financiers SYSCOHADA — portage exact de backend/app/etats_financiers.py.

Mêmes calculs (compte de résultat en cascade, bilan N/N-1, TFT, cockpit DAF) ;
seules les requêtes ORM changent (QuerySet au lieu de select SQLAlchemy).
"""
from __future__ import annotations

from datetime import date

from apps.comptabilite.models import Compte, Ecriture, LigneEcriture


def _rows(societe_id, statut: str | None = None) -> list[tuple]:
    """(compte, sens, montant, date) de toutes les lignes d'écriture."""
    q = LigneEcriture.objects.filter(societe_id=societe_id)
    if statut:
        q = q.filter(ecriture__statut=statut)
    return [(c, s, float(m), d) for c, s, m, d in
            q.values_list("compte_numero", "sens", "montant_usd", "ecriture__date_ecriture")]


def _agg(rows: list[tuple], pred) -> dict[str, float]:
    """Solde (D − C) par compte pour les lignes retenues par `pred(date)`."""
    d: dict[str, float] = {}
    for compte, sens, m, dte in rows:
        if not pred(dte):
            continue
        d[compte] = d.get(compte, 0.0) + (m if sens == "D" else -m)
    return d


def _soldes(societe_id, statut: str | None = None) -> dict[str, float]:
    return _agg(_rows(societe_id, statut), lambda _d: True)


def _labels(societe_id) -> dict[str, str]:
    rows = Compte.objects.filter(societe_id=societe_id).values_list("numero", "intitule")
    return {n: i for n, i in rows if len(n) == 2}


def _pref(soldes: dict[str, float], prefixes: list[str], produit: bool) -> float:
    s = sum(v for c, v in soldes.items() if any(c.startswith(p) for p in prefixes))
    return round(-s if produit else s, 2)


def _lignes(sN: dict, sN1: dict, prefixes: list[str], produit: bool,
            labels: dict[str, str]) -> tuple[list[dict], float, float]:
    out, tot, tot1 = [], 0.0, 0.0
    for p in prefixes:
        m = _pref(sN, [p], produit)
        m1 = _pref(sN1, [p], produit)
        if abs(m) >= 0.005 or abs(m1) >= 0.005:
            out.append({"poste": p, "intitule": labels.get(p, p), "montant": m, "montant_n1": m1})
            tot += m
            tot1 += m1
    return out, round(tot, 2), round(tot1, 2)


# Postes SYSCOHADA (préfixes à 2 chiffres)
EXP_PROD = ["70", "71", "72", "73", "75", "78", "79"]
EXP_CH = ["60", "61", "62", "63", "64", "65", "66", "68", "69"]
FIN_PROD = ["77"]
FIN_CH = ["67"]
HAO_PROD = ["82", "84", "86", "88"]
HAO_CH = ["81", "83", "85", "87"]


def _resultat_net(soldes: dict[str, float]) -> float:
    prod = sum(-v for c, v in soldes.items() if c[:1] == "7")
    charges = sum(v for c, v in soldes.items() if c[:1] == "6")
    hao_prod = sum(-v for c, v in soldes.items() if any(c.startswith(p) for p in HAO_PROD))
    hao_ch = sum(v for c, v in soldes.items() if any(c.startswith(p) for p in HAO_CH))
    impot = sum(v for c, v in soldes.items() if c.startswith("89"))
    return round(prod - charges + hao_prod - hao_ch - impot, 2)


def compte_resultat(societe_id, statut: str | None = None, annee: int | None = None) -> dict:
    annee = annee or date.today().year
    rows = _rows(societe_id, statut)
    sN = _agg(rows, lambda d: d.year == annee)          # produits/charges = flux de l'exercice
    sN1 = _agg(rows, lambda d: d.year == annee - 1)
    labels = _labels(societe_id)

    def solde(lbl, m, m1, fort=False):
        return {"solde": lbl, "montant": round(m, 2), "montant_n1": round(m1, 2), "fort": fort}

    p_exp, tpe, tpe1 = _lignes(sN, sN1, EXP_PROD, True, labels)
    c_exp, tce, tce1 = _lignes(sN, sN1, EXP_CH, False, labels)
    re, re1 = tpe - tce, tpe1 - tce1
    p_fin, tpf, tpf1 = _lignes(sN, sN1, FIN_PROD, True, labels)
    c_fin, tcf, tcf1 = _lignes(sN, sN1, FIN_CH, False, labels)
    rf, rf1 = tpf - tcf, tpf1 - tcf1
    rao, rao1 = re + rf, re1 + rf1
    p_hao, tph, tph1 = _lignes(sN, sN1, HAO_PROD, True, labels)
    c_hao, tch, tch1 = _lignes(sN, sN1, HAO_CH, False, labels)
    rhao, rhao1 = tph - tch, tph1 - tch1
    imp, imp1 = _pref(sN, ["89"], False), _pref(sN1, ["89"], False)
    rn, rn1 = rao + rhao - imp, rao1 + rhao1 - imp1

    return {
        "annee": annee,
        "sections": [
            {"titre": "Produits d'exploitation", "sens": "produit", "lignes": p_exp, "total": round(tpe, 2), "total_n1": round(tpe1, 2)},
            {"titre": "Charges d'exploitation", "sens": "charge", "lignes": c_exp, "total": round(tce, 2), "total_n1": round(tce1, 2)},
            solde("Résultat d'exploitation", re, re1),
            {"titre": "Produits financiers", "sens": "produit", "lignes": p_fin, "total": round(tpf, 2), "total_n1": round(tpf1, 2)},
            {"titre": "Charges financières", "sens": "charge", "lignes": c_fin, "total": round(tcf, 2), "total_n1": round(tcf1, 2)},
            solde("Résultat financier", rf, rf1),
            solde("Résultat des activités ordinaires", rao, rao1, True),
            {"titre": "Produits HAO", "sens": "produit", "lignes": p_hao, "total": round(tph, 2), "total_n1": round(tph1, 2)},
            {"titre": "Charges HAO", "sens": "charge", "lignes": c_hao, "total": round(tch, 2), "total_n1": round(tch1, 2)},
            solde("Résultat HAO", rhao, rhao1),
            solde("Impôts sur le résultat", -imp, -imp1),
        ],
        "resultat_net": round(rn, 2), "resultat_net_n1": round(rn1, 2),
        "chiffre_affaires": _pref(sN, ["70"], True),
        "chiffre_affaires_n1": _pref(sN1, ["70"], True),
    }


def _bilan_chiffres(soldes: dict[str, float], labels: dict[str, str]) -> dict:
    lignes, t_immo, _ = _lignes(soldes, soldes, ["20", "21", "22", "23", "24", "25", "26", "27", "28", "29"], False, labels)
    stocks = round(sum(v for c, v in soldes.items() if c[:1] == "3"), 2)
    creances = round(sum(v for c, v in soldes.items() if c[:1] == "4" and v > 0), 2)
    tres_a = round(sum(v for c, v in soldes.items() if c[:1] == "5" and v > 0), 2)
    total_actif = round(t_immo + stocks + creances + tres_a, 2)
    rn = _resultat_net(soldes)
    capitaux = round(sum(-v for c, v in soldes.items()
                         if c[:1] == "1" and c[:2] not in ("16", "18", "19")), 2)
    cap_propres = round(capitaux + rn, 2)
    dettes_fin = round(sum(-v for c, v in soldes.items() if c[:2] in ("16", "18", "19")), 2)
    passif_circ = round(sum(-v for c, v in soldes.items() if c[:1] == "4" and v < 0), 2)
    tres_p = round(sum(-v for c, v in soldes.items() if c[:1] == "5" and v < 0), 2)
    total_passif = round(cap_propres + dettes_fin + passif_circ + tres_p, 2)
    return {
        "immo": t_immo, "immo_lignes": lignes, "stocks": stocks, "creances": creances,
        "circulant": round(stocks + creances, 2), "tres_actif": tres_a, "total_actif": total_actif,
        "capital_reserves": capitaux, "resultat_net": rn, "cap_propres": cap_propres,
        "dettes_fin": dettes_fin, "passif_circ": passif_circ, "tres_passif": tres_p,
        "total_passif": total_passif,
    }


def bilan(societe_id, statut: str | None = None, annee: int | None = None) -> dict:
    annee = annee or date.today().year
    rows = _rows(societe_id, statut)
    N = _bilan_chiffres(_agg(rows, lambda d: d.year <= annee), _labels(societe_id))
    N1 = _bilan_chiffres(_agg(rows, lambda d: d.year <= annee - 1), _labels(societe_id))
    return {
        "annee": annee,
        "actif": {
            "immobilise": {"total": N["immo"], "total_n1": N1["immo"], "lignes": N["immo_lignes"]},
            "circulant": {"total": N["circulant"], "total_n1": N1["circulant"],
                          "stocks": N["stocks"], "stocks_n1": N1["stocks"],
                          "creances": N["creances"], "creances_n1": N1["creances"]},
            "tresorerie": N["tres_actif"], "tresorerie_n1": N1["tres_actif"],
            "total": N["total_actif"], "total_n1": N1["total_actif"],
        },
        "passif": {
            "capitaux_propres": {"total": N["cap_propres"], "total_n1": N1["cap_propres"],
                                 "capital_reserves": N["capital_reserves"], "capital_reserves_n1": N1["capital_reserves"],
                                 "resultat_net": N["resultat_net"], "resultat_net_n1": N1["resultat_net"]},
            "dettes_financieres": N["dettes_fin"], "dettes_financieres_n1": N1["dettes_fin"],
            "passif_circulant": N["passif_circ"], "passif_circulant_n1": N1["passif_circ"],
            "tresorerie": N["tres_passif"], "tresorerie_n1": N1["tres_passif"],
            "total": N["total_passif"], "total_n1": N1["total_passif"],
        },
        "equilibre": abs(N["total_actif"] - N["total_passif"]) < 0.01,
        "ecart": round(N["total_actif"] - N["total_passif"], 2),
    }


def tft(societe_id, statut: str | None = None, annee: int | None = None) -> dict:
    annee = annee or date.today().year
    rows = _rows(societe_id, statut)
    ouverture = _agg(rows, lambda d: d.year < annee)
    delta = _agg(rows, lambda d: d.year == annee)   # mouvements de l'exercice

    def dsum(pred):
        return round(sum(v for c, v in delta.items() if pred(c)), 2)

    tres_ouv = round(sum(v for c, v in ouverture.items() if c[:1] == "5"), 2)
    resultat = -dsum(lambda c: c[:1] in ("6", "7", "8"))
    var_stocks = -dsum(lambda c: c[:1] == "3")
    var_tiers = -dsum(lambda c: c[:1] == "4")
    operationnel = round(resultat + var_stocks + var_tiers, 2)
    investissement = -dsum(lambda c: c[:1] == "2")
    financement = -dsum(lambda c: c[:1] == "1")
    variation = round(operationnel + investissement + financement, 2)
    tres_clo = round(tres_ouv + variation, 2)

    return {
        "annee": annee,
        "tresorerie_ouverture": tres_ouv,
        "flux": [
            {"titre": "Flux de trésorerie des activités opérationnelles", "total": operationnel,
             "lignes": [
                 {"libelle": "Résultat net et éléments non décaissés (CAF)", "montant": resultat},
                 {"libelle": "Variation des stocks", "montant": var_stocks},
                 {"libelle": "Variation des créances et dettes (BFR)", "montant": var_tiers},
             ]},
            {"titre": "Flux de trésorerie des activités d'investissement", "total": investissement,
             "lignes": [{"libelle": "Acquisitions et cessions d'immobilisations", "montant": investissement}]},
            {"titre": "Flux de trésorerie des activités de financement", "total": financement,
             "lignes": [{"libelle": "Capitaux propres, emprunts et remboursements", "montant": financement}]},
        ],
        "variation": variation,
        "tresorerie_cloture": tres_clo,
        "controle": abs((tres_ouv + variation) - tres_clo) < 0.01,
    }


def cockpit(societe_id) -> dict:
    """Indicateurs financiers de synthèse pour le DAF."""
    soldes = _soldes(societe_id)
    caisse = round(sum(v for c, v in soldes.items() if c.startswith("57")), 2)
    banque = round(sum(v for c, v in soldes.items() if c.startswith("52")), 2)
    creances = round(sum(v for c, v in soldes.items() if c.startswith("41") and v > 0), 2)
    dettes = round(sum(-v for c, v in soldes.items() if c.startswith("40") and v < 0), 2)
    tva_collectee = round(sum(-v for c, v in soldes.items() if c.startswith("443")), 2)
    tva_deductible = round(sum(v for c, v in soldes.items() if c.startswith("445")), 2)
    avances = round(sum(v for c, v in soldes.items()
                        if (c.startswith("421") or c.startswith("409")) and v > 0), 2)
    ca = round(sum(-v for c, v in soldes.items() if c.startswith("70")), 2)
    charges = round(sum(v for c, v in soldes.items() if c[:1] == "6"), 2)
    en_attente = Ecriture.objects.filter(societe_id=societe_id, statut="en_attente").count()
    return {
        "tresorerie": {"caisse": caisse, "banque": banque, "total": round(caisse + banque, 2)},
        "creances_clients": creances,
        "dettes_fournisseurs": dettes,
        "chiffre_affaires": ca,
        "charges": charges,
        "resultat": _resultat_net(soldes),
        "tva_a_payer": round(tva_collectee - tva_deductible, 2),
        "avances_en_cours": avances,
        "pieces_en_attente": en_attente,
    }
