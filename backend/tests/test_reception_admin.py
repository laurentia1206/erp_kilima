"""Réception acheteur (bon/mauvais/manquant), validateur configurable,
administration (sociétés, agents, tiers).
"""
from __future__ import annotations

import uuid as uuid_mod

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
        for code, nom in (("KKL", "KAKO Logistique"), ("DAK", "DAKAM Sarl")):
            soc = models.Societe(code=code, nom=nom, ville="Likasi")
            s.add(soc)
            s.flush()
            charger_plan(s, soc.id)
            pla_uuid = uuid_mod.UUID(ids["societe_id"])
            for u in s.execute(select(models.Utilisateur)).scalars():
                deja = {a.role_id for a in s.execute(select(models.UtilisateurSociete).where(
                    models.UtilisateurSociete.utilisateur_id == u.id,
                    models.UtilisateurSociete.societe_id == pla_uuid)).scalars()}
                for rid in deja:
                    s.add(models.UtilisateurSociete(utilisateur_id=u.id, societe_id=soc.id, role_id=rid))
            ids[code.lower() + "_id"] = str(soc.id)
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


def test_reception_bon_mauvais_manquant_et_gates(ctx):
    """DAK achète à PLANET, transport KKL. La facturation (vendeur ET
    transporteur) est bloquée avant la réception ; à la réception 7 bon /
    2 mauvais / 1 manquant : stock = 9, manquant au prix d'achat imputé à KKL,
    puis tout le monde peut facturer (vendeur : quantité chargée)."""
    client, ids = ctx
    h = _headers(client, ids)
    pla, kkl, dak = ids["societe_id"], ids["kkl_id"], ids["dak_id"]

    # DAK (acheteur) : article + fournisseur lié à PLANET (vendeur)
    client.post(f"/api/commercial/articles?societe_id={dak}", headers=h["COMPTABLE"], json={
        "code": "CIM50", "designation": "Ciment gris 50 kg", "prix_achat": 14, "prix_vente": 17})
    fourn = client.post(f"/api/commercial/tiers?societe_id={dak}", headers=h["COMPTABLE"], json={
        "type": "fournisseur", "code": "PLA", "nom": "PLANET Sarl"}).json()
    client.post("/api/intersociete/lier", headers=h["DFI"], json={
        "tiers_id": fourn["id"], "societe_liee_id": pla})
    # PLANET : stock 100 @ 10
    cim_pla = next(a for a in client.get(f"/api/commercial/articles?societe_id={pla}",
                                         headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    f_pla = next(t for t in client.get(f"/api/commercial/tiers?societe_id={pla}",
                                       headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")
    client.post(f"/api/commercial/factures?societe_id={pla}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": f_pla["id"],
        "lignes": [{"article_id": cim_pla["id"], "qte": 100, "prix_unitaire": 10}]})
    cim_dak = next(a for a in client.get(f"/api/commercial/articles?societe_id={dak}",
                                         headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")

    # PO DAK → PLANET, transporteur KKL
    cmd = client.post(f"/api/commercial/commandes?societe_id={dak}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "destination": "Dépôt DAKAM Likasi",
        "transporteur_societe_id": kkl,
        "lignes": [{"article_id": cim_dak["id"], "qte": 10, "prix_unitaire": 14}]}).json()
    assert cmd["intersociete"]["course_numero"].startswith("FC-KKL-")

    # Vendeur confirme et livre (charge 10)
    dv = next(d for d in client.get(f"/api/ventes/devis?societe_id={pla}",
                                    headers=h["COMPTABLE"]).json()
              if d["commande_origine"] == cmd["numero"])
    client.post(f"/api/ventes/devis/{dv['id']}/confirmer", headers=h["COMPTABLE"])
    dvd = client.get(f"/api/ventes/devis/{dv['id']}", headers=h["COMPTABLE"]).json()
    lg = next(l for l in dvd["lignes"] if l["article"])
    client.post(f"/api/ventes/devis/{dv['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg["id"], "qte": 10}]})

    # Gate vendeur : facturer avant réception → 409
    r = client.post(f"/api/ventes/devis/{dv['id']}/facturer", headers=h["COMPTABLE"])
    assert r.status_code == 409 and "réception" in r.json()["detail"].lower()

    # Course KKL : prise en charge → validée → départ → ARRIVÉE (déchargement) → retour
    dem = next(c for c in client.get(f"/api/transport/courses?societe_id={kkl}&statut=demande",
                                     headers=h["COMPTABLE"]).json()
               if c["numero"] == cmd["intersociete"]["course_numero"])
    cam = client.post(f"/api/transport/camions?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "immatriculation": "2024 KL 05", "capacite_tonnes": 30}).json()
    client.post(f"/api/transport/courses/{dem['id']}/prendre-en-charge", headers=h["COMPTABLE"],
                json={"camion_id": cam["id"], "tonnage_prevu": 10,
                      "tarif_mode": "voyage", "prix_unitaire": 250})
    client.post(f"/api/transport/courses/{dem['id']}/valider", headers=h["DFI"])
    client.post(f"/api/transport/courses/{dem['id']}/depart", headers=h["COMPTABLE"])
    r = client.post(f"/api/transport/courses/{dem['id']}/arrivee", headers=h["COMPTABLE"])
    assert r.json()["statut"] == "arrivee"
    # Suivi partagé : l'acheteur (DAK) voit le statut de la course sur son PO
    cmd_vue = client.get(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"]).json()
    assert cmd_vue["intersociete"]["course_statut"] == "arrivee"
    client.post(f"/api/transport/courses/{dem['id']}/retour", headers=h["COMPTABLE"],
                json={"tonnage_livre": 9})

    # Gate transporteur : facturer avant réception → 409
    r = client.post(f"/api/transport/facturer?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "course_ids": [dem["id"]]})
    assert r.status_code == 409 and "réception" in r.json()["detail"].lower()

    # ── Réception DAK : 7 bon, 2 mauvais, 1 manquant (sur 10 chargés)
    cmd_d = client.get(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"]).json()
    lrec = cmd_d["intersociete"]["reception"]["lignes"][0]
    assert lrec["livre"] == 10.0 and lrec["a_recevoir"] == 10.0
    # Sur-réception → refus
    r = client.post(f"/api/intersociete/commandes/{cmd['id']}/receptionner", headers=h["COMPTABLE"],
                    json={"lignes": [{"ligne_commande_id": lrec["ligne_commande_id"],
                                      "qte_bon": 11}]})
    assert r.status_code == 409
    r = client.post(f"/api/intersociete/commandes/{cmd['id']}/receptionner", headers=h["COMPTABLE"],
                    json={"lignes": [{"ligne_commande_id": lrec["ligne_commande_id"],
                                      "qte_bon": 8, "qte_mauvais": 1, "qte_manquante": 1}]})
    assert r.status_code == 201, r.text
    rec1_num = r.json()["numero"]

    # ── L'acheteur se ravise AVANT la confirmation du transporteur : il ANNULE
    #    (contre-passation stock + manquants) puis ressaisit le bon constat
    recs = client.get(f"/api/intersociete/receptions?societe_id={dak}", headers=h["COMPTABLE"]).json()
    rec1 = next(x for x in recs["historique"] if x["numero"] == rec1_num)
    r = client.delete(f"/api/intersociete/receptions/{rec1['id']}", headers=h["COMPTABLE"])
    assert r.status_code == 200, r.text
    s_dak = next(l for l in client.get(f"/api/commercial/stock?societe_id={dak}",
                                       headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s_dak["stock_qte"] == 0.0                          # contre-passé
    r = client.post(f"/api/intersociete/commandes/{cmd['id']}/receptionner", headers=h["COMPTABLE"],
                    json={"lignes": [{"ligne_commande_id": lrec["ligne_commande_id"],
                                      "qte_bon": 7, "qte_mauvais": 2, "qte_manquante": 1}],
                          "note": "2 sacs déchirés, 1 manquant"})
    assert r.status_code == 201, r.text
    assert r.json()["manquants_usd"] == 14.0 and r.json()["manquants_imputes_transporteur"] is True
    # une réception confirmée ne s'annule plus (testé plus bas après confirmation)

    # Stock DAK = reçu (9 × 14), manquant imputé à KKL des deux côtés
    s_dak = next(l for l in client.get(f"/api/commercial/stock?societe_id={dak}",
                                       headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s_dak["stock_qte"] == 9.0 and s_dak["stock_valeur"] == 126.0
    bal_dak = _balance(client, h, dak)
    assert bal_dak["758"]["solde_crediteur"] == 14.0          # indemnité manquants (produit DAK)
    bal_kkl = _balance(client, h, kkl)
    assert bal_kkl["658"]["solde_debiteur"] == 14.0           # manquants supportés (charge KKL)

    # ── Le vendeur peut facturer (quantité chargée) ; le transporteur DOIT
    #    d'abord CONFIRMER le constat de l'acheteur (règle de Laurent)
    r = client.post(f"/api/ventes/devis/{dv['id']}/facturer", headers=h["COMPTABLE"])
    assert r.status_code == 201, r.text
    assert r.json()["facture"]["total_ttc"] == 162.4          # chargé : 10 × 14 = 140 HT + 22,4 TVA
    r = client.post(f"/api/transport/facturer?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "course_ids": [dem["id"]]})
    assert r.status_code == 409 and "confirm" in r.json()["detail"].lower()
    # la vue Achats›Réceptions de DAK montre la réception « à confirmer »
    recs = client.get(f"/api/intersociete/receptions?societe_id={dak}", headers=h["COMPTABLE"]).json()
    rec_att = next(x for x in recs["historique"] if x["statut"] == "a_confirmer")
    # le transporteur confirme → sa facturation passe ; le constat devient figé
    r = client.post(f"/api/intersociete/receptions/{rec_att['id']}/confirmer", headers=h["COMPTABLE"])
    assert r.status_code == 200, r.text
    assert client.delete(f"/api/intersociete/receptions/{rec_att['id']}",
                         headers=h["COMPTABLE"]).status_code == 409
    r = client.post(f"/api/transport/facturer?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "course_ids": [dem["id"]]})
    assert r.status_code == 201, r.text

    # Miroir vente marchandises : PAS de double entrée de stock chez DAK
    s_dak = next(l for l in client.get(f"/api/commercial/stock?societe_id={dak}",
                                       headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s_dak["stock_qte"] == 9.0
    assert _balance(client, h, dak)["31"]["solde_debiteur"] == 126.0


def test_po_ligne_libre_ref_producteur_et_badges(ctx):
    """Article inconnu chez le vendeur (ligne libre) : le CHARGEMENT reste
    obligatoire avant facturation ; le n° producteur saisi à la prise en charge
    suit le PO et la facture ; les badges comptent les opérations en attente."""
    client, ids = ctx
    h = _headers(client, ids)
    pla, dak = ids["societe_id"], ids["dak_id"]

    # Acheteur DAK : article CHAUX25 (inexistant chez PLANET → ligne libre au miroir)
    art = client.post(f"/api/commercial/articles?societe_id={dak}", headers=h["COMPTABLE"], json={
        "code": "CHAUX25", "designation": "Chaux hydratée 25 kg", "prix_achat": 8, "prix_vente": 11}).json()
    fourn = client.post(f"/api/commercial/tiers?societe_id={dak}", headers=h["COMPTABLE"], json={
        "type": "fournisseur", "code": "PLA-2", "nom": "PLANET Sarl"}).json()
    client.post("/api/intersociete/lier", headers=h["DFI"], json={
        "tiers_id": fourn["id"], "societe_liee_id": pla})
    cmd = client.post(f"/api/commercial/commandes?societe_id={dak}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "destination": "Dépôt DAKAM",
        "lignes": [{"article_id": art["id"], "qte": 20, "prix_unitaire": 8}]}).json()

    # Badge vendeur : 1 PO à prendre en charge
    assert client.get(f"/api/intersociete/badges?societe_id={pla}",
                      headers=h["COMPTABLE"]).json()["devis_po"] >= 1

    # La ligne arrive « à associer » chez le vendeur (article inconnu chez lui)
    dv = next(d for d in client.get(f"/api/ventes/devis?societe_id={pla}",
                                    headers=h["COMPTABLE"]).json()
              if d["commande_origine"] == cmd["numero"])
    dvd = client.get(f"/api/ventes/devis/{dv['id']}", headers=h["COMPTABLE"]).json()
    lg = dvd["lignes"][0]
    assert lg["article"] is None and lg["a_associer"] is True and lg["code_acheteur"] == "CHAUX25"

    # Prise en charge : N° PRODUCTEUR + ASSOCIATION (création de l'article chez le vendeur)
    r = client.post(f"/api/ventes/devis/{dv['id']}/confirmer", headers=h["COMPTABLE"],
                    json={"reference_producteur": "GCK-2026-08841",
                          "associations": [{"ligne_id": lg["id"],
                                            "nouvel_article": {"code": "CHAUX25", "prix_achat": 6}}]})
    assert r.json()["reference_producteur"] == "GCK-2026-08841"
    assert r.json()["lignes"][0]["article"] == "CHAUX25"
    cmd_v = client.get(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"]).json()
    assert cmd_v["reference_fournisseur"] == "GCK-2026-08841"

    # SANS chargement déclaré : rien à facturer
    assert client.post(f"/api/ventes/devis/{dv['id']}/facturer",
                       headers=h["COMPTABLE"]).status_code == 409
    # Chargement SANS stock chez le vendeur → refus (règle A1 de Laurent)
    r = client.post(f"/api/ventes/devis/{dv['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg["id"], "qte": 20}]})
    assert r.status_code == 409 and "stock" in r.json()["detail"].lower()
    # Le vendeur s'approvisionne (20 @ 6) puis charge
    f_pla = next(t for t in client.get(f"/api/commercial/tiers?societe_id={pla}",
                                       headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")
    chaux_pla = next(a for a in client.get(f"/api/commercial/articles?societe_id={pla}",
                                           headers=h["COMPTABLE"]).json() if a["code"] == "CHAUX25")
    client.post(f"/api/commercial/factures?societe_id={pla}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": f_pla["id"],
        "lignes": [{"article_id": chaux_pla["id"], "qte": 20, "prix_unitaire": 6}]})
    r = client.post(f"/api/ventes/devis/{dv['id']}/livrer", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_id": lg["id"], "qte": 20}]})
    assert r.status_code == 201, r.text

    # Badge acheteur : 1 marchandise à réceptionner ; facturation toujours bloquée
    assert client.get(f"/api/intersociete/badges?societe_id={dak}",
                      headers=h["COMPTABLE"]).json()["receptions"] >= 1
    r = client.post(f"/api/ventes/devis/{dv['id']}/facturer", headers=h["COMPTABLE"])
    assert r.status_code == 409 and "réception" in r.json()["detail"].lower()

    # Réception complète → facture OK, avec le n° producteur en référence,
    # et le stock CHAUX25 entré chez l'acheteur
    cmd_v = client.get(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"]).json()
    lrec = cmd_v["intersociete"]["reception"]["lignes"][0]
    client.post(f"/api/intersociete/commandes/{cmd['id']}/receptionner", headers=h["COMPTABLE"],
                json={"lignes": [{"ligne_commande_id": lrec["ligne_commande_id"], "qte_bon": 20}]})
    r = client.post(f"/api/ventes/devis/{dv['id']}/facturer", headers=h["COMPTABLE"])
    assert r.status_code == 201, r.text
    fac = client.get(f"/api/commercial/factures/{r.json()['facture']['id']}",
                     headers=h["COMPTABLE"]).json()
    assert fac["reference"] == "GCK-2026-08841"
    s_dak = next(l for l in client.get(f"/api/commercial/stock?societe_id={dak}",
                                       headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CHAUX25")
    assert s_dak["stock_qte"] == 20.0 and s_dak["stock_valeur"] == 160.0
    # facture miroir chez l'acheteur : EN ATTENTE de validation comptable
    achats_dak = client.get(f"/api/commercial/factures?societe_id={dak}&type=achat",
                            headers=h["COMPTABLE"]).json()
    miroir = next(x for x in achats_dak if x["reference"] == r.json()["facture"]["numero"]
                  or (x["intra_groupe"] and x["total_ttc"] == fac["total_ttc"]))
    assert miroir["statut"] == "en_attente"


def test_validateur_course_configurable(ctx):
    """Le rôle validateur des fiches de course se règle par société (défaut DFI)."""
    client, ids = ctx
    h = _headers(client, ids)
    kkl = ids["kkl_id"]
    ext = client.post(f"/api/commercial/tiers?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "type": "client", "code": "CL-V", "nom": "Client V"}).json()
    cam = client.post(f"/api/transport/camions?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "immatriculation": "7777 VV 05", "capacite_tonnes": 30}).json()
    c = client.post(f"/api/transport/courses?societe_id={kkl}", headers=h["COMPTABLE"], json={
        "client_tiers_id": ext["id"], "camion_id": cam["id"],
        "origine": "Likasi", "destination": "Kolwezi", "marchandise": "Ciment",
        "tonnage_prevu": 20, "tarif_mode": "voyage", "prix_unitaire": 500}).json()

    assert client.get(f"/api/transport/config?societe_id={kkl}",
                      headers=h["COMPTABLE"]).json()["role_validation"] == "DFI"
    # Délégation au DG
    r = client.post(f"/api/transport/config?societe_id={kkl}", headers=h["DFI"],
                    json={"role_validation": "DG"})
    assert r.status_code == 200 and r.json()["role_validation"] == "DG"
    # Le DFI ne peut plus valider ; le DG oui
    assert client.post(f"/api/transport/courses/{c['id']}/valider", headers=h["DFI"]).status_code == 403
    assert client.post(f"/api/transport/courses/{c['id']}/valider",
                       headers=h["DG"]).json()["statut"] == "validee"


def test_administration_societes_agents_tiers(ctx):
    """Création de société (plan + caisse + affectation), création d'agent qui
    peut se connecter, désactivation, modification de tiers."""
    client, ids = ctx
    h = _headers(client, ids)

    # ── Société
    r = client.post("/api/config/societes", headers=h["DFI"], json={
        "code": "GHR", "nom": "Guest House Relax", "ville": "Likasi"})
    assert r.status_code == 201, r.text
    ghr = r.json()
    assert client.post("/api/config/societes", headers=h["DFI"], json={
        "code": "GHR", "nom": "Doublon"}).status_code == 409
    # Le créateur y a accès, la caisse principale et le plan existent
    mes_socs = client.get("/api/societes", headers=h["DFI"]).json()
    assert any(s["id"] == ghr["id"] for s in mes_socs)
    caisses = client.get(f"/api/caisses?societe_id={ghr['id']}", headers=h["DFI"]).json()
    assert len(caisses) == 1 and caisses[0]["est_principale"] is True
    plan = client.get(f"/api/comptabilite/plan-comptable?societe_id={ghr['id']}",
                      headers=h["DFI"]).json()
    assert isinstance(plan, list) and len(plan) > 50

    # ── Agent : création + connexion + désactivation
    r = client.post("/api/config/utilisateurs", headers=h["DFI"], json={
        "nom": "MUKENDI", "prenom": "Vinciane", "email": "vinciane@kilima.cd",
        "password": "secret123",
        "affectations": [{"societe_id": ids["kkl_id"], "role_code": "COMPTABLE"}]})
    assert r.status_code == 201, r.text
    hv = _login(client, "vinciane@kilima.cd", "secret123")
    socs_v = client.get("/api/societes", headers=hv).json()
    assert len(socs_v) == 1 and socs_v[0]["id"] == ids["kkl_id"]
    # Affectation supplémentaire via l'API dédiée
    u_id = r.json()["id"]
    client.post("/api/config/affectations", headers=h["DFI"], json={
        "utilisateur_id": u_id, "societe_id": ghr["id"], "role_code": "COMPTABLE"})
    assert len(client.get("/api/societes", headers=hv).json()) == 2
    # Désactivation → liste admin la montre inactive
    client.patch(f"/api/config/utilisateurs/{u_id}", headers=h["DFI"], json={"actif": False})
    lst = client.get("/api/config/utilisateurs", headers=h["DFI"]).json()
    assert next(u for u in lst if u["email"] == "vinciane@kilima.cd")["actif"] is False

    # ── Tiers : modification (plafond crédit, nom)
    t = client.post(f"/api/commercial/tiers?societe_id={ids['societe_id']}", headers=h["COMPTABLE"],
                    json={"type": "client", "code": "TST", "nom": "Client Test"}).json()
    r = client.patch(f"/api/commercial/tiers/{t['id']}", headers=h["COMPTABLE"], json={
        "nom": "Client Test SARL", "limite_credit_usd": 500})
    assert r.status_code == 200
    assert r.json()["nom"] == "Client Test SARL" and r.json()["limite_credit_usd"] == 500.0


def test_administration_v2_modifications_roles_protection(ctx):
    """Sociétés modifiables/archivables/supprimables (si vides), agents
    modifiables, rôles personnalisés avec héritage de droits d'accès."""
    client, ids = ctx
    h = _headers(client, ids)
    pla = ids["societe_id"]

    # ── Société : modifier puis archiver puis réactiver
    s = client.post("/api/config/societes", headers=h["DFI"], json={
        "code": "TST", "nom": "Société Test", "ville": "Likasi"}).json()
    r = client.patch(f"/api/config/societes/{s['id']}", headers=h["DFI"], json={
        "nom": "Société Test Renommée", "ville": "Kolwezi"})
    assert r.status_code == 200 and r.json()["nom"] == "Société Test Renommée"
    client.patch(f"/api/config/societes/{s['id']}", headers=h["DFI"], json={"actif": False})
    cfg = client.get("/api/config/societes", headers=h["DFI"]).json()
    assert next(x for x in cfg if x["id"] == s["id"])["actif"] is False
    client.patch(f"/api/config/societes/{s['id']}", headers=h["DFI"], json={"actif": True})

    # ── Suppression : OK si vide, refusée si activité
    r = client.delete(f"/api/config/societes/{s['id']}", headers=h["DFI"])
    assert r.status_code == 200
    assert not any(x["id"] == s["id"] for x in client.get("/api/config/societes", headers=h["DFI"]).json())
    # PLANET a de l'activité (on lui crée une facture) → suppression refusée
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={pla}",
                                     headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={pla}",
                                       headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")
    client.post(f"/api/commercial/factures?societe_id={pla}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"],
        "lignes": [{"article_id": cim["id"], "qte": 5, "prix_unitaire": 10}]})
    assert client.delete(f"/api/config/societes/{pla}", headers=h["DFI"]).status_code == 409

    # ── Agent : modifier identité + email (avec contrôle d'unicité)
    u = client.post("/api/config/utilisateurs", headers=h["DFI"], json={
        "nom": "KALENGA", "email": "papy@kilima.cd", "password": "secret123",
        "affectations": [{"societe_id": pla, "role_code": "COMPTABLE"}]}).json()
    r = client.patch(f"/api/config/utilisateurs/{u['id']}", headers=h["DFI"], json={
        "nom": "KALENGA MWEPU", "prenom": "Papy", "email": "papy.kalenga@kilima.cd"})
    assert r.status_code == 200
    _login(client, "papy.kalenga@kilima.cd", "secret123")   # le nouvel email fonctionne
    assert client.patch(f"/api/config/utilisateurs/{u['id']}", headers=h["DFI"], json={
        "email": "dfi@kilima.cd"}).status_code == 409       # doublon refusé

    # ── Rôle personnalisé avec héritage : LOGISTICIEN hérite de COMPTABLE
    r = client.post("/api/config/roles", headers=h["DFI"], json={
        "code": "LOGISTICIEN", "libelle": "Logisticien / Dispatcher", "herite_de": "COMPTABLE"})
    assert r.status_code == 201, r.text
    role_id = r.json()["id"]
    v = client.post("/api/config/utilisateurs", headers=h["DFI"], json={
        "nom": "ILUNGA", "email": "dispatch@kilima.cd", "password": "secret123",
        "affectations": [{"societe_id": ids["kkl_id"], "role_code": "LOGISTICIEN"}]}).json()
    hd = _login(client, "dispatch@kilima.cd", "secret123")
    # accès aux écrans COMPTABLE (articles) et transport grâce à l'héritage
    assert client.get(f"/api/commercial/articles?societe_id={ids['kkl_id']}", headers=hd).status_code == 200
    assert client.get(f"/api/transport/camions?societe_id={ids['kkl_id']}", headers=hd).status_code == 200

    # rôle utilisé → suppression refusée ; rôle système → refusée aussi
    assert client.delete(f"/api/config/roles/{role_id}", headers=h["DFI"]).status_code == 409
    roles = client.get("/api/config/roles", headers=h["DFI"]).json()
    dfi_role = next(x for x in roles if x["code"] == "DFI")
    assert client.delete(f"/api/config/roles/{dfi_role['id']}", headers=h["DFI"]).status_code == 409
    # après retrait de l'affectation, la suppression passe
    client.request("DELETE", "/api/config/affectations", headers=h["DFI"], json={
        "utilisateur_id": v["id"], "societe_id": ids["kkl_id"], "role_code": "LOGISTICIEN"})
    assert client.delete(f"/api/config/roles/{role_id}", headers=h["DFI"]).status_code == 200
