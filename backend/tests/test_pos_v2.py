"""POS v2 — remises, multi-paiements bi-devise, crédit client, retours, rapport.

Chaque test vérifie à la fois le résultat métier (ticket, stock, caisse) ET la
comptabilité générée (balance équilibrée, comptes attendus).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from scripts.seed_demo import seed_demo


@pytest.fixture()
def ctx():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestSession() as s:
        ids = seed_demo(s)

    def _get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    client = TestClient(app)
    yield client, ids
    app.dependency_overrides.clear()


def _login(client, email, pw):
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _headers(client, ids):
    return {role: _login(client, email, ids["password"]) for role, email in ids["users"].items()}


def _pos_setup(client, h, sid, prix_detail=15, stock=100, cump=10):
    """Article CIM50 au tarif détail, stock constitué, caisse du PV ouverte."""
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}",
                                     headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}",
                                       headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")
    pv = client.get(f"/api/commercial/points-vente?societe_id={sid}", headers=h["COMPTABLE"]).json()[0]
    detail = next(l for l in client.get(f"/api/commercial/listes-prix?societe_id={sid}",
                                        headers=h["COMPTABLE"]).json() if l["code"] == "DETAIL")
    client.post(f"/api/commercial/listes-prix/{detail['id']}/tarifs", headers=h["COMPTABLE"],
                json={"article_id": cim["id"], "prix": prix_detail})
    client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"],
        "lignes": [{"article_id": cim["id"], "qte": stock, "prix_unitaire": cump}]})
    client.post(f"/api/caisse/{pv['caisse_id']}/ouvrir", headers=h["CAISSIER_CENTRAL"],
                json={"fond_initial_usd": 50})
    return cim, pv


def _set_taux(client, h, taux=2000):
    r = client.post("/api/taux", headers=h["DFI"], json={
        "date_taux": date.today().isoformat(), "devise": "CDF", "taux_usd": taux})
    assert r.status_code in (200, 201), r.text


def _balance(client, h, sid):
    b = client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert b["equilibre"] is True
    return {l["compte"]: l for l in b["lignes"]}


def test_pos_paiement_fractionne_bidevise(ctx):
    """Règlement mixte : espèces USD + espèces CDF (au taux du jour) + mobile money,
    monnaie rendue sur les espèces, écriture éclatée 5711/522, caisse bi-devise."""
    client, ids = ctx
    h = _headers(client, ids)
    sid = ids["societe_id"]
    cim, pv = _pos_setup(client, h, sid)
    _set_taux(client, h, 2000)

    # 4 × 15 = 60 HT + 9,6 TVA = 69,6 TTC
    # Non-espèces : MM 19,6 → dû en espèces 50 ; reçu : 40 USD + 60 000 FC (30 USD) → monnaie 20
    r = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"],
        "paiements": [
            {"mode": "espece", "devise": "USD", "montant": 40},
            {"mode": "espece", "devise": "CDF", "montant": 60000},
            {"mode": "mobile_money", "devise": "USD", "montant": 19.6, "reference": "MP-778812"},
        ],
        "lignes": [{"article_id": cim["id"], "qte": 4}]})
    assert r.status_code == 201, r.text
    tk = r.json()
    assert tk["total_ttc"] == 69.6
    assert tk["montant_recu"] == 70.0 and tk["monnaie"] == 20.0
    assert len(tk["paiements"]) == 3
    mm = next(p for p in tk["paiements"] if p["mode"] == "mobile_money")
    assert mm["reference"] == "MP-778812"
    cdf = next(p for p in tk["paiements"] if p["devise"] == "CDF")
    assert cdf["montant"] == 60000.0 and cdf["montant_usd"] == 30.0 and cdf["taux"] == 2000.0

    # Comptabilité : caisse POS au net espèces (50), mobile money 522 = 19,6
    bal = _balance(client, h, sid)
    assert bal["5711"]["solde_debiteur"] == 50.0
    assert bal["522"]["solde_debiteur"] == 19.6
    assert bal["701"]["solde_crediteur"] == 60.0

    # Journal de caisse : entrées 40 USD et 60 000 FC, sortie monnaie 20 USD
    jr = client.get(f"/api/caisse/{pv['caisse_id']}/journal", headers=h["CAISSIER_CENTRAL"]).json()
    assert any(m["sens"] == "entree" and m["devise"] == "USD" and m["montant"] == 40.0 for m in jr["mouvements"])
    assert any(m["sens"] == "entree" and m["devise"] == "CDF" and m["montant"] == 60000.0 for m in jr["mouvements"])
    assert any(m["nature"] == "Monnaie rendue POS" and m["sens"] == "sortie"
               and m["devise"] == "USD" and m["montant"] == 20.0 for m in jr["mouvements"])
    assert jr["soldes"]["USD"] == 70.0        # fond 50 + 40 − 20
    assert jr["soldes"].get("CDF", 0) == 60000.0

    # Monnaie impossible sur du non-espèces → refus explicite
    r = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"],
        "paiements": [{"mode": "mobile_money", "devise": "USD", "montant": 100}],
        "lignes": [{"article_id": cim["id"], "qte": 4}]})
    assert r.status_code == 400 and "monnaie" in r.json()["detail"].lower()


def test_pos_cdf_sans_taux_refuse(ctx):
    """Encaissement en CDF sans taux du jour défini → refus clair."""
    client, ids = ctx
    h = _headers(client, ids)
    sid = ids["societe_id"]
    cim, pv = _pos_setup(client, h, sid)
    r = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"],
        "paiements": [{"mode": "espece", "devise": "CDF", "montant": 139200}],
        "lignes": [{"article_id": cim["id"], "qte": 4}]})
    assert r.status_code == 409 and "taux" in r.json()["detail"].lower()


def test_pos_remises_ligne_et_globale(ctx):
    """Remise 10 % sur la ligne + 5 % globale = 14,5 % combinée ; le HT est net,
    la remise totale est tracée sur la facture et dans le rapport."""
    client, ids = ctx
    h = _headers(client, ids)
    sid = ids["societe_id"]
    cim, pv = _pos_setup(client, h, sid)

    # brut 60 ; net = 60 × 0,9 × 0,95 = 51,3 ; TVA 8,21 ; TTC 59,51 ; remise 8,7
    r = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"], "remise_globale_pct": 5,
        "paiements": [{"mode": "espece", "devise": "USD", "montant": 59.51}],
        "lignes": [{"article_id": cim["id"], "qte": 4, "remise_pct": 10}]})
    assert r.status_code == 201, r.text
    tk = r.json()
    assert tk["total_ht"] == 51.3 and tk["total_ttc"] == 59.51
    assert tk["remise_totale"] == 8.7
    assert tk["lignes"][0]["remise_pct"] == 14.5 and tk["lignes"][0]["brut"] == 60.0

    bal = _balance(client, h, sid)
    assert bal["701"]["solde_crediteur"] == 51.3     # CA net de remise
    assert bal["5711"]["solde_debiteur"] == 59.51

    rap = client.get(f"/api/commercial/pos/rapport?societe_id={sid}&point_vente_id={pv['id']}",
                     headers=h["CAISSIER_CENTRAL"]).json()
    assert rap["remises"] == 8.7 and rap["nb_tickets"] == 1


def test_pos_vente_credit_client_et_plafond(ctx):
    """Vente à crédit : client enregistré obligatoire, créance en 411,
    plafond de crédit contrôlé sur l'encours cumulé."""
    client, ids = ctx
    h = _headers(client, ids)
    sid = ids["societe_id"]
    cim, pv = _pos_setup(client, h, sid)

    # Crédit sur client comptant → refus
    r = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"],
        "paiements": [{"mode": "credit", "devise": "USD", "montant": 69.6}],
        "lignes": [{"article_id": cim["id"], "qte": 4}]})
    assert r.status_code == 400

    # Client avec plafond 100 USD — créé depuis le POS (rôle caissier)
    cl = client.post(f"/api/commercial/tiers?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "type": "client", "code": "KABILA-M", "nom": "Marie Kabila", "limite_credit_usd": 100})
    assert cl.status_code == 201, cl.text
    cl = cl.json()

    # 1re vente : mixte 20 espèces + 49,6 à crédit → OK
    r = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"], "client_id": cl["id"],
        "paiements": [{"mode": "espece", "devise": "USD", "montant": 20},
                      {"mode": "credit", "devise": "USD", "montant": 49.6}],
        "lignes": [{"article_id": cim["id"], "qte": 4}]})
    assert r.status_code == 201, r.text

    bal = _balance(client, h, sid)
    assert bal["411"]["solde_debiteur"] == 49.6
    assert bal["5711"]["solde_debiteur"] == 20.0

    # 2e vente : encours 49,6 + 69,6 > 100 → refus
    r = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"], "client_id": cl["id"],
        "paiements": [{"mode": "credit", "devise": "USD", "montant": 69.6}],
        "lignes": [{"article_id": cim["id"], "qte": 4}]})
    assert r.status_code == 409 and "plafond" in r.json()["detail"].lower()


