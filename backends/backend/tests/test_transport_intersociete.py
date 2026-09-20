"""Intersociétés & Transport — facture miroir, règlement double-face,
cycle de course (PROC-KL-01→04), sous-traitance, maintenance bloquante.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
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
        # Deuxième société du groupe : KAKO Logistique, mêmes utilisateurs
        from app.plan_comptable import charger_plan
        kkl = models.Societe(code="KKL", nom="KAKO Logistique", ville="Likasi")
        s.add(kkl)
        s.flush()
        charger_plan(s, kkl.id)
        roles = {r.code: r for r in s.execute(select(models.Role)).scalars()}
        for u in s.execute(select(models.Utilisateur)).scalars():
            deja = {(a.role_id) for a in s.execute(select(models.UtilisateurSociete).where(
                models.UtilisateurSociete.utilisateur_id == u.id)).scalars()}
            for rid in deja:
                s.add(models.UtilisateurSociete(utilisateur_id=u.id, societe_id=kkl.id, role_id=rid))
        ids["kkl_id"] = str(kkl.id)
        s.commit()

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


def _balance(client, h, sid):
    b = client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert b["equilibre"] is True, b
    return {l["compte"]: l for l in b["lignes"]}


def test_miroir_intersociete_et_reglement_double_face(ctx):
    """PLANET vend 10 sacs à KAKO Logistique : facture d'achat miroir + stock
    entré chez KKL, positions réconciliées, règlement réel des deux côtés."""
    client, ids = ctx
    h = _headers(client, ids)
    pla, kkl = ids["societe_id"], ids["kkl_id"]

    # Stock chez PLANET (100 @ 10) et article homonyme chez KKL
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={pla}",
                                     headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={pla}",
                                       headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")
    client.post(f"/api/commercial/factures?societe_id={pla}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"],
        "lignes": [{"article_id": cim["id"], "qte": 100, "prix_unitaire": 10}]})
    client.post(f"/api/commercial/articles?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "code": "CIM50", "designation": "Ciment gris 50 kg", "prix_achat": 15, "prix_vente": 18})

    # Client « KAKO Logistique » chez PLANET, lié à la société KKL
    cl = client.post(f"/api/commercial/tiers?societe_id={pla}", headers=h["COMPTABLE"], json={
        "type": "client", "code": "KKL", "nom": "KAKO Logistique"}).json()
    r = client.post("/api/intersociete/lier", headers=h["DFI"], json={
        "tiers_id": cl["id"], "societe_liee_id": kkl})
    assert r.status_code == 200, r.text

    # Vente PLANET → KKL : 10 × 15 = 150 HT + 24 TVA = 174 TTC
    r = client.post(f"/api/commercial/factures?societe_id={pla}", headers=h["COMPTABLE"], json={
        "type": "vente", "tiers_id": cl["id"],
        "lignes": [{"article_id": cim["id"], "qte": 10, "prix_unitaire": 15}]})
    assert r.status_code == 201, r.text

    # Miroir chez KKL : facture d'achat en attente de revue + stock entré
    inter = client.get("/api/intersociete/factures", headers=h["DFI"]).json()
    assert len(inter) == 1
    f = inter[0]
    assert f["vendeur"] == "PLANET Sarl" and f["acheteur"] == "KAKO Logistique"
    assert f["total_ttc"] == 174.0 and f["miroir_numero"].startswith("FA-KKL-")
    s_kkl = next(l for l in client.get(f"/api/commercial/stock?societe_id={kkl}",
                                       headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s_kkl["stock_qte"] == 10.0 and s_kkl["stock_valeur"] == 150.0

    # Positions réconciliées : PLANET → KKL 174, écart nul
    pos = client.get("/api/intersociete/positions", headers=h["DFI"]).json()
    p = next(x for x in pos if x["creancier"] == "PLANET Sarl")
    assert p["debiteur"] == "KAKO Logistique"
    assert p["montant_usd"] == 174.0 and p["miroir_usd"] == 174.0 and p["ecart_usd"] == 0.0

    # Règlement réel double-face (banque des deux côtés)
    r = client.post(f"/api/intersociete/factures/{f['id']}/regler", headers=h["DFI"], json={
        "vendeur_mode": "banque", "acheteur_mode": "banque", "reference": "VIR-GROUPE-001"})
    assert r.status_code == 201, r.text
    assert r.json()["statut_reglement"] == "payee"

    bal_pla = _balance(client, h, pla)
    bal_kkl = _balance(client, h, kkl)
    assert bal_pla["521"]["solde_debiteur"] == 174.0                       # PLANET encaisse
    assert round(bal_pla["411"]["solde_debiteur"] - bal_pla["411"]["solde_crediteur"], 2) == 0.0
    assert round(bal_kkl["521"]["solde_crediteur"] - bal_kkl["521"]["solde_debiteur"], 2) == 174.0
    assert round(bal_kkl["401"]["solde_crediteur"] - bal_kkl["401"]["solde_debiteur"], 2) == 0.0
    # positions soldées
    pos = client.get("/api/intersociete/positions", headers=h["DFI"]).json()
    assert not any(x["creancier"] == "PLANET Sarl" and abs(x["montant_usd"]) > 0.01 for x in pos)


def test_cycle_course_et_sous_traitance(ctx):
    """Deux courses chez KAKO Logistique : une propre facturée à un client
    externe (706), une sous-traitée à 70 % — dette 401 du propriétaire, marges."""
    client, ids = ctx
    h = _headers(client, ids)
    kkl = ids["kkl_id"]

    prop = client.post(f"/api/commercial/tiers?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "type": "fournisseur", "code": "MUKENDI", "nom": "Transports Mukendi"}).json()
    ext = client.post(f"/api/commercial/tiers?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "type": "client", "code": "MINIERE-X", "nom": "Société Minière X"}).json()

    cam1 = client.post(f"/api/transport/camions?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "immatriculation": "9412 AB 05", "marque": "Howo", "capacite_tonnes": 30}).json()
    cam2 = client.post(f"/api/transport/camions?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "immatriculation": "7001 CD 05", "type": "sous_traite", "capacite_tonnes": 30,
        "proprietaire_tiers_id": prop["id"],
        "remuneration_mode": "pourcentage", "remuneration_valeur": 70}).json()
    chf = client.post(f"/api/transport/chauffeurs?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "nom": "Papy Kalenga"}).json()

    # ── Course 1 : camion propre, 20 $/t, 30 t prévu / 28 t livré
    r = client.post(f"/api/transport/courses?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "client_tiers_id": ext["id"], "camion_id": cam1["id"], "chauffeur_id": chf["id"],
        "origine": "Likasi", "destination": "Kolwezi", "marchandise": "Ciment 42.5",
        "tonnage_prevu": 30, "tarif_mode": "tonne", "prix_unitaire": 20})
    assert r.status_code == 201, r.text
    c1 = r.json()
    # Départ sans validation DFI → refus ; validation par un non-DFI → refus
    assert client.post(f"/api/transport/courses/{c1['id']}/depart", headers=h["COMPTABLE"]).status_code == 409
    assert client.post(f"/api/transport/courses/{c1['id']}/valider", headers=h["COMPTABLE"]).status_code == 403
    client.post(f"/api/transport/courses/{c1['id']}/valider", headers=h["DFI"])
    r = client.post(f"/api/transport/courses/{c1['id']}/depart", headers=h["COMPTABLE"])
    assert r.json()["statut"] == "en_cours"
    # Le camion est occupé : une autre course ne peut pas partir avec lui
    c1b = client.post(f"/api/transport/courses?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "client_tiers_id": ext["id"], "camion_id": cam1["id"],
        "origine": "Likasi", "destination": "Lubumbashi", "marchandise": "Divers",
        "tonnage_prevu": 10, "tarif_mode": "voyage", "prix_unitaire": 400}).json()
    client.post(f"/api/transport/courses/{c1b['id']}/valider", headers=h["DFI"])
    assert client.post(f"/api/transport/courses/{c1b['id']}/depart", headers=h["COMPTABLE"]).status_code == 409

    r = client.post(f"/api/transport/courses/{c1['id']}/retour", headers=h["COMPTABLE"], json={
        "tonnage_livre": 28, "incidents": "RAS"})
    assert r.status_code == 200, r.text
    c1 = r.json()
    assert c1["statut"] == "livree" and c1["recette_usd"] == 560.0    # 28 × 20
    assert c1["marge_usd"] == 560.0                                   # pas de frais liés

    # ── Course 2 : camion sous-traité au pourcentage (70 % de 800 = 560)
    c2 = client.post(f"/api/transport/courses?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "client_tiers_id": ext["id"], "camion_id": cam2["id"],
        "origine": "Likasi", "destination": "Kolwezi", "marchandise": "Chaux",
        "tonnage_prevu": 30, "tarif_mode": "voyage", "prix_unitaire": 800}).json()
    client.post(f"/api/transport/courses/{c2['id']}/valider", headers=h["DFI"])
    client.post(f"/api/transport/courses/{c2['id']}/depart", headers=h["COMPTABLE"])
    r = client.post(f"/api/transport/courses/{c2['id']}/retour", headers=h["COMPTABLE"], json={
        "tonnage_livre": 30})
    c2 = r.json()
    assert c2["st_cout_usd"] == 560.0 and c2["st_facture"].startswith("FA-KKL-")
    assert c2["marge_usd"] == 240.0                                   # 800 − 560

    bal = _balance(client, h, kkl)
    assert bal["612"]["solde_debiteur"] == 560.0                      # sous-traitance
    assert round(bal["401"]["solde_crediteur"] - bal["401"]["solde_debiteur"], 2) == 560.0

    # ── Facturation groupée des deux courses (même client externe)
    r = client.post(f"/api/transport/facturer?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "course_ids": [c1["id"], c2["id"]]})
    assert r.status_code == 201, r.text
    fac = r.json()["facture"]
    # 560 + 800 = 1360 HT + 217,6 TVA = 1577,6 TTC
    assert fac["total_ttc"] == 1577.6 and fac["intra_groupe"] is False
    bal = _balance(client, h, kkl)
    assert bal["706"]["solde_crediteur"] == 1360.0
    assert bal["411"]["solde_debiteur"] == 1577.6

    # Rentabilité
    rap = client.get(f"/api/transport/rapport?societe_id={kkl}", headers=h["COMPTABLE"]).json()
    assert rap["total"]["courses"] == 2 and rap["total"]["recettes"] == 1360.0
    assert rap["total"]["sous_traitance"] == 560.0 and rap["total"]["marge"] == 800.0
    st_row = next(x for x in rap["par_camion"] if x["camion"] == "7001 CD 05")
    assert st_row["marge"] == 240.0


def test_transport_gardes_fous_et_maintenance(ctx):
    """Avance carburant non décaissée → départ bloqué ; camion immobilisé →
    inaffectable ; remise en service → disponible (PROC-KL-01/02/05/06)."""
    client, ids = ctx
    h = _headers(client, ids)
    kkl = ids["kkl_id"]
    ext = client.post(f"/api/commercial/tiers?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "type": "client", "code": "CLIENT-Y", "nom": "Client Y"}).json()
    cam = client.post(f"/api/transport/camions?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "immatriculation": "1200 EF 05", "capacite_tonnes": 25}).json()

    # Réquisition carburant liée mais non décaissée → départ refusé
    req = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": kkl, "objet": "Carburant course Likasi-Kolwezi", "devise": "USD",
        "lignes": [{"description": "Gasoil 400 L", "quantite": 1, "prix_unitaire": 520}]}).json()
    c = client.post(f"/api/transport/courses?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "client_tiers_id": ext["id"], "camion_id": cam["id"],
        "origine": "Likasi", "destination": "Kolwezi", "marchandise": "Ciment",
        "tonnage_prevu": 25, "tarif_mode": "tonne", "prix_unitaire": 20,
        "requisition_id": req["id"]}).json()
    client.post(f"/api/transport/courses/{c['id']}/valider", headers=h["DFI"])
    r = client.post(f"/api/transport/courses/{c['id']}/depart", headers=h["COMPTABLE"])
    assert r.status_code == 409 and "avance" in r.json()["detail"].lower()

    # Panne immobilisante → le camion devient inaffectable
    iv = client.post(f"/api/transport/interventions?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "camion_id": cam["id"], "type": "reparation", "description": "Boîte de vitesses HS",
        "cout_estime": 900, "immobilise": True}).json()
    cams = client.get(f"/api/transport/camions?societe_id={kkl}", headers=h["COMPTABLE"]).json()
    assert next(x for x in cams if x["id"] == cam["id"])["statut"] == "immobilise"
    c2 = client.post(f"/api/transport/courses?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "client_tiers_id": ext["id"], "camion_id": cam["id"],
        "origine": "Likasi", "destination": "Kolwezi", "marchandise": "Divers",
        "tonnage_prevu": 10, "tarif_mode": "voyage", "prix_unitaire": 300}).json()
    client.post(f"/api/transport/courses/{c2['id']}/valider", headers=h["DFI"])
    r = client.post(f"/api/transport/courses/{c2['id']}/depart", headers=h["COMPTABLE"])
    assert r.status_code == 409 and "immobilis" in r.json()["detail"].lower()

    # Remise en service → disponible, coût réel tracé
    client.post(f"/api/transport/interventions/{iv['id']}/terminer", headers=h["COMPTABLE"],
                json={"cout_reel": 850})
    cams = client.get(f"/api/transport/camions?societe_id={kkl}", headers=h["COMPTABLE"]).json()
    assert next(x for x in cams if x["id"] == cam["id"])["statut"] == "disponible"
    ivs = client.get(f"/api/transport/interventions?societe_id={kkl}", headers=h["COMPTABLE"]).json()
    assert ivs[0]["statut"] == "terminee" and ivs[0]["cout_reel"] == 850.0


def test_facturation_course_interne_miroir(ctx):
    """KAKO Logistique facture une course à une société du groupe : la facture
    d'achat miroir apparaît chez elle (charge transport à reclasser en revue)."""
    client, ids = ctx
    h = _headers(client, ids)
    pla, kkl = ids["societe_id"], ids["kkl_id"]
    # client « PLANET » chez KKL, lié à la société PLANET
    cli = client.post(f"/api/commercial/tiers?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "type": "client", "code": "PLA", "nom": "PLANET Sarl"}).json()
    client.post("/api/intersociete/lier", headers=h["DFI"], json={
        "tiers_id": cli["id"], "societe_liee_id": pla})
    cam = client.post(f"/api/transport/camions?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "immatriculation": "3305 GH 05", "capacite_tonnes": 30}).json()
    c = client.post(f"/api/transport/courses?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "client_tiers_id": cli["id"], "camion_id": cam["id"],
        "origine": "Likasi", "destination": "Kolwezi", "marchandise": "Chaux GCK",
        "tonnage_prevu": 30, "tarif_mode": "voyage", "prix_unitaire": 700}).json()
    client.post(f"/api/transport/courses/{c['id']}/valider", headers=h["DFI"])
    client.post(f"/api/transport/courses/{c['id']}/depart", headers=h["COMPTABLE"])
    client.post(f"/api/transport/courses/{c['id']}/retour", headers=h["COMPTABLE"],
                json={"tonnage_livre": 30})
    r = client.post(f"/api/transport/facturer?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "course_ids": [c["id"]]})
    assert r.status_code == 201, r.text
    assert r.json()["facture"]["intra_groupe"] is True

    inter = client.get("/api/intersociete/factures", headers=h["DFI"]).json()
    f = next(x for x in inter if x["vendeur"] == "KAKO Logistique")
    assert f["acheteur"] == "PLANET Sarl" and f["miroir_numero"].startswith("FA-PLA-")
    # 700 HT + 112 TVA = 812 TTC — la dette apparaît chez PLANET
    achats_pla = client.get(f"/api/commercial/factures?societe_id={pla}&type=achat",
                            headers=h["COMPTABLE"]).json()
    miroir = next(x for x in achats_pla if x["numero"] == f["miroir_numero"])
    assert miroir["total_ttc"] == 812.0
