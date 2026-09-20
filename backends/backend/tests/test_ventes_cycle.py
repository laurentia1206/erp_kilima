"""Module Ventes — devis → commande → livraisons partielles → factures → règlements.

Chaque étape est vérifiée côté métier (statuts, stock, quantités) ET côté
comptabilité (écritures, 411, balance équilibrée).
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


def _setup(client, h, sid):
    """Client, article en stock (100 @ 10) et caisse principale ouverte."""
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}",
                                     headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}",
                                       headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")
    client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"],
        "lignes": [{"article_id": cim["id"], "qte": 100, "prix_unitaire": 10}]})
    cl = client.post(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "client", "code": "MUTOMBO-SA", "nom": "Ets Mutombo & Fils"}).json()
    return cim, cl


def _balance(client, h, sid):
    b = client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert b["equilibre"] is True
    return {l["compte"]: l for l in b["lignes"]}


def test_cycle_complet_devis_a_reglement(ctx):
    """Devis (remises) → envoi → confirmation → 2 livraisons partielles →
    2 factures → règlements fractionnés → créance soldée."""
    client, ids = ctx
    h = _headers(client, ids)
    sid = ids["societe_id"]
    cim, cl = _setup(client, h, sid)

    # ── Devis : 10 sacs @ 15, remise ligne 10 % + globale 5 % + une ligne service
    r = client.post(f"/api/ventes/devis?societe_id={sid}", headers=h["COMPTABLE"], json={
        "tiers_id": cl["id"], "validite": "2099-12-31", "remise_globale_pct": 5,
        "conditions": "Paiement à 30 jours",
        "lignes": [
            {"article_id": cim["id"], "qte": 10, "remise_pct": 10},           # prix défaut article
            {"designation": "Transport sur site", "qte": 1, "prix_unitaire": 40, "taux_tva": 16},
        ]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["numero"].startswith("DEV-") and d["statut"] == "brouillon"
    # 10 × 14 = 140 → ×0,9×0,95 = 119,70 ; transport 40 → ×0,95 = 38 ; HT 157,70
    assert d["total_ht"] == 157.7
    assert d["remise_totale"] == 22.3
    lg_cim = next(l for l in d["lignes"] if l["article"])
    lg_srv = next(l for l in d["lignes"] if not l["article"])

    # Modification en brouillon : OK ; le devis n'a AUCUN impact stock/compta
    r = client.put(f"/api/ventes/devis/{d['id']}", headers=h["COMPTABLE"], json={
        "tiers_id": cl["id"], "validite": "2099-12-31", "remise_globale_pct": 5,
        "conditions": "Paiement à 30 jours",
        "lignes": [
            {"article_id": cim["id"], "qte": 10, "remise_pct": 10},
            {"designation": "Transport sur site", "qte": 2, "prix_unitaire": 40, "taux_tva": 16},
        ]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total_ht"] == 195.7          # transport ×2 : 119,70 + 76
    s = next(l for l in client.get(f"/api/commercial/stock?societe_id={sid}",
                                   headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s["stock_qte"] == 100.0         # rien n'a bougé

    # ── Envoi puis confirmation (devis → commande client)
    assert client.post(f"/api/ventes/devis/{d['id']}/envoyer", headers=h["COMPTABLE"]).json()["statut"] == "envoye"
    d = client.post(f"/api/ventes/devis/{d['id']}/confirmer", headers=h["COMPTABLE"]).json()
    assert d["statut"] == "confirme" and d["statut_livraison"] == "a_livrer"

    # Modifier une commande confirmée → refus
    assert client.put(f"/api/ventes/devis/{d['id']}", headers=h["COMPTABLE"], json={
        "tiers_id": cl["id"], "lignes": [{"article_id": cim["id"], "qte": 1}]}).status_code == 409

    # ── Livraison partielle 1 : 6 sacs (sortie stock au CUMP 10)
    lg_cim = next(l for l in d["lignes"] if l["article"])
    r = client.post(f"/api/ventes/devis/{d['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg_cim["id"], "qte": 6}], "note": "Camion KLZ-042"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["statut_livraison"] == "partielle"
    assert d["livraisons"][0]["numero"].startswith("BL-")
    s = next(l for l in client.get(f"/api/commercial/stock?societe_id={sid}",
                                   headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s["stock_qte"] == 94.0
    # Sur-livraison → refus
    assert client.post(f"/api/ventes/devis/{d['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg_cim["id"], "qte": 5}]}).status_code == 409

    # ── Facture 1 : 6 sacs livrés + les 2 transports (ligne service)
    r = client.post(f"/api/ventes/devis/{d['id']}/facturer", headers=h["COMPTABLE"],
                    json={"echeance": "2099-01-31"})
    assert r.status_code == 201, r.text
    fac1 = r.json()["facture"]
    d = r.json()["devis"]
    # 6/10 × 119,70 = 71,82 + 76 (transport) = 147,82 HT ; TVA 23,65 ; TTC 171,47
    assert fac1["total_ttc"] == 171.47
    # Refacturer sans nouvelle livraison → refus
    assert client.post(f"/api/ventes/devis/{d['id']}/facturer", headers=h["COMPTABLE"]).status_code == 409

    # 411 débité du TTC, balance OK
    bal = _balance(client, h, sid)
    assert bal["411"]["solde_debiteur"] == 171.47
    # stock 31 : 1 000 (achat) − 60 (livraison 6 × CUMP 10) = 940
    assert bal["31"]["solde_debiteur"] == 940.0

    # ── Règlement 1 : 100 $ en espèces (caisse centrale ouverte)
    client.post(f"/api/caisse/{ids['caisse_id']}/ouvrir", headers=h["CAISSIER_CENTRAL"],
                json={"fond_initial_usd": 0})
    r = client.post(f"/api/ventes/factures/{fac1['id']}/regler", headers=h["COMPTABLE"], json={
        "mode": "espece", "devise": "USD", "montant": 100, "caisse_id": ids["caisse_id"]})
    assert r.status_code == 201, r.text
    assert r.json()["statut_reglement"] == "partielle" and r.json()["solde_du_usd"] == 71.47

    # ── Règlement 2 : solde par banque → facture payée, 411 apuré à hauteur du TTC
    r = client.post(f"/api/ventes/factures/{fac1['id']}/regler", headers=h["COMPTABLE"], json={
        "mode": "banque", "devise": "USD", "montant": 71.47, "reference": "VIR-2026-0117"})
    assert r.json()["statut_reglement"] == "payee"
    # Sur-règlement → refus
    assert client.post(f"/api/ventes/factures/{fac1['id']}/regler", headers=h["COMPTABLE"], json={
        "mode": "banque", "devise": "USD", "montant": 5}).status_code == 409

    bal = _balance(client, h, sid)
    assert round(bal["411"]["solde_debiteur"] - bal["411"]["solde_crediteur"], 2) == 0.0
    assert bal["571"]["solde_debiteur"] == 100.0
    assert bal["521"]["solde_debiteur"] == 71.47

    # ── Livraison 2 (solde 4 sacs) puis facture 2, encours client à jour
    r = client.post(f"/api/ventes/devis/{d['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg_cim["id"], "qte": 4}]})
    d = r.json()
    assert d["statut_livraison"] == "livree"
    fac2 = client.post(f"/api/ventes/devis/{d['id']}/facturer", headers=h["COMPTABLE"]).json()["facture"]
    # 4/10 × 119,70 = 47,88 HT ; TVA 7,66 ; TTC 55,54
    assert fac2["total_ttc"] == 55.54

    enc = client.get(f"/api/ventes/encours?societe_id={sid}", headers=h["COMPTABLE"]).json()
    ligne = next(e for e in enc if e["client"] == "Ets Mutombo & Fils")
    assert ligne["solde_usd"] == 55.54
    assert [f["numero"] for f in ligne["factures_dues"]] == [fac2["numero"]]


def test_devis_workflow_gardes_fous(ctx):
    """Statuts verrouillés : livraison avant confirmation refusée, annulation
    impossible après livraison, ligne service non livrable, stock insuffisant."""
    client, ids = ctx
    h = _headers(client, ids)
    sid = ids["societe_id"]
    cim, cl = _setup(client, h, sid)

    d = client.post(f"/api/ventes/devis?societe_id={sid}", headers=h["COMPTABLE"], json={
        "tiers_id": cl["id"],
        "lignes": [{"article_id": cim["id"], "qte": 150},
                   {"designation": "Main d'œuvre", "qte": 1, "prix_unitaire": 25}]}).json()
    lg_cim = next(l for l in d["lignes"] if l["article"])
    lg_srv = next(l for l in d["lignes"] if not l["article"])

    # Livrer un brouillon → refus
    assert client.post(f"/api/ventes/devis/{d['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg_cim["id"], "qte": 1}]}).status_code == 409
    client.post(f"/api/ventes/devis/{d['id']}/confirmer", headers=h["COMPTABLE"])

    # Stock insuffisant (150 > 100) → refus
    assert client.post(f"/api/ventes/devis/{d['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg_cim["id"], "qte": 150}]}).status_code == 409
    # Ligne service non livrable → refus explicite
    assert client.post(f"/api/ventes/devis/{d['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg_srv["id"], "qte": 1}]}).status_code == 400

    # Après une livraison réelle, l'annulation est verrouillée
    client.post(f"/api/ventes/devis/{d['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg_cim["id"], "qte": 10}]})
    assert client.post(f"/api/ventes/devis/{d['id']}/annuler", headers=h["COMPTABLE"]).status_code == 409

    # Un devis vierge, lui, s'annule
    d2 = client.post(f"/api/ventes/devis?societe_id={sid}", headers=h["COMPTABLE"], json={
        "tiers_id": cl["id"], "lignes": [{"article_id": cim["id"], "qte": 1}]}).json()
    assert client.post(f"/api/ventes/devis/{d2['id']}/annuler",
                       headers=h["COMPTABLE"]).json()["statut"] == "annule"


def test_reglement_cdf_au_taux_du_jour(ctx):
    """Règlement client en francs congolais converti au taux du jour."""
    client, ids = ctx
    h = _headers(client, ids)
    sid = ids["societe_id"]
    cim, cl = _setup(client, h, sid)
    client.post("/api/taux", headers=h["DFI"], json={
        "date_taux": date.today().isoformat(), "devise": "CDF", "taux_usd": 2000})

    d = client.post(f"/api/ventes/devis?societe_id={sid}", headers=h["COMPTABLE"], json={
        "tiers_id": cl["id"], "lignes": [{"article_id": cim["id"], "qte": 5}]}).json()
    client.post(f"/api/ventes/devis/{d['id']}/confirmer", headers=h["COMPTABLE"])
    lg = d["lignes"][0]
    client.post(f"/api/ventes/devis/{d['id']}/livrer", headers=h["COMPTABLE"],
                json={"lignes": [{"ligne_id": lg["id"], "qte": 5}]})
    fac = client.post(f"/api/ventes/devis/{d['id']}/facturer", headers=h["COMPTABLE"]).json()["facture"]
    # 5 × 14 = 70 HT + 11,2 TVA = 81,2 TTC

    client.post(f"/api/caisse/{ids['caisse_id']}/ouvrir", headers=h["CAISSIER_CENTRAL"],
                json={"fond_initial_usd": 0})
    r = client.post(f"/api/ventes/factures/{fac['id']}/regler", headers=h["COMPTABLE"], json={
        "mode": "espece", "devise": "CDF", "montant": 100000, "caisse_id": ids["caisse_id"]})
    assert r.status_code == 201, r.text
    assert r.json()["regle_usd"] == 50.0 and r.json()["solde_du_usd"] == 31.2

    jr = client.get(f"/api/caisse/{ids['caisse_id']}/journal", headers=h["CAISSIER_CENTRAL"]).json()
    assert any(m["nature"] == "Encaissement client" and m["devise"] == "CDF"
               and m["montant"] == 100000.0 for m in jr["mouvements"])