def test_pos_retour_espece_stock_et_ecritures(ctx):
    """Retour partiel : avoir AVV, ré-entrée en stock au coût d'origine, écriture
    inverse (D 701 + D 4431 / C 5711), sortie de caisse, garde-fou quantités."""
    client, ids = ctx
    h = _headers(client, ids)
    sid = ids["societe_id"]
    cim, pv = _pos_setup(client, h, sid)

    tk = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"], "montant_recu": 69.6,
        "lignes": [{"article_id": cim["id"], "qte": 4}]}).json()

    # Retour de 2 unités en espèces
    r = client.post(f"/api/commercial/pos/retour?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "facture_id": tk["id"], "mode": "espece", "motif": "Sacs déchirés",
        "lignes": [{"ligne_id": tk["lignes"][0]["id"], "qte": 2}]})
    assert r.status_code == 201, r.text
    av = r.json()
    assert av["numero"].startswith("AVV-") and av["est_avoir"] is True
    assert av["total_ttc"] == 34.8 and av["origine_numero"] == tk["numero"]

    # Stock revenu à 98, valorisé au coût d'origine (CUMP 10)
    s = next(l for l in client.get(f"/api/commercial/stock?societe_id={sid}",
                                   headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s["stock_qte"] == 98.0 and s["stock_valeur"] == 980.0

    # Comptabilité : 701 net 30, TVA nette 4,8, caisse nette 34,8
    bal = _balance(client, h, sid)
    assert round(bal["701"]["solde_crediteur"] - bal["701"]["solde_debiteur"], 2) == 30.0
    assert round(bal["4431"]["solde_crediteur"] - bal["4431"]["solde_debiteur"], 2) == 4.8
    assert round(bal["5711"]["solde_debiteur"] - bal["5711"]["solde_crediteur"], 2) == 34.8

    # Sortie de caisse tracée
    jr = client.get(f"/api/caisse/{pv['caisse_id']}/journal", headers=h["CAISSIER_CENTRAL"]).json()
    assert any(m["nature"] == "Retour POS" and m["montant"] == 34.8 for m in jr["mouvements"])

    # Le détail expose le déjà-retourné ; sur-retour → 409
    det = client.get(f"/api/commercial/pos/ticket/{tk['id']}", headers=h["CAISSIER_CENTRAL"]).json()
    assert det["lignes"][0]["deja_retourne"] == 2.0
    r = client.post(f"/api/commercial/pos/retour?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "facture_id": tk["id"], "mode": "espece",
        "lignes": [{"ligne_id": tk["lignes"][0]["id"], "qte": 3}]})
    assert r.status_code == 409

    # La synthèse commerciale déduit l'avoir (CA net 30)
    syn = client.get(f"/api/commercial/ventes-synthese?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert syn["chiffre_affaires"] == 30.0


def test_pos_fidelite_et_tickets_du_jour(ctx):
    """Fidélité : les points s'accumulent sur le client (et se reprennent au retour) ;
    la liste des tickets du jour trace ventes, avoirs et modes de règlement."""
    client, ids = ctx
    h = _headers(client, ids)
    sid = ids["societe_id"]
    cim, pv = _pos_setup(client, h, sid)
    client.patch(f"/api/commercial/articles/{cim['id']}", headers=h["COMPTABLE"],
                 json={"points_fidelite": 2})

    cl = client.post(f"/api/commercial/tiers?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "type": "client", "code": "ILUNGA-J", "nom": "Jean Ilunga"}).json()

    tk = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"], "client_id": cl["id"], "montant_recu": 69.6,
        "lignes": [{"article_id": cim["id"], "qte": 4}]}).json()
    assert tk["client"]["points_fidelite"] == 8.0       # 4 × 2, cumul après vente

    client.post(f"/api/commercial/pos/retour?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "facture_id": tk["id"], "mode": "espece",
        "lignes": [{"ligne_id": tk["lignes"][0]["id"], "qte": 1}]})
    clients = client.get(f"/api/commercial/tiers?societe_id={sid}&type=client",
                         headers=h["CAISSIER_CENTRAL"]).json()
    assert next(c for c in clients if c["code"] == "ILUNGA-J")["points_fidelite"] == 6.0

    tks = client.get(f"/api/commercial/pos/tickets?societe_id={sid}&point_vente_id={pv['id']}",
                     headers=h["CAISSIER_CENTRAL"]).json()
    assert len(tks) == 2
    vente = next(t for t in tks if t["type"] == "vente")
    avoir = next(t for t in tks if t["type"] == "avoir_vente")
    assert vente["client"] == "Jean Ilunga" and vente["avoirs"] == [avoir["numero"]]
    assert "espece" in vente["modes"]


