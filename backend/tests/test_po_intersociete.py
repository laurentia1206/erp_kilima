"""Flux PO intersociété (schéma de Laurent) & réquisitions multiples par course.

PO acheteur → commande client en attente chez le vendeur → demande de course
chez le transporteur (bloquée avant confirmation) → livraison / facturation →
PO soldée, stock entré par le miroir, réception manuelle interdite.
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
        from app.plan_comptable import charger_plan
        kkl = models.Societe(code="KKL", nom="KAKO Logistique", ville="Likasi")
        s.add(kkl)
        s.flush()
        charger_plan(s, kkl.id)
        for u in s.execute(select(models.Utilisateur)).scalars():
            deja = {a.role_id for a in s.execute(select(models.UtilisateurSociete).where(
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


def test_flux_po_intersociete_complet(ctx):
    """PO KKL→PLA avec transporteur : miroir vendeur, demande de course bloquée
    puis prenable après confirmation, livraison → stock acheteur + PO soldée."""
    client, ids = ctx
    h = _headers(client, ids)
    pla, kkl = ids["societe_id"], ids["kkl_id"]    # PLA = vendeur (joue DAKAM), KKL = acheteur

    # Acheteur : article homonyme + fournisseur lié à PLA
    client.post(f"/api/commercial/articles?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "code": "CIM50", "designation": "Ciment gris 50 kg", "prix_achat": 14, "prix_vente": 17})
    fourn = client.post(f"/api/commercial/tiers?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "type": "fournisseur", "code": "PLA", "nom": "PLANET Sarl"}).json()
    client.post("/api/intersociete/lier", headers=h["DFI"], json={
        "tiers_id": fourn["id"], "societe_liee_id": pla})
    # Vendeur : stock 100 @ 10
    cim_pla = next(a for a in client.get(f"/api/commercial/articles?societe_id={pla}",
                                         headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    f_pla = next(t for t in client.get(f"/api/commercial/tiers?societe_id={pla}",
                                       headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")
    client.post(f"/api/commercial/factures?societe_id={pla}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": f_pla["id"],
        "lignes": [{"article_id": cim_pla["id"], "qte": 100, "prix_unitaire": 10}]})
    cim_kkl = next(a for a in client.get(f"/api/commercial/articles?societe_id={kkl}",
                                         headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")

    # ── PO n°1 sans transporteur valable (soi-même → ignoré) : miroir seul
    r = client.post(f"/api/commercial/commandes?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "destination": "Dépôt Kolwezi",
        "transporteur_societe_id": kkl,
        "lignes": [{"article_id": cim_kkl["id"], "qte": 20, "prix_unitaire": 14}]})
    assert r.status_code == 201, r.text
    cmd = r.json()
    assert cmd["intersociete"]["etat"] == "en_attente"
    assert cmd["intersociete"]["devis_numero"].startswith("DEV-PLA-")
    assert cmd["intersociete"]["course_numero"] is None

    devis_pla = client.get(f"/api/ventes/devis?societe_id={pla}", headers=h["COMPTABLE"]).json()
    dv = next(d for d in devis_pla if d["numero"] == cmd["intersociete"]["devis_numero"])
    assert dv["statut"] == "envoye" and dv["total_ht"] == 280.0
    assert dv["commande_origine"] == cmd["numero"]

    # Réception manuelle interdite sur PO intersociété
    lg = client.get(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"]).json()["lignes"][0]
    r = client.post(f"/api/commercial/commandes/{cmd['id']}/receptionner", headers=h["COMPTABLE"], json={
        "repartition": "quantite",
        "lignes": [{"ligne_commande_id": lg["id"], "qte_recue": 20}], "frais": []})
    assert r.status_code == 409 and "miroir" in r.json()["detail"].lower()

    # ── PO n°2 avec transporteur = PLA : demande de course créée chez lui
    cmd2 = client.post(f"/api/commercial/commandes?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "destination": "Dépôt Likasi",
        "transporteur_societe_id": pla,
        "lignes": [{"article_id": cim_kkl["id"], "qte": 10, "prix_unitaire": 14}]}).json()
    assert cmd2["intersociete"]["course_numero"].startswith("FC-PLA-")
    dem = next(c for c in client.get(f"/api/transport/courses?societe_id={pla}&statut=demande",
                                     headers=h["COMPTABLE"]).json()
               if c["numero"] == cmd2["intersociete"]["course_numero"])
    assert dem["deblocable"] is False and dem["commande_origine"] == cmd2["numero"]
    assert dem["destination"] == "Dépôt Likasi"

    # Prise en charge AVANT confirmation du vendeur → refus explicite
    cam = client.post(f"/api/transport/camions?societe_id={pla}", headers=h["COMPTABLE"], json={
        "immatriculation": "5555 ZZ 05", "capacite_tonnes": 30}).json()
    r = client.post(f"/api/transport/courses/{dem['id']}/prendre-en-charge", headers=h["COMPTABLE"],
                    json={"camion_id": cam["id"], "tarif_mode": "voyage", "prix_unitaire": 300})
    assert r.status_code == 409 and "confirm" in r.json()["detail"].lower()

    # ── Le vendeur confirme → PO « prise en charge », demande déblocable
    dv2 = next(d for d in client.get(f"/api/ventes/devis?societe_id={pla}",
                                     headers=h["COMPTABLE"]).json()
               if d["commande_origine"] == cmd2["numero"])
    client.post(f"/api/ventes/devis/{dv2['id']}/confirmer", headers=h["COMPTABLE"])
    cmd2b = client.get(f"/api/commercial/commandes/{cmd2['id']}", headers=h["COMPTABLE"]).json()
    assert cmd2b["intersociete"]["etat"] == "prise_en_charge"

    r = client.post(f"/api/transport/courses/{dem['id']}/prendre-en-charge", headers=h["COMPTABLE"],
                    json={"camion_id": cam["id"], "tonnage_prevu": 10,
                          "tarif_mode": "voyage", "prix_unitaire": 300})
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "brouillon" and r.json()["camion"] == "5555 ZZ 05"

    # ── Livraison du vendeur, puis RÉCEPTION de l'acheteur (règle du groupe),
    #    et seulement ensuite la facturation → stock acheteur, PO soldée
    dv2d = client.get(f"/api/ventes/devis/{dv2['id']}", headers=h["COMPTABLE"]).json()
    lg_dv = next(l for l in dv2d["lignes"] if l["article"])
    client.post(f"/api/ventes/devis/{dv2['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg_dv["id"], "qte": 10}]})
    # facturer avant réception → refus
    assert client.post(f"/api/ventes/devis/{dv2['id']}/facturer",
                       headers=h["COMPTABLE"]).status_code == 409
    cmd2r = client.get(f"/api/commercial/commandes/{cmd2['id']}", headers=h["COMPTABLE"]).json()
    lrec = cmd2r["intersociete"]["reception"]["lignes"][0]
    client.post(f"/api/intersociete/commandes/{cmd2['id']}/receptionner", headers=h["COMPTABLE"],
                json={"lignes": [{"ligne_commande_id": lrec["ligne_commande_id"], "qte_bon": 10}]})
    r = client.post(f"/api/ventes/devis/{dv2['id']}/facturer", headers=h["COMPTABLE"])
    assert r.status_code == 201, r.text

    s_kkl = next(l for l in client.get(f"/api/commercial/stock?societe_id={kkl}",
                                       headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s_kkl["stock_qte"] == 10.0 and s_kkl["stock_valeur"] == 140.0   # 10 × 14
    cmd2c = client.get(f"/api/commercial/commandes/{cmd2['id']}", headers=h["COMPTABLE"]).json()
    assert cmd2c["statut"] == "soldee" and cmd2c["intersociete"]["etat"] == "facturee"


def test_requisitions_multiples_par_course(ctx):
    """L'initiale conditionne le départ ; les suppléments (crevaison, mécanicien
    en route) se rattachent à tout moment et s'additionnent au coût de revient."""
    client, ids = ctx
    h = _headers(client, ids)
    kkl = ids["kkl_id"]
    ext = client.post(f"/api/commercial/tiers?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "type": "client", "code": "CL-Z", "nom": "Client Z"}).json()
    cam = client.post(f"/api/transport/camions?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "immatriculation": "8800 QR 05", "capacite_tonnes": 30}).json()
    req1 = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": kkl, "objet": "Carburant initial", "devise": "USD",
        "lignes": [{"description": "Gasoil", "quantite": 1, "prix_unitaire": 400}]}).json()
    c = client.post(f"/api/transport/courses?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "client_tiers_id": ext["id"], "camion_id": cam["id"],
        "origine": "Likasi", "destination": "Kolwezi", "marchandise": "Ciment",
        "tonnage_prevu": 30, "tarif_mode": "voyage", "prix_unitaire": 700,
        "requisition_id": req1["id"]}).json()
    assert [r["numero"] for r in c["requisitions"]] == [req1["numero"]]
    client.post(f"/api/transport/courses/{c['id']}/valider", headers=h["DFI"])

    # Avance non décaissée → départ toujours bloqué
    assert client.post(f"/api/transport/courses/{c['id']}/depart",
                       headers=h["COMPTABLE"]).status_code == 409

    # Doublon → refus ; réquisition d'une autre société → refus
    assert client.post(f"/api/transport/courses/{c['id']}/lier-requisition", headers=h["COMPTABLE"],
                       json={"requisition_id": req1["id"]}).status_code == 409
    req_pla = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": ids["societe_id"], "objet": "Autre société", "devise": "USD",
        "lignes": [{"description": "X", "quantite": 1, "prix_unitaire": 10}]}).json()
    assert client.post(f"/api/transport/courses/{c['id']}/lier-requisition", headers=h["COMPTABLE"],
                       json={"requisition_id": req_pla["id"]}).status_code == 400

    # Dépense supplémentaire en route : rattachable à tout moment
    req2 = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": kkl, "objet": "Crevaison en route", "devise": "USD",
        "lignes": [{"description": "Pneu + montage", "quantite": 1, "prix_unitaire": 120}]}).json()
    r = client.post(f"/api/transport/courses/{c['id']}/lier-requisition", headers=h["COMPTABLE"],
                    json={"requisition_id": req2["id"]})
    assert r.status_code == 200, r.text
    assert sorted(x["numero"] for x in r.json()["requisitions"]) == \
        sorted([req1["numero"], req2["numero"]])