def test_pos_rapport_du_jour(ctx):
    """Rapport « X » : CA, retours, net, encaissements par mode, palmarès."""
    client, ids = ctx
    h = _headers(client, ids)
    sid = ids["societe_id"]
    cim, pv = _pos_setup(client, h, sid)
    _set_taux(client, h, 2000)

    client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"], "montant_recu": 69.6,
        "lignes": [{"article_id": cim["id"], "qte": 4}]})
    tk2 = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"],
        "paiements": [{"mode": "espece", "devise": "USD", "montant": 17.4},
                      {"mode": "mobile_money", "devise": "USD", "montant": 17.4}],
        "lignes": [{"article_id": cim["id"], "qte": 2}]}).json()
    client.post(f"/api/commercial/pos/retour?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "facture_id": tk2["id"], "mode": "espece",
        "lignes": [{"ligne_id": tk2["lignes"][0]["id"], "qte": 1}]})

    r = client.get(f"/api/commercial/pos/rapport?societe_id={sid}&point_vente_id={pv['id']}",
                   headers=h["CAISSIER_CENTRAL"]).json()
    assert r["nb_tickets"] == 2 and r["nb_retours"] == 1
    assert r["ttc"] == 104.4                      # 69,6 + 34,8
    assert r["retours_ttc"] == 17.4 and r["net_ttc"] == 87.0
    assert r["net_ttc_cdf"] == 174000.0
    assert r["par_mode"]["mobile_money"]["usd"] == 17.4
    # espèces : 69,6 + 17,4 − retour 17,4 = 69,6
    assert r["par_mode"]["espece"]["usd"] == 69.6
    assert r["palmares"][0]["qte"] == 5.0         # 4 + 2 − 1
    assert r["panier_moyen"] == 52.2
