"""Test d'intégration bout-en-bout du circuit de décaissement sur SQLite.

Login multi-rôles → réquisition (G01) → validation demande → ordre de dépense
(G02) → validation sortie de fonds (paliers) → exécution (G03 + avance) →
justification (G04) → vérification des écritures comptables OHADA générées.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.comptabilite import compute_balance
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
    yield client, ids, TestSession
    app.dependency_overrides.clear()


def _login(client, email, pw):
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_circuit_complet(ctx):
    client, ids, TestSession = ctx
    pw = ids["password"]
    u = ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}

    # 1. G01 — réquisition de 5 000 USD (par le comptable)
    r = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": ids["societe_id"], "objet": "Achat fournitures", "devise": "USD",
        "lignes": [{"description": "Lot A", "quantite": 1, "prix_unitaire": 3000},
                   {"description": "Lot B", "quantite": 1, "prix_unitaire": 2000}],
    })
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["montant_total_usd"] == "5000.00"
    assert req["statut"] == "soumise"
    req_id = req["id"]

    # 2. Validation de la demande : DG puis Admin
    r = client.post(f"/api/requisitions/{req_id}/valider-demande", headers=h["DG"],
                    json={"decision": "valide"})
    assert r.json()["statut"] == "soumise"   # Admin manquant
    r = client.post(f"/api/requisitions/{req_id}/valider-demande", headers=h["ADMIN"],
                    json={"decision": "valide"})
    assert r.json()["statut"] == "demande_validee", r.text

    # Auto-validation interdite : le comptable initiateur n'est pas validateur ici,
    # mais vérifions le garde-fou avec le DG re-soumettant sa propre demande plus bas.

    # 3. G02 — ordre de dépense (par le DFI)
    r = client.post("/api/ordres-depense", headers=h["DFI"], json={
        "requisition_id": req_id, "beneficiaire_tiers_id": ids["beneficiaire_id"],
        "mode_paiement": "caisse"})
    assert r.status_code == 201, r.text
    odp = r.json()
    assert odp["palier_applique"] == "1001-10000"
    assert odp["statut"] == "a_valider"
    odp_id = odp["id"]

    # 4. Validation sortie de fonds : palier conjoint DFI+DG+Admin+Président
    for role in ["DFI", "DG", "ADMIN"]:
        r = client.post(f"/api/ordres-depense/{odp_id}/valider", headers=h[role],
                        json={"decision": "valide"})
        assert r.json()["statut"] == "a_valider", f"{role}: {r.text}"
    r = client.post(f"/api/ordres-depense/{odp_id}/valider", headers=h["PRESIDENT"],
                    json={"decision": "valide"})
    assert r.json()["statut"] == "valide", r.text

    # 5. Exécution par le caissier (G03 + avance + écriture versement)
    client.post(f"/api/caisse/{ids['caisse_id']}/ouvrir", headers=h["CAISSIER_CENTRAL"],
                json={"fond_initial_usd": 1000000})
    r = client.post(f"/api/ordres-depense/{odp_id}/executer",
                    headers=h["CAISSIER_CENTRAL"],
                    json={"caisse_id": ids["caisse_id"], "type_avance": "boissons"})
    assert r.status_code == 200, r.text
    assert r.json()["avance_numero"].startswith("AVJ-")

    # Récupère l'avance créée
    with TestSession() as s:
        avance = s.execute(select(models.Avance)).scalar_one()
        avance_id = str(avance.id)
        assert avance.statut == "a_justifier"

    # 6. G04 — justification (3000 + 2000 = 5000, conforme)
    r = client.post("/api/avances/justifier", headers=h["COMPTABLE"], json={
        "avance_id": avance_id, "solde_retourne": 0, "devise_solde": "USD",
        "lignes": [{"nature": "Lot A", "devise": "USD", "montant": 3000, "compte_impute": "605"},
                   {"nature": "Lot B", "devise": "USD", "montant": 2000, "compte_impute": "605"}],
    })
    assert r.status_code == 201, r.text
    just = r.json()
    assert just["ecart_usd"] == "0.00"
    assert just["complement_demande"] is False

    # 7. Vérification comptable : écritures équilibrées et avance (421) soldée
    from app.comptabilite import compute_balance
    with TestSession() as s:
        ecritures = s.execute(select(models.Ecriture)).scalars().all()
        assert len(ecritures) == 2  # versement + justification
        lignes = s.execute(select(models.LigneEcriture)).scalars().all()
        debit = sum(float(l.montant_usd) for l in lignes if l.sens == "D")
        credit = sum(float(l.montant_usd) for l in lignes if l.sens == "C")
        assert round(debit, 2) == round(credit, 2)  # partie double globale

        balance = {b["compte"]: b for b in compute_balance(s, avance.societe_id)}
        # bénéficiaire = agent → compte d'avance 421 (Personnel)
        assert balance["421"]["solde"] == 0.0      # avance apurée
        assert balance["571"]["solde"] == -5000.0  # sortie de caisse
        assert balance["605"]["solde"] == 5000.0   # charge constatée


def test_decaissement_refuse_sans_validation(ctx):
    """Le caissier ne peut pas exécuter un ordre non validé."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}

    r = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": ids["societe_id"], "objet": "Test", "devise": "USD",
        "lignes": [{"description": "x", "quantite": 1, "prix_unitaire": 5000}]})
    req_id = r.json()["id"]
    client.post(f"/api/requisitions/{req_id}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{req_id}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    r = client.post("/api/ordres-depense", headers=h["DFI"], json={
        "requisition_id": req_id, "beneficiaire_tiers_id": ids["beneficiaire_id"]})
    odp_id = r.json()["id"]
    assert r.json()["statut"] == "a_valider"   # 5000 : émission DFI faite, reste DG/Admin/Président

    # Pas de validation sortie → exécution refusée (5000 : reste à co-signer après émission)
    r = client.post(f"/api/ordres-depense/{odp_id}/executer", headers=h["CAISSIER_CENTRAL"],
                    json={"caisse_id": ids["caisse_id"]})
    assert r.status_code == 409


def test_centre_approbation(ctx):
    """Le Centre d'approbation montre à chacun ce qui attend SA validation."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}

    r = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": ids["societe_id"], "objet": "Carburant", "devise": "USD",
        "lignes": [{"description": "Gasoil", "quantite": 1, "prix_unitaire": 5000}]})
    req_id = r.json()["id"]

    # Le DG voit la réquisition à valider ; le comptable initiateur ne la voit PAS
    appro_dg = client.get("/api/approbations", headers=h["DG"]).json()
    assert any(x["id"] == req_id for x in appro_dg["requisitions"])
    appro_comptable = client.get("/api/approbations", headers=h["COMPTABLE"]).json()
    assert not any(x["id"] == req_id for x in appro_comptable["requisitions"])

    # Après validation DG, le DG ne la voit plus ; Admin la voit encore
    client.post(f"/api/requisitions/{req_id}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    assert not any(x["id"] == req_id for x in client.get("/api/approbations", headers=h["DG"]).json()["requisitions"])
    assert any(x["id"] == req_id for x in client.get("/api/approbations", headers=h["ADMIN"]).json()["requisitions"])

    # Admin valide → demande validée ; DFI crée l'ordre → apparaît chez le DFI (≤1000 → DFI seul)
    client.post(f"/api/requisitions/{req_id}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    r = client.post("/api/ordres-depense", headers=h["DFI"], json={
        "requisition_id": req_id, "beneficiaire_tiers_id": ids["beneficiaire_id"]})
    odp_id = r.json()["id"]
    # L'émission par le DFI vaut sa validation N2 : il ne le revoit pas ; les autres co-signataires si.
    assert r.json()["statut"] == "a_valider"
    assert any(x["id"] == odp_id for x in client.get("/api/approbations", headers=h["DG"]).json()["ordres_depense"])
    assert not any(x["id"] == odp_id for x in client.get("/api/approbations", headers=h["DFI"]).json()["ordres_depense"])


def test_renvoi_pour_precisions(ctx):
    """Un validateur renvoie la demande pour précisions, l'initiateur répond, puis validation."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}

    r = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": ids["societe_id"], "objet": "Mission", "devise": "USD",
        "lignes": [{"description": "frais", "quantite": 1, "prix_unitaire": 400}]})
    rid = r.json()["id"]

    # DG demande des précisions (et non un rejet)
    r = client.post(f"/api/requisitions/{rid}/demander-precisions", headers=h["DG"],
                    json={"decision": "valide", "commentaire": "Préciser la destination et la durée."})
    assert r.json()["statut"] == "en_attente_info", r.text
    # La réquisition apparaît chez l'initiateur comme à compléter
    mine = [x for x in client.get(f"/api/requisitions?societe_id={ids['societe_id']}",
                                  headers=h["COMPTABLE"]).json() if x["id"] == rid][0]
    assert mine["statut"] == "en_attente_info" and mine["nb_commentaires"] == 1

    # L'initiateur répond → re-soumise
    r = client.post(f"/api/requisitions/{rid}/repondre", headers=h["COMPTABLE"],
                    json={"decision": "valide", "commentaire": "Lubumbashi, 3 jours."})
    assert r.json()["statut"] == "soumise"
    comms = client.get(f"/api/requisitions/{rid}/commentaires", headers=h["DG"]).json()
    assert [c["type"] for c in comms] == ["precision_demandee", "reponse"]

    # Validation normale ensuite
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    r = client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    assert r.json()["statut"] == "demande_validee"


def test_decaissement_par_banque(ctx):
    """Décaissement via banque : crédite le compte 521, sans mouvement de caisse."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}

    with TestSession() as s:
        banque = s.execute(select(models.CompteBancaire)).scalar_one()
        bank_id = str(banque.id)

    r = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": ids["societe_id"], "objet": "Paiement fournisseur", "devise": "USD",
        "lignes": [{"description": "facture", "quantite": 1, "prix_unitaire": 600}]})
    rid = r.json()["id"]
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    # Ordre en mode banque
    r = client.post("/api/ordres-depense", headers=h["DFI"], json={
        "requisition_id": rid, "beneficiaire_tiers_id": ids["beneficiaire_id"], "mode_paiement": "banque"})
    odp_resp = r.json()
    odp_id = odp_resp["id"]
    # 600 USD → palier ≤1000 → DFI seul : l'émission par le DFI vaut déjà sa validation N2
    assert odp_resp["statut"] == "valide"
    # Exécution par banque = par le COMPTABLE (établit l'OP / le chèque), pas le caissier
    assert client.post(f"/api/ordres-depense/{odp_id}/executer", headers=h["CAISSIER_CENTRAL"],
                       json={"compte_bancaire_id": bank_id}).status_code == 403
    r = client.post(f"/api/ordres-depense/{odp_id}/executer", headers=h["COMPTABLE"],
                    json={"compte_bancaire_id": bank_id, "reference_paiement": "OP-2026-001"})
    assert r.status_code == 200, r.text

    with TestSession() as s:
        lignes = s.execute(select(models.LigneEcriture)).scalars().all()
        credits = {l.compte_numero for l in lignes if l.sens == "C"}
        assert "521" in credits and "571" not in credits  # banque créditée, pas la caisse
        mvts = s.execute(select(models.MouvementCaisse)).scalars().all()
        assert len(mvts) == 0  # aucun mouvement de caisse pour un paiement banque


def test_paiement_direct_sur_justificatif(ctx):
    """Paiement direct : pas d'avance à justifier, charge constatée directement."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}

    r = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": ids["societe_id"], "objet": "Achat ciment (facture reçue)",
        "mode_decaissement": "paiement_direct", "devise": "USD",
        "lignes": [{"description": "20 sacs ciment", "quantite": 1, "prix_unitaire": 600}]})
    rid = r.json()["id"]
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    r = client.post("/api/ordres-depense", headers=h["DFI"], json={
        "requisition_id": rid, "beneficiaire_tiers_id": ids["beneficiaire_id"]})
    odp_resp = r.json()
    odp_id = odp_resp["id"]
    assert odp_resp["statut"] == "valide"   # 600 → DFI seul : émission = validation N2
    client.post(f"/api/caisse/{ids['caisse_id']}/ouvrir", headers=h["CAISSIER_CENTRAL"],
                json={"fond_initial_usd": 1000000})
    r = client.post(f"/api/ordres-depense/{odp_id}/executer", headers=h["CAISSIER_CENTRAL"],
                    json={"caisse_id": ids["caisse_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "paiement_direct"
    assert "avance_numero" not in r.json()

    with TestSession() as s:
        assert s.execute(select(models.Avance)).scalars().all() == []  # AUCUNE avance créée
        bal = {b["compte"]: b for b in compute_balance(s, uuid_of(ids["societe_id"]))}
        assert bal["605"]["solde"] == 600.0   # charge constatée
        assert bal["571"]["solde"] == -600.0  # sortie de caisse
        assert "409" not in bal                # pas de compte d'avance mouvementé


def test_pieces_jointes(ctx):
    """Téléversement et liste d'une pièce jointe sur une réquisition."""
    client, ids, _ = ctx
    h = _login(client, ids["users"]["COMPTABLE"], ids["password"])
    r = client.post("/api/requisitions", headers=h, json={
        "societe_id": ids["societe_id"], "objet": "Avec justificatif", "devise": "USD",
        "lignes": [{"description": "x", "quantite": 1, "prix_unitaire": 50}]})
    rid = r.json()["id"]
    up = client.post("/api/pieces-jointes", headers=h,
                     data={"document_type": "requisition", "document_id": rid},
                     files={"file": ("facture.txt", b"FACTURE DEMO", "text/plain")})
    assert up.status_code == 201, up.text
    lst = client.get(f"/api/pieces-jointes?document_type=requisition&document_id={rid}", headers=h).json()
    assert len(lst) == 1 and lst[0]["nom_fichier"] == "facture.txt"


def uuid_of(s):
    import uuid as _u
    return _u.UUID(s)


def test_config_paliers_et_parametres(ctx):
    """Paramétrage : lecture/écriture de la grille et des seuils, réservé aux admins."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    dfi = _login(client, u["DFI"], pw)
    comptable = _login(client, u["COMPTABLE"], pw)

    # Accès réservé : le comptable est refusé
    assert client.get("/api/config/paliers", headers=comptable).status_code == 403

    # Grille groupe : niveau 2 a bien 3 paliers
    grille = client.get("/api/config/paliers", headers=dfi).json()
    assert len(grille["sortie_fonds"]) == 3
    assert len(grille["demande"]) == 1

    # Crée un palier spécifique à PLANET (niveau 1) : > 2000 → DG + Président
    r = client.post("/api/config/paliers", headers=dfi, json={
        "societe_id": ids["societe_id"], "niveau": "demande",
        "montant_min_usd": 2000.01, "montant_max_usd": None, "libelle": ">2000 PLA",
        "approbateurs": [{"role_code": "DG", "mode": "conjoint"}, {"role_code": "PRESIDENT", "mode": "conjoint"}]})
    assert r.status_code == 201
    pla = client.get(f"/api/config/paliers?societe_id={ids['societe_id']}", headers=dfi).json()
    assert len(pla["demande"]) == 1
    assert {a["role_code"] for a in pla["demande"][0]["approbateurs"]} == {"DG", "PRESIDENT"}

    # Met à jour un seuil
    params = client.get("/api/config/parametres", headers=dfi).json()
    seuil = next(p for p in params if p["cle"] == "seuil_palier_1_usd")
    r = client.put(f"/api/config/parametres/{seuil['id']}", headers=dfi, json={"valeur": "1500"})
    assert r.json()["valeur"] == "1500"


def test_comptable_valide_et_reclasse(ctx):
    """Une pièce de décaissement est 'en attente' ; le comptable la valide en reclassant un compte."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}

    # Paiement direct 600 → 1 écriture 'en attente' (D 605 / C 571)
    r = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": ids["societe_id"], "objet": "Achat", "mode_decaissement": "paiement_direct",
        "devise": "USD", "lignes": [{"description": "x", "quantite": 1, "prix_unitaire": 600}]})
    rid = r.json()["id"]
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    odp = client.post("/api/ordres-depense", headers=h["DFI"], json={
        "requisition_id": rid, "beneficiaire_tiers_id": ids["beneficiaire_id"]}).json()["id"]
    # 600 → DFI seul : l'ordre est validé dès l'émission, le caissier peut exécuter
    client.post(f"/api/caisse/{ids['caisse_id']}/ouvrir", headers=h["CAISSIER_CENTRAL"],
                json={"fond_initial_usd": 1000000})
    client.post(f"/api/ordres-depense/{odp}/executer", headers=h["CAISSIER_CENTRAL"],
                json={"caisse_id": ids["caisse_id"]})

    # Le comptable voit la pièce en attente
    pend = client.get(f"/api/comptabilite/ecritures?societe_id={ids['societe_id']}", headers=h["COMPTABLE"]).json()
    assert len(pend) == 1
    ecr = pend[0]
    assert ecr["statut"] == "en_attente"
    ligne_charge = next(l for l in ecr["lignes"] if l["sens"] == "D")

    # Validation avec reclassement 605 -> 611
    r = client.post(f"/api/comptabilite/ecritures/{ecr['id']}/valider", headers=h["COMPTABLE"],
                    json={"reclassements": [{"ligne_id": ligne_charge["id"], "compte_numero": "611"}]})
    assert r.json()["statut"] == "valide" and r.json()["reclassements"] == 1

    # Plus rien en attente ; le compte a bien été reclassé
    assert client.get(f"/api/comptabilite/ecritures?societe_id={ids['societe_id']}", headers=h["COMPTABLE"]).json() == []
    valides = client.get(f"/api/comptabilite/ecritures?societe_id={ids['societe_id']}&statut=valide", headers=h["COMPTABLE"]).json()
    assert any(l["compte"] == "611" for l in valides[0]["lignes"])

    # Accès refusé au caissier
    assert client.get(f"/api/comptabilite/ecritures?societe_id={ids['societe_id']}", headers=h["CAISSIER_CENTRAL"]).status_code == 403


def test_socle_grand_livre(ctx):
    """Plan comptable SYSCOHADA, création de compte, saisie manuelle d'OD équilibrée,
    et restitution dans le grand livre + balance."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]

    # Plan comptable chargé (SYSCOHADA) + comptes clés présents
    plan = client.get(f"/api/comptabilite/plan-comptable?societe_id={sid}", headers=h["COMPTABLE"]).json()
    nums = {c["numero"] for c in plan}
    assert {"401", "411", "571", "701", "601", "445"}.issubset(nums)
    assert next(c for c in plan if c["numero"] == "411")["auxiliaire"] is True

    # Filtre par classe
    classe7 = client.get(f"/api/comptabilite/plan-comptable?societe_id={sid}&classe=7", headers=h["COMPTABLE"]).json()
    assert classe7 and all(c["numero"].startswith("7") for c in classe7)

    # Création d'un compte
    r = client.post(f"/api/comptabilite/plan-comptable?societe_id={sid}", headers=h["COMPTABLE"],
                    json={"numero": "6056", "intitule": "Petit outillage"})
    assert r.status_code == 201
    # Doublon refusé
    assert client.post(f"/api/comptabilite/plan-comptable?societe_id={sid}", headers=h["COMPTABLE"],
                       json={"numero": "6056", "intitule": "X"}).status_code == 409

    # Journaux standard présents
    jx = client.get(f"/api/comptabilite/journaux?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert "OD" in {j["code"] for j in jx}

    # Saisie manuelle d'OD équilibrée : D 411 / C 701 (1 200 USD)
    r = client.post(f"/api/comptabilite/ecritures/saisie?societe_id={sid}", headers=h["COMPTABLE"], json={
        "journal_code": "VE", "libelle": "Facture client démo",
        "lignes": [{"sens": "D", "compte": "411", "montant": 1200, "libelle": "Client"},
                   {"sens": "C", "compte": "701", "montant": 1200, "libelle": "Vente"}]})
    assert r.status_code == 201, r.text
    assert r.json()["statut"] == "valide"

    # Déséquilibre refusé
    assert client.post(f"/api/comptabilite/ecritures/saisie?societe_id={sid}", headers=h["COMPTABLE"], json={
        "libelle": "x", "lignes": [{"sens": "D", "compte": "411", "montant": 100},
                                    {"sens": "C", "compte": "701", "montant": 90}]}).status_code == 400
    # Compte hors plan refusé
    assert client.post(f"/api/comptabilite/ecritures/saisie?societe_id={sid}", headers=h["COMPTABLE"], json={
        "libelle": "x", "lignes": [{"sens": "D", "compte": "999999", "montant": 100},
                                    {"sens": "C", "compte": "701", "montant": 100}]}).status_code == 400

    # Grand livre : le 411 porte le mouvement avec code journal VE
    gl = client.get(f"/api/comptabilite/grand-livre?societe_id={sid}&compte=411", headers=h["COMPTABLE"]).json()
    assert gl and gl[0]["compte"] == "411"
    assert gl[0]["mouvements"][0]["journal"] == "VE"
    assert gl[0]["solde"] == 1200

    # Balance : 411 débiteur 1200, 701 créditeur 1200, équilibrée
    bal = client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert bal["equilibre"] is True
    l411 = next(l for l in bal["lignes"] if l["compte"] == "411")
    l701 = next(l for l in bal["lignes"] if l["compte"] == "701")
    assert l411["solde_debiteur"] == 1200 and l701["solde_crediteur"] == 1200


def test_split_validation_piece(ctx):
    """Le comptable peut éclater une ligne sur plusieurs comptes à la validation ;
    l'équilibre D=C est préservé et la provenance est renseignée."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    cid, sid = ids["caisse_id"], ids["societe_id"]

    client.post(f"/api/caisse/{cid}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 0})
    client.post(f"/api/caisse/{cid}/operation", headers=h["CAISSIER_CENTRAL"], json={
        "sens": "entree", "nature": "Recette diverse", "legs": [{"devise": "USD", "montant": 1000}]})

    pend = client.get(f"/api/comptabilite/ecritures?societe_id={sid}", headers=h["COMPTABLE"]).json()
    ecr = pend[0]
    assert ecr["provenance"] == "Caisse"          # regroupé par provenance
    assert " · " in ecr["libelle"]                # libellé explicite (caisse · nature)
    ligne_471 = next(l for l in ecr["lignes"] if l["compte"] == "471")

    # Éclatement du crédit 471 (1000) sur 701 (600) + 706 (400)
    r = client.post(f"/api/comptabilite/ecritures/{ecr['id']}/valider", headers=h["COMPTABLE"], json={
        "splits": [{"ligne_id": ligne_471["id"], "repartition": [
            {"compte_numero": "701", "montant": 600, "libelle": "Ventes"},
            {"compte_numero": "706", "montant": 400, "libelle": "Services"}]}]})
    assert r.status_code == 200, r.text
    assert r.json()["splits"] == 1

    val = client.get(f"/api/comptabilite/ecritures?societe_id={sid}&statut=valide", headers=h["COMPTABLE"]).json()
    e = next(x for x in val if x["numero"] == ecr["numero"])
    comptes = sorted((l["compte"], l["montant_usd"]) for l in e["lignes"])
    assert comptes == [("571", 1000.0), ("701", 600.0), ("706", 400.0)]
    total_d = sum(l["montant_usd"] for l in e["lignes"] if l["sens"] == "D")
    total_c = sum(l["montant_usd"] for l in e["lignes"] if l["sens"] == "C")
    assert total_d == total_c == 1000.0


def test_split_desequilibre_refuse(ctx):
    """Un éclatement dont la somme ≠ montant de la ligne est refusé."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    cid, sid = ids["caisse_id"], ids["societe_id"]
    client.post(f"/api/caisse/{cid}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 0})
    client.post(f"/api/caisse/{cid}/operation", headers=h["CAISSIER_CENTRAL"], json={
        "sens": "entree", "nature": "Recette", "legs": [{"devise": "USD", "montant": 500}]})
    ecr = client.get(f"/api/comptabilite/ecritures?societe_id={sid}", headers=h["COMPTABLE"]).json()[0]
    l471 = next(l for l in ecr["lignes"] if l["compte"] == "471")
    r = client.post(f"/api/comptabilite/ecritures/{ecr['id']}/valider", headers=h["COMPTABLE"], json={
        "splits": [{"ligne_id": l471["id"], "repartition": [
            {"compte_numero": "701", "montant": 300}, {"compte_numero": "706", "montant": 100}]}]})
    assert r.status_code == 400


def test_avance_decaissement_auto_valide_justif_en_attente(ctx):
    """Le décaissement d'avance est auto-validé (D 421 bénéficiaire / C 571) et
    n'encombre pas la file du comptable ; c'est la justification qui y arrive."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]

    r = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": sid, "objet": "Mission terrain", "devise": "USD",
        "lignes": [{"description": "Frais", "quantite": 1, "prix_unitaire": 800}]})
    rid = r.json()["id"]
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    odp = client.post("/api/ordres-depense", headers=h["DFI"], json={
        "requisition_id": rid, "beneficiaire_tiers_id": ids["beneficiaire_id"]}).json()["id"]
    client.post(f"/api/caisse/{ids['caisse_id']}/ouvrir", headers=h["CAISSIER_CENTRAL"],
                json={"fond_initial_usd": 100000})
    client.post(f"/api/ordres-depense/{odp}/executer", headers=h["CAISSIER_CENTRAL"],
                json={"caisse_id": ids["caisse_id"]})

    # Décaissement auto-validé : rien en attente pour le comptable
    pend = client.get(f"/api/comptabilite/ecritures?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert pend == []
    # La pièce de versement est 'valide', débite 421 (agent) avec le tiers
    val = client.get(f"/api/comptabilite/ecritures?societe_id={sid}&statut=valide", headers=h["COMPTABLE"]).json()
    vers = next(e for e in val if e["type_operation"] == "versement_avance")
    d = next(l for l in vers["lignes"] if l["sens"] == "D")
    assert d["compte"] == "421" and d["tiers"]

    # Grand livre auxiliaire du bénéficiaire : solde débiteur = avance en cours
    gl = client.get(f"/api/comptabilite/grand-livre?societe_id={sid}&compte=421&tiers_id={ids['beneficiaire_id']}",
                    headers=h["COMPTABLE"]).json()
    assert gl and gl[0]["solde"] == 800.0

    # Justification → une pièce arrive dans la file du comptable
    with TestSession() as s:
        avance_id = str(s.execute(select(models.Avance)).scalar_one().id)
    client.post("/api/avances/justifier", headers=h["COMPTABLE"], json={
        "avance_id": avance_id, "solde_retourne": 0, "devise_solde": "USD",
        "lignes": [{"nature": "Transport", "devise": "USD", "montant": 800, "compte_impute": "605"}]})
    pend2 = client.get(f"/api/comptabilite/ecritures?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert len(pend2) == 1 and pend2[0]["type_operation"] == "justification_avance"


def test_lettrage_avance_beneficiaire(ctx):
    """Lettrage du compte du bénéficiaire : l'avance (débit) et sa justification
    (crédit) se lettrent ; le solde non lettré tombe à zéro s'il justifie tout."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid, ben = ids["societe_id"], ids["beneficiaire_id"]

    # Décaissement d'une avance de 800 puis justification complète (605)
    r = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": sid, "objet": "Mission", "devise": "USD",
        "lignes": [{"description": "Frais", "quantite": 1, "prix_unitaire": 800}]})
    rid = r.json()["id"]
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    odp = client.post("/api/ordres-depense", headers=h["DFI"], json={
        "requisition_id": rid, "beneficiaire_tiers_id": ben}).json()["id"]
    client.post(f"/api/caisse/{ids['caisse_id']}/ouvrir", headers=h["CAISSIER_CENTRAL"],
                json={"fond_initial_usd": 100000})
    client.post(f"/api/ordres-depense/{odp}/executer", headers=h["CAISSIER_CENTRAL"],
                json={"caisse_id": ids["caisse_id"]})
    with TestSession() as s:
        avance_id = str(s.execute(select(models.Avance)).scalar_one().id)
    client.post("/api/avances/justifier", headers=h["COMPTABLE"], json={
        "avance_id": avance_id, "solde_retourne": 0, "devise_solde": "USD",
        "lignes": [{"nature": "Transport", "devise": "USD", "montant": 800, "compte_impute": "605"}]})

    # Compte 421 du bénéficiaire : 2 lignes non lettrées (D 800 / C 800), solde 0 mais non lettré
    let = client.get(f"/api/comptabilite/lettrage?societe_id={sid}&compte=421&tiers_id={ben}",
                     headers=h["COMPTABLE"]).json()
    assert len(let["lignes"]) == 2 and let["solde"] == 0.0
    assert all(l["lettrage"] is None for l in let["lignes"])
    ids_lignes = [l["id"] for l in let["lignes"]]

    # Lettrage des deux lignes
    r = client.post("/api/comptabilite/lettrage", headers=h["COMPTABLE"],
                    json={"societe_id": sid, "ligne_ids": ids_lignes})
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    assert code == "A"

    # Toutes lettrées ; le filtre 'non lettrés' ne renvoie plus rien
    let2 = client.get(f"/api/comptabilite/lettrage?societe_id={sid}&compte=421&tiers_id={ben}&non_lettres=true",
                      headers=h["COMPTABLE"]).json()
    assert let2["lignes"] == [] and let2["solde_non_lettre"] == 0.0

    # Délettrage possible
    r = client.post("/api/comptabilite/delettrage", headers=h["COMPTABLE"],
                    json={"societe_id": sid, "compte": "421", "code": code})
    assert r.json()["delettre"] == 2


def test_lettrage_desequilibre_refuse(ctx):
    """Un lettrage dont Σdébit ≠ Σcrédit est refusé."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]
    # Deux écritures manuelles sur 411 : D 500 puis C 300 (déséquilibre si lettrées ensemble)
    client.post(f"/api/comptabilite/ecritures/saisie?societe_id={sid}", headers=h["COMPTABLE"], json={
        "libelle": "Facture", "lignes": [{"sens": "D", "compte": "411", "montant": 500},
                                         {"sens": "C", "compte": "701", "montant": 500}]})
    client.post(f"/api/comptabilite/ecritures/saisie?societe_id={sid}", headers=h["COMPTABLE"], json={
        "libelle": "Encaissement partiel", "lignes": [{"sens": "C", "compte": "411", "montant": 300},
                                                      {"sens": "D", "compte": "571", "montant": 300}]})
    let = client.get(f"/api/comptabilite/lettrage?societe_id={sid}&compte=411", headers=h["COMPTABLE"]).json()
    ids_l = [l["id"] for l in let["lignes"]]
    r = client.post("/api/comptabilite/lettrage", headers=h["COMPTABLE"],
                    json={"societe_id": sid, "ligne_ids": ids_l})
    assert r.status_code == 400


def test_rapprochement_bancaire(ctx):
    """Rapprochement du 521 : on pointe les lignes présentes sur le relevé ; les
    lignes non pointées (chèque non débité) expliquent l'écart livre/relevé."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]

    # Encaissement client 1000 (D 521 / C 411) + chèque émis 300 (C 521 / D 601)
    client.post(f"/api/comptabilite/ecritures/saisie?societe_id={sid}", headers=h["COMPTABLE"], json={
        "journal_code": "BQ", "libelle": "Encaissement client",
        "lignes": [{"sens": "D", "compte": "521", "montant": 1000}, {"sens": "C", "compte": "411", "montant": 1000}]})
    client.post(f"/api/comptabilite/ecritures/saisie?societe_id={sid}", headers=h["COMPTABLE"], json={
        "journal_code": "BQ", "libelle": "Chèque fournisseur",
        "lignes": [{"sens": "C", "compte": "521", "montant": 300}, {"sens": "D", "compte": "601", "montant": 300}]})

    ap = client.get(f"/api/comptabilite/rapprochement/a-pointer?societe_id={sid}&compte=521", headers=h["COMPTABLE"]).json()
    assert len(ap["lignes"]) == 2
    assert ap["solde_comptable"] == 700.0 and ap["solde_rapproche"] == 0.0
    ligne_enc = next(l for l in ap["lignes"] if l["debit"] == 1000)

    # Le relevé montre 1000 (le chèque de 300 n'est pas encore débité) → on pointe l'encaissement
    r = client.post("/api/comptabilite/rapprochement", headers=h["COMPTABLE"], json={
        "societe_id": sid, "compte": "521", "date_releve": "2026-07-06", "solde_releve": 1000,
        "ligne_ids": [ligne_enc["id"]]})
    assert r.status_code == 201, r.text
    etat = r.json()
    assert etat["solde_comptable"] == 700.0     # solde livre
    assert etat["solde_rapproche"] == 1000.0    # pointé
    assert etat["ecart"] == 0.0                 # relevé - pointé

    # Il ne reste que le chèque non débité à pointer
    ap2 = client.get(f"/api/comptabilite/rapprochement/a-pointer?societe_id={sid}&compte=521", headers=h["COMPTABLE"]).json()
    assert len(ap2["lignes"]) == 1 and ap2["lignes"][0]["credit"] == 300
    assert ap2["solde_rapproche"] == 1000.0

    # Historique + annulation (dépointage)
    hist = client.get(f"/api/comptabilite/rapprochement?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert len(hist) == 1
    rid = hist[0]["id"]
    r = client.post(f"/api/comptabilite/rapprochement/{rid}/annuler", headers=h["COMPTABLE"])
    assert r.json()["lignes_depointees"] == 1
    ap3 = client.get(f"/api/comptabilite/rapprochement/a-pointer?societe_id={sid}&compte=521", headers=h["COMPTABLE"]).json()
    assert len(ap3["lignes"]) == 2   # tout redevient à pointer


def test_analytique_ventilation_et_rapport(ctx):
    """Ventilation d'une charge sur des sections d'un axe + rapport analytique."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]

    # Axes seedés
    axes = client.get(f"/api/analytique/axes?societe_id={sid}", headers=h["COMPTABLE"]).json()
    centre = next(a for a in axes if a["code"] == "CENTRE")
    assert len(centre["sections"]) >= 3
    admin = next(s for s in centre["sections"] if s["code"] == "ADMIN")
    transp = next(s for s in centre["sections"] if s["code"] == "TRANSP")

    # Création d'un axe + section supplémentaires
    r = client.post(f"/api/analytique/axes?societe_id={sid}", headers=h["COMPTABLE"],
                    json={"code": "PROJET", "libelle": "Projet / chantier"})
    assert r.status_code == 201
    axe_proj = r.json()["id"]
    r = client.post(f"/api/analytique/axes/{axe_proj}/sections", headers=h["COMPTABLE"],
                    json={"code": "CH01", "libelle": "Chantier Kolwezi"})
    assert r.status_code == 201

    # Deux écritures : charge 605 = 1000, produit 701 = 1500
    client.post(f"/api/comptabilite/ecritures/saisie?societe_id={sid}", headers=h["COMPTABLE"], json={
        "libelle": "Achat divers", "lignes": [{"sens": "D", "compte": "605", "montant": 1000},
                                              {"sens": "C", "compte": "571", "montant": 1000}]})
    client.post(f"/api/comptabilite/ecritures/saisie?societe_id={sid}", headers=h["COMPTABLE"], json={
        "libelle": "Vente", "lignes": [{"sens": "D", "compte": "411", "montant": 1500},
                                       {"sens": "C", "compte": "701", "montant": 1500}]})

    # Lignes à ventiler sur l'axe CENTRE (charges 6x + produits 7x)
    lignes = client.get(f"/api/analytique/lignes?societe_id={sid}&axe_id={centre['id']}", headers=h["COMPTABLE"]).json()
    charge = next(l for l in lignes if l["compte"] == "605")
    produit = next(l for l in lignes if l["compte"] == "701")
    assert charge["type"] == "charge" and charge["reste"] == 1000.0

    # Ventile la charge 1000 : 600 Admin + 400 Transport
    r = client.post("/api/analytique/ventiler", headers=h["COMPTABLE"], json={
        "societe_id": sid, "ligne_id": charge["id"], "axe_id": centre["id"],
        "repartition": [{"section_id": admin["id"], "montant": 600},
                        {"section_id": transp["id"], "montant": 400}]})
    assert r.status_code == 200 and r.json()["ventile"] == 1000.0
    # Ventile le produit 1500 sur Admin
    client.post("/api/analytique/ventiler", headers=h["COMPTABLE"], json={
        "societe_id": sid, "ligne_id": produit["id"], "axe_id": centre["id"],
        "repartition": [{"section_id": admin["id"], "montant": 1500}]})

    # Ventilation excédentaire refusée
    r = client.post("/api/analytique/ventiler", headers=h["COMPTABLE"], json={
        "societe_id": sid, "ligne_id": charge["id"], "axe_id": centre["id"],
        "repartition": [{"section_id": admin["id"], "montant": 2000}]})
    assert r.status_code == 400

    # non ventilées : la charge est ventilée à 100 %, ne doit plus apparaître
    nv = client.get(f"/api/analytique/lignes?societe_id={sid}&axe_id={centre['id']}&non_ventilees=true", headers=h["COMPTABLE"]).json()
    assert not any(l["compte"] == "605" for l in nv)

    # Rapport : Admin = produits 1500 - charges 600 = 900 ; Transport = -400
    rap = client.get(f"/api/analytique/rapport?societe_id={sid}&axe_id={centre['id']}", headers=h["COMPTABLE"]).json()
    s_admin = next(l for l in rap["lignes"] if l["code"] == "ADMIN")
    s_transp = next(l for l in rap["lignes"] if l["code"] == "TRANSP")
    assert s_admin["charges"] == 600.0 and s_admin["produits"] == 1500.0 and s_admin["resultat"] == 900.0
    assert s_transp["charges"] == 400.0 and s_transp["resultat"] == -400.0
    assert rap["total_charges"] == 1000.0 and rap["total_produits"] == 1500.0

    # Accès refusé au caissier
    assert client.get(f"/api/analytique/axes?societe_id={sid}", headers=h["CAISSIER_CENTRAL"]).status_code == 403


def test_etats_financiers_ohada(ctx):
    """Compte de résultat + Bilan SYSCOHADA : le résultat relie les deux et le
    bilan est équilibré (Actif = Passif, résultat inclus dans les capitaux propres)."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]

    def saisie(lib, lignes, jc="OD"):
        r = client.post(f"/api/comptabilite/ecritures/saisie?societe_id={sid}", headers=h["COMPTABLE"],
                        json={"journal_code": jc, "libelle": lib, "lignes": lignes})
        assert r.status_code == 201, r.text

    # Apport en capital 10 000 (D 521 / C 101)
    saisie("Apport capital", [{"sens": "D", "compte": "521", "montant": 10000},
                              {"sens": "C", "compte": "101", "montant": 10000}], "BQ")
    # Vente 3 000 à crédit (D 411 / C 701)
    saisie("Vente ciment", [{"sens": "D", "compte": "411", "montant": 3000},
                            {"sens": "C", "compte": "701", "montant": 3000}], "VE")
    # Achat 1 000 réglé banque (D 601 / C 521)
    saisie("Achat marchandises", [{"sens": "D", "compte": "601", "montant": 1000},
                                  {"sens": "C", "compte": "521", "montant": 1000}], "AC")

    # Compte de résultat : CA 3000, charges 1000, résultat net 2000
    cr = client.get(f"/api/comptabilite/compte-resultat?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert cr["chiffre_affaires"] == 3000.0
    assert cr["resultat_net"] == 2000.0
    re = next(s for s in cr["sections"] if s.get("solde") == "Résultat d'exploitation")
    assert re["montant"] == 2000.0

    # Bilan équilibré : Actif = Passif = 12 000 ; résultat 2000 dans les capitaux propres
    bl = client.get(f"/api/comptabilite/bilan?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert bl["equilibre"] is True and bl["ecart"] == 0.0
    assert bl["actif"]["total"] == 12000.0 and bl["passif"]["total"] == 12000.0
    assert bl["actif"]["tresorerie"] == 9000.0          # 521 = 10000 - 1000
    assert bl["actif"]["circulant"]["creances"] == 3000.0   # 411
    assert bl["passif"]["capitaux_propres"]["resultat_net"] == 2000.0
    assert bl["passif"]["capitaux_propres"]["total"] == 12000.0  # capital 10000 + résultat 2000

    # Comparatif N-1 : aucune écriture l'an dernier → colonnes N-1 à zéro
    assert cr["resultat_net_n1"] == 0.0
    assert bl["actif"]["total_n1"] == 0.0

    # TFT : trésorerie ouverture 0 → clôture = variation ; financement = capital 10 000
    tft = client.get(f"/api/comptabilite/tft?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert tft["tresorerie_ouverture"] == 0.0
    fin = next(f for f in tft["flux"] if "financement" in f["titre"])
    assert fin["total"] == 10000.0
    assert tft["tresorerie_cloture"] == 9000.0    # 521 réel
    assert tft["controle"] is True

    # Cockpit DAF
    ck = client.get(f"/api/comptabilite/cockpit?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert ck["tresorerie"]["banque"] == 9000.0
    assert ck["creances_clients"] == 3000.0
    assert ck["chiffre_affaires"] == 3000.0 and ck["resultat"] == 2000.0

    # Accès refusé au caissier
    assert client.get(f"/api/comptabilite/bilan?societe_id={sid}", headers=h["CAISSIER_CENTRAL"]).status_code == 403


def test_cycle_commercial(ctx):
    """Achat → stock (CUMP) → vente : TVA auto, écritures, marge, et résultat
    correct grâce à l'inventaire permanent (variation de stock)."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]

    arts = client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json()
    cim = next(a for a in arts if a["code"] == "CIM50")
    tiers = client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json()
    fourn = next(t for t in tiers if t["type"] == "fournisseur")
    client_btp = next(t for t in tiers if t["code"] == "C-BTP")

    # Achat 100 sacs @ 11 → HT 1100, TVA 176, TTC 1276
    r = client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"],
        "lignes": [{"article_id": cim["id"], "qte": 100, "prix_unitaire": 11}]})
    assert r.status_code == 201, r.text
    fa = r.json()
    assert (fa["total_ht"], fa["total_tva"], fa["total_ttc"]) == (1100.0, 176.0, 1276.0)
    assert fa["numero"].startswith("FA-")

    stk = client.get(f"/api/commercial/stock?societe_id={sid}", headers=h["COMPTABLE"]).json()
    s_cim = next(l for l in stk["lignes"] if l["code"] == "CIM50")
    assert s_cim["stock_qte"] == 100.0 and s_cim["stock_valeur"] == 1100.0 and s_cim["cump"] == 11.0

    # Vente 60 sacs @ 14 → HT 840, TVA 134.4 ; coût 660 (CUMP 11), marge 180
    r = client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "vente", "tiers_id": client_btp["id"],
        "lignes": [{"article_id": cim["id"], "qte": 60, "prix_unitaire": 14}]})
    assert r.status_code == 201, r.text
    fv = r.json()
    assert (fv["total_ht"], fv["total_tva"]) == (840.0, 134.4)
    assert fv["cout_ventes"] == 660.0 and fv["marge"] == 180.0

    stk2 = client.get(f"/api/commercial/stock?societe_id={sid}", headers=h["COMPTABLE"]).json()
    s_cim2 = next(l for l in stk2["lignes"] if l["code"] == "CIM50")
    assert s_cim2["stock_qte"] == 40.0 and s_cim2["stock_valeur"] == 440.0

    # Stock insuffisant → refus
    r = client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "vente", "tiers_id": client_btp["id"],
        "lignes": [{"article_id": cim["id"], "qte": 1000, "prix_unitaire": 14}]})
    assert r.status_code == 409

    # Écritures : le 411 client porte le TTC ; TVA collectée sur 4431
    gl = client.get(f"/api/comptabilite/grand-livre?societe_id={sid}&compte=411", headers=h["COMPTABLE"]).json()
    assert any(abs(m["debit"] - 974.4) < 0.01 for c in gl for m in c["mouvements"])

    # Résultat correct grâce à l'inventaire permanent : 840 (vente) − 660 (coût) = 180
    cr = client.get(f"/api/comptabilite/compte-resultat?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert cr["resultat_net"] == 180.0
    assert cr["chiffre_affaires"] == 840.0

    # Accès refusé au caissier
    assert client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["CAISSIER_CENTRAL"]).status_code == 403


def test_rendu_caisse_coherent_avec_571(ctx):
    """Le rendu de monnaie à la justification entre bien EN CAISSE (session ouverte)
    ET au grand livre 571 — les deux restent cohérents."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid, ben, cid = ids["societe_id"], ids["beneficiaire_id"], ids["caisse_id"]

    rid = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": sid, "objet": "Mission", "devise": "USD",
        "lignes": [{"description": "Frais", "quantite": 1, "prix_unitaire": 800}]}).json()["id"]
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    odp = client.post("/api/ordres-depense", headers=h["DFI"], json={
        "requisition_id": rid, "beneficiaire_tiers_id": ben}).json()["id"]
    client.post(f"/api/caisse/{cid}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 100000})
    client.post(f"/api/ordres-depense/{odp}/executer", headers=h["CAISSIER_CENTRAL"], json={"caisse_id": cid})
    with TestSession() as s:
        avance_id = str(s.execute(select(models.Avance)).scalar_one().id)

    # Justification : 700 de dépense + 100 rendus en caisse
    r = client.post("/api/avances/justifier", headers=h["COMPTABLE"], json={
        "avance_id": avance_id, "solde_retourne": 100, "devise_solde": "USD",
        "lignes": [{"nature": "Transport", "devise": "USD", "montant": 700, "compte_impute": "605"}]})
    assert r.status_code == 201, r.text

    # 1) Le rendu est DANS la caisse (journal de la session ouverte)
    jr = client.get(f"/api/caisse/{cid}/journal", headers=h["CAISSIER_CENTRAL"]).json()
    retours = [m for m in jr["mouvements"] if m["nature"] == "Retour d'avance"]
    assert len(retours) == 1 and retours[0]["sens"] == "entree" and retours[0]["montant"] == 100.0

    # 2) Le rendu est AUSSI au grand livre 571 (débit 100)
    gl = client.get(f"/api/comptabilite/grand-livre?societe_id={sid}&compte=571", headers=h["COMPTABLE"]).json()
    mvts = gl[0]["mouvements"] if gl else []
    assert any(abs(m["debit"] - 100.0) < 0.01 and "Retour" in (m["libelle"] or "") for m in mvts)

    # Caisse fermée → le rendu est refusé (on ne peut pas désynchroniser 571 et caisse)
    rid2 = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": sid, "objet": "Mission 2", "devise": "USD",
        "lignes": [{"description": "Frais", "quantite": 1, "prix_unitaire": 500}]}).json()["id"]
    client.post(f"/api/requisitions/{rid2}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{rid2}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    odp2 = client.post("/api/ordres-depense", headers=h["DFI"], json={"requisition_id": rid2, "beneficiaire_tiers_id": ben}).json()["id"]
    client.post(f"/api/ordres-depense/{odp2}/executer", headers=h["CAISSIER_CENTRAL"], json={"caisse_id": cid})
    with TestSession() as s:
        av2 = str([a.id for a in s.execute(select(models.Avance)).scalars().all() if str(a.id) != avance_id][0])
    cl = client.post(f"/api/caisse/{cid}/cloturer", headers=h["CAISSIER_CENTRAL"],
                     json={"physique_usd": 0, "physique_cdf": 0, "commentaire": "clôture test"})
    assert cl.status_code == 200, cl.text
    r = client.post("/api/avances/justifier", headers=h["COMPTABLE"], json={
        "avance_id": av2, "solde_retourne": 50, "devise_solde": "USD",
        "lignes": [{"nature": "Frais", "devise": "USD", "montant": 450, "compte_impute": "605"}]})
    assert r.status_code == 409   # caisse fermée : rendu impossible


def test_justification_marchandises_entree_stock(ctx):
    """Circuit 1 : une avance justifiée par des marchandises fait entrer le stock
    au coût d'acquisition (D 31 + TVA / C 421), avec création d'article à la volée."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid, ben = ids["societe_id"], ids["beneficiaire_id"]

    # Avance de 800 (achat de marchandises urgent)
    rid = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": sid, "objet": "Achat ciment urgent", "devise": "USD", "nature": "marchandise",
        "lignes": [{"description": "Ciment", "quantite": 1, "prix_unitaire": 800}]}).json()["id"]
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    odp = client.post("/api/ordres-depense", headers=h["DFI"], json={
        "requisition_id": rid, "beneficiaire_tiers_id": ben}).json()["id"]
    client.post(f"/api/caisse/{ids['caisse_id']}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 100000})
    client.post(f"/api/ordres-depense/{odp}/executer", headers=h["CAISSIER_CENTRAL"], json={"caisse_id": ids["caisse_id"]})
    with TestSession() as s:
        avance_id = str(s.execute(select(models.Avance)).scalar_one().id)

    # La nature « marchandise » de la réquisition se propage jusqu'à l'avance
    avs = client.get(f"/api/avances?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert avs[0]["nature"] == "marchandise"

    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")

    # Justification par marchandises : 100 sacs @ 6 + transport 40 → coût 640, TVA 102.4, solde 57.6
    r = client.post("/api/avances/justifier", headers=h["COMPTABLE"], json={
        "avance_id": avance_id, "solde_retourne": 57.6, "devise_solde": "USD",
        "marchandises": [{"article_id": cim["id"], "qte": 100, "prix_unitaire": 6}],
        "frais": [{"libelle": "Transport", "montant_ht": 40}], "repartition": "quantite"})
    assert r.status_code == 201, r.text
    assert r.json()["ecart_usd"] == "0.00"

    # Stock CIM50 entré au coût d'acquisition : 100 sacs, valeur 640, CUMP 6.40
    s_cim = next(l for l in client.get(f"/api/commercial/stock?societe_id={sid}", headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s_cim["stock_qte"] == 100.0 and s_cim["stock_valeur"] == 640.0 and s_cim["cump"] == 6.4

    # Comptabilité : 31 mouvementé (640), avance 421 apurée, balance équilibrée
    bal = {l["compte"]: l for l in client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()["lignes"]}
    assert bal["31"]["solde_debiteur"] == 640.0
    assert "601" in bal and "603" in bal            # convention (b) : achat 601 (prix) + variation 603 (coût)
    assert bal["601"]["solde_debiteur"] == 600.0    # prix d'achat HT (100 × 6)
    assert "421" not in bal or bal["421"]["solde_debiteur"] == 0.0   # avance apurée
    assert client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()["equilibre"] is True

    # Justification 100% marchandises avec création d'article à la volée (autre avance)
    rid2 = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": sid, "objet": "Achat clous", "devise": "USD",
        "lignes": [{"description": "Clous", "quantite": 1, "prix_unitaire": 116}]}).json()["id"]
    client.post(f"/api/requisitions/{rid2}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{rid2}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    odp2 = client.post("/api/ordres-depense", headers=h["DFI"], json={"requisition_id": rid2, "beneficiaire_tiers_id": ben}).json()["id"]
    client.post(f"/api/ordres-depense/{odp2}/executer", headers=h["CAISSIER_CENTRAL"], json={"caisse_id": ids["caisse_id"]})
    with TestSession() as s:
        av2 = str([a.id for a in s.execute(select(models.Avance)).scalars().all() if str(a.id) != avance_id][0])
    r = client.post("/api/avances/justifier", headers=h["COMPTABLE"], json={
        "avance_id": av2, "devise_solde": "USD",
        "marchandises": [{"code": "CLOU", "designation": "Clous 10cm (kg)", "unite": "kg", "qte": 50, "prix_unitaire": 2}]})
    assert r.status_code == 201, r.text   # 50*2=100 HT + 16 TVA = 116 = avance
    arts = client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert any(a["code"] == "CLOU" and a["stock_qte"] == 50.0 for a in arts)   # article créé à la volée + stock


def test_pos_cession_caisse_principale_avec_ecart(ctx):
    """Circuit POS : la vente alimente la caisse temporaire (compte 5711) ; à la remise,
    une cession part vers la caisse principale et reste EN ATTENTE chez le caissier
    principal, qui valide à réception réelle des fonds — l'écart (manquant) va en 658."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid, princ_id = ids["societe_id"], ids["caisse_id"]
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")
    pv = client.get(f"/api/commercial/points-vente?societe_id={sid}", headers=h["COMPTABLE"]).json()[0]

    # La caisse POS a bien son propre compte (caisse temporaire), la centrale est principale
    caisses = {c["id"]: c for c in client.get(f"/api/caisses?societe_id={sid}", headers=h["CAISSIER_CENTRAL"]).json()}
    pos_caisse_id = pv["caisse_id"]
    assert caisses[pos_caisse_id]["compte"] == "5711" and caisses[pos_caisse_id]["est_principale"] is False
    assert caisses[princ_id]["est_principale"] is True

    # Stock puis vente POS 4 @ 15 → 5711 débité du TTC 69,6
    client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"], "lignes": [{"article_id": cim["id"], "qte": 100, "prix_unitaire": 10}]})
    detail = next(l for l in client.get(f"/api/commercial/listes-prix?societe_id={sid}", headers=h["COMPTABLE"]).json() if l["code"] == "DETAIL")
    client.post(f"/api/commercial/listes-prix/{detail['id']}/tarifs", headers=h["COMPTABLE"], json={"article_id": cim["id"], "prix": 15})
    client.post(f"/api/caisse/{pos_caisse_id}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 0})
    client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"], "montant_recu": 69.6, "lignes": [{"article_id": cim["id"], "qte": 4}]})

    # Remise : cession POS → caisse principale (les fonds quittent la caisse temporaire)
    t = client.post("/api/transferts", headers=h["CAISSIER_CENTRAL"], json={
        "societe_id": sid, "source_type": "caisse", "source_id": pos_caisse_id,
        "dest_type": "caisse", "dest_id": princ_id, "devise": "USD", "montant": 69.6,
        "motif": "Remise recette POS"}).json()
    assert t["statut"] == "a_valider"

    # Le caissier principal ouvre sa caisse et valide en ne recevant réellement que 69,0
    client.post(f"/api/caisse/{princ_id}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 0})
    r = client.post(f"/api/transferts/{t['id']}/valider", headers=h["CAISSIER_CENTRAL"], json={"montant_recu": 69.0})
    assert r.status_code == 200, r.text
    assert r.json()["ecart_usd"] == 0.6

    # Comptabilité : 5711 soldé (69,6 in − 69,6 out), 571 = 69,0, manquant 658 = 0,6, équilibré
    bal = {l["compte"]: l for l in client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()["lignes"]}
    assert round(bal.get("5711", {}).get("solde_debiteur", 0) - bal.get("5711", {}).get("solde_crediteur", 0), 2) == 0.0
    assert bal["571"]["solde_debiteur"] == 69.0
    assert bal["658"]["solde_debiteur"] == 0.6
    assert client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()["equilibre"] is True

    # La caisse principale a reçu physiquement 69,0 (le montant réel)
    jr = client.get(f"/api/caisse/{princ_id}/journal", headers=h["CAISSIER_CENTRAL"]).json()
    assert jr["soldes"]["USD"] == 69.0


def test_pos_vente_comptant(ctx):
    """Vente POS : prix depuis la liste du point de vente, sortie de stock (CUMP),
    encaissement en caisse du PV, écriture D caisse / C ventes + TVA, monnaie & points."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")
    pv = client.get(f"/api/commercial/points-vente?societe_id={sid}", headers=h["COMPTABLE"]).json()[0]
    detail = next(l for l in client.get(f"/api/commercial/listes-prix?societe_id={sid}", headers=h["COMPTABLE"]).json() if l["code"] == "DETAIL")

    # Article : points fidélité 2/unité, commission 5 %, prix détail 15
    client.patch(f"/api/commercial/articles/{cim['id']}", headers=h["COMPTABLE"], json={"points_fidelite": 2, "taux_commission": 5})
    client.post(f"/api/commercial/listes-prix/{detail['id']}/tarifs", headers=h["COMPTABLE"], json={"article_id": cim["id"], "prix": 15})
    # Stock : acheter 100 @ 10 (CUMP 10)
    client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"], "lignes": [{"article_id": cim["id"], "qte": 100, "prix_unitaire": 10}]})

    # Vente sans caisse ouverte → refus
    r = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"], "lignes": [{"article_id": cim["id"], "qte": 4}]})
    assert r.status_code == 409

    # Ouvrir la caisse du POS puis vendre 4 sacs, reçu 100
    pos_caisse_id = pv["caisse_id"]
    client.post(f"/api/caisse/{pos_caisse_id}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 50})
    r = client.post(f"/api/commercial/pos/vente?societe_id={sid}", headers=h["CAISSIER_CENTRAL"], json={
        "point_vente_id": pv["id"], "montant_recu": 100, "lignes": [{"article_id": cim["id"], "qte": 4}]})
    assert r.status_code == 201, r.text
    tk = r.json()
    # Prix détail 15 → HT 60, TVA 16% = 9.6, TTC 69.6 ; reçu 100 → monnaie 30.4
    assert tk["total_ht"] == 60.0 and tk["total_tva"] == 9.6 and tk["total_ttc"] == 69.6
    assert tk["monnaie"] == 30.4
    assert tk["marge"] == 20.0                 # 60 (vente HT) - 40 (coût CUMP 10 × 4)
    assert tk["points_fidelite"] == 8.0        # 4 × 2
    assert tk["commission"] == 3.0             # 60 × 5%

    # Stock diminué de 4
    s = next(l for l in client.get(f"/api/commercial/stock?societe_id={sid}", headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s["stock_qte"] == 96.0

    # La vente est bien entrée EN CAISSE du POS : 100 reçus, 30,4 rendus (net 69,6)
    jr = client.get(f"/api/caisse/{pos_caisse_id}/journal", headers=h["CAISSIER_CENTRAL"]).json()
    assert any(m["nature"] == "Vente POS" and m["montant"] == 100.0 for m in jr["mouvements"])
    assert any(m["nature"] == "Monnaie rendue POS" and m["montant"] == 30.4 for m in jr["mouvements"])
    assert jr["soldes"]["USD"] == 119.6        # fond 50 + 100 − 30.4

    # Comptabilité : 571 débité du TTC, 701 crédité HT, balance équilibrée
    bal = {l["compte"]: l for l in client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()["lignes"]}
    assert bal["5711"]["solde_debiteur"] == 69.6 and bal["701"]["solde_crediteur"] == 60.0   # caisse temporaire POS
    assert client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()["equilibre"] is True


def test_listes_prix_et_points_vente(ctx):
    """Listes de prix par point de vente : un article a un prix différent selon la
    liste, et le point de vente résout ce prix (sinon le prix par défaut)."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")

    # Listes seedées + point de vente
    listes = client.get(f"/api/commercial/listes-prix?societe_id={sid}", headers=h["COMPTABLE"]).json()
    detail = next(l for l in listes if l["code"] == "DETAIL")
    gros = next(l for l in listes if l["code"] == "GROS")
    pv = client.get(f"/api/commercial/points-vente?societe_id={sid}", headers=h["COMPTABLE"]).json()[0]
    assert pv["code"] == "POS-KLZ" and pv["liste_prix"] == "Tarif détail"

    # CIM50 : 15 en détail, 12.5 en gros (prix de vente par défaut = 14)
    client.post(f"/api/commercial/listes-prix/{detail['id']}/tarifs", headers=h["COMPTABLE"],
                json={"article_id": cim["id"], "prix": 15})
    client.post(f"/api/commercial/listes-prix/{gros['id']}/tarifs", headers=h["COMPTABLE"],
                json={"article_id": cim["id"], "prix": 12.5})

    # Résolution du prix
    p_pv = client.get(f"/api/commercial/articles/{cim['id']}/prix?point_vente_id={pv['id']}", headers=h["COMPTABLE"]).json()
    assert p_pv["prix"] == 15.0 and p_pv["source"] == "liste"   # via la liste du POS
    p_gros = client.get(f"/api/commercial/articles/{cim['id']}/prix?liste_prix_id={gros['id']}", headers=h["COMPTABLE"]).json()
    assert p_gros["prix"] == 12.5

    # Article sans tarif dans une liste → prix de vente par défaut
    autre = client.post(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"], json={
        "code": "SABLE", "designation": "Sable", "prix_vente": 25, "gere_stock": False}).json()
    p_def = client.get(f"/api/commercial/articles/{autre['id']}/prix?liste_prix_id={detail['id']}", headers=h["COMPTABLE"]).json()
    assert p_def["prix"] == 25.0 and p_def["source"] == "défaut"

    # La grille des tarifs liste bien l'article défini
    tf = client.get(f"/api/commercial/listes-prix/{detail['id']}/tarifs", headers=h["COMPTABLE"]).json()
    row = next(a for a in tf["articles"] if a["code"] == "CIM50")
    assert row["prix"] == 15.0 and row["defini"] is True and row["prix_defaut"] == 14.0

    # Accès refusé au caissier
    assert client.get(f"/api/commercial/listes-prix?societe_id={sid}", headers=h["CAISSIER_CENTRAL"]).status_code == 403


def test_article_tva_configurable_et_exoneration(ctx):
    """La TVA n'est plus imposée : taux par défaut = config société, et un article
    non assujetti ne génère aucune TVA (achat comme vente)."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]
    tiers = client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json()
    fourn = next(t for t in tiers if t["type"] == "fournisseur")["id"]
    cli = next(t for t in tiers if t["type"] == "client")["id"]

    # Taux de TVA par défaut de la société = 18 %
    client.post(f"/api/comptabilite/comptes-config?societe_id={sid}", headers=h["COMPTABLE"],
                json={"config": {}, "tva_taux_defaut": 18})

    # Article assujetti sans taux précisé → hérite du défaut 18 %
    a1 = client.post(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"], json={
        "code": "ART18", "designation": "Article standard", "gere_stock": False}).json()
    assert a1["assujetti_tva"] is True and a1["taux_tva"] == 18.0

    # Article NON assujetti → taux forcé à 0
    a2 = client.post(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"], json={
        "code": "EXO", "designation": "Produit exonéré", "assujetti_tva": False,
        "prix_achat": 5, "prix_vente": 8, "categorie": "Denrées", "code_barres": "600123",
        "taux_commission": 2, "points_fidelite": 1}).json()
    assert a2["assujetti_tva"] is False and a2["taux_tva"] == 0.0
    assert a2["categorie"] == "Denrées" and a2["taux_commission"] == 2.0 and a2["points_fidelite"] == 1.0

    # Achat de l'exonéré → aucune TVA
    fa = client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn, "lignes": [{"article_id": a2["id"], "qte": 10, "prix_unitaire": 5}]}).json()
    assert fa["total_tva"] == 0.0 and fa["total_ttc"] == 50.0

    # Vente de l'exonéré → aucune TVA (même si on tenterait de forcer un taux)
    fv = client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "vente", "tiers_id": cli, "lignes": [{"article_id": a2["id"], "qte": 5, "prix_unitaire": 8, "taux_tva": 16}]}).json()
    assert fv["total_tva"] == 0.0 and fv["total_ttc"] == 40.0


def test_commande_controle_3voies(ctx):
    """Rapprochement 3 voies sur la commande : commandé / reçu / facturé, avec écarts,
    + date de livraison prévue et détail de réception."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")

    # Commande 200 @ 11 = 2200, avec date de livraison + réf fournisseur
    cmd = client.post(f"/api/commercial/commandes?societe_id={sid}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "date_livraison_prevue": "2026-08-01", "reference_fournisseur": "BC-EXT-42",
        "lignes": [{"article_id": cim["id"], "qte": 200, "prix_unitaire": 11}]}).json()
    assert cmd["date_livraison_prevue"] == "2026-08-01" and cmd["reference_fournisseur"] == "BC-EXT-42"

    # Réception partielle 100
    rec = client.post(f"/api/commercial/commandes/{cmd['id']}/receptionner", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_commande_id": cmd["lignes"][0]["id"], "qte_recue": 100}]}).json()

    # 3 voies après réception : commandé 2200, reçu 1100, facturé 0
    d = client.get(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"]).json()
    assert d["controle"]["commande_ht"] == 2200.0 and d["controle"]["recu_ht"] == 1100.0 and d["controle"]["facture_ht"] == 0.0
    assert d["controle"]["ecart_recu"] == -1100.0        # reste à recevoir
    assert len(d["receptions"]) == 1 and d["receptions"][0]["facture"] is None

    # Facturation de la réception → facturé 1100, écart facture nul
    client.post(f"/api/commercial/receptions/{rec['id']}/facturer", headers=h["COMPTABLE"])
    d2 = client.get(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"]).json()
    assert d2["controle"]["facture_ht"] == 1100.0 and d2["controle"]["ecart_facture"] == 0.0
    assert d2["receptions"][0]["facture"] is not None

    # Détail de réception accessible
    rd = client.get(f"/api/commercial/receptions/{rec['id']}", headers=h["COMPTABLE"]).json()
    assert rd["numero"] == rec["numero"] and rd["lignes"][0]["qte"] == 100.0


def test_revue_hybride_achats_en_attente_ventes_directes(ctx):
    """Revue comptable hybride : une facture d'achat génère une pièce EN ATTENTE
    (le comptable valide), tandis qu'une facture de vente part directement (valide)."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]
    arts = client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json()
    cim = next(a for a in arts if a["code"] == "CIM50")
    tiers = client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json()
    fourn = next(t for t in tiers if t["type"] == "fournisseur")
    cli = next(t for t in tiers if t["type"] == "client")

    pend0 = len(client.get(f"/api/comptabilite/ecritures?societe_id={sid}", headers=h["COMPTABLE"]).json())

    # Achat → pièce en attente (revue par défaut activée pour les achats)
    fa = client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"], "lignes": [{"article_id": cim["id"], "qte": 40, "prix_unitaire": 11}]}).json()
    pend1 = client.get(f"/api/comptabilite/ecritures?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert len(pend1) == pend0 + 1                     # exactement une pièce d'achat en attente
    assert any(fa["numero"] in (e.get("source") or "") or fa["numero"] in (e.get("libelle") or "") for e in pend1)

    # Vente → directe (valide), n'ajoute aucune pièce en attente
    client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "vente", "tiers_id": cli["id"], "lignes": [{"article_id": cim["id"], "qte": 5, "prix_unitaire": 14}]})
    pend2 = client.get(f"/api/comptabilite/ecritures?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert len(pend2) == len(pend1)

    # Config : on désactive la revue des achats → l'achat suivant part directement
    r = client.post(f"/api/comptabilite/revue-config?societe_id={sid}", headers=h["DFI"], json={"revue_achats": False})
    assert r.status_code == 200, r.text
    client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"], "lignes": [{"article_id": cim["id"], "qte": 10, "prix_unitaire": 11}]})
    pend3 = client.get(f"/api/comptabilite/ecritures?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert len(pend3) == len(pend2)                    # plus de pièce en attente ajoutée


def test_commande_editable_puis_verrouillee(ctx):
    """Une commande est modifiable/annulable tant qu'aucune réception ne l'entame ;
    après réception elle est verrouillée. La facture porte le n° fournisseur saisi."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")

    cmd = client.post(f"/api/commercial/commandes?societe_id={sid}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "lignes": [{"article_id": cim["id"], "qte": 50, "prix_unitaire": 11}]}).json()
    assert cmd["modifiable"] is True

    # Modification (qté + prix) tant que non entamée
    edit = client.put(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "reference_fournisseur": "DEVIS-9",
        "lignes": [{"article_id": cim["id"], "qte": 80, "prix_unitaire": 10}]})
    assert edit.status_code == 200, edit.text
    ed = edit.json()
    assert ed["total_ht"] == 800.0 and ed["reference_fournisseur"] == "DEVIS-9"

    # Réception partielle → verrouillage
    rec = client.post(f"/api/commercial/commandes/{cmd['id']}/receptionner", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_commande_id": ed["lignes"][0]["id"], "qte_recue": 30}]}).json()
    d = client.get(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"]).json()
    assert d["modifiable"] is False
    assert client.put(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "lignes": [{"article_id": cim["id"], "qte": 5, "prix_unitaire": 1}]}).status_code == 409
    assert client.post(f"/api/commercial/commandes/{cmd['id']}/annuler", headers=h["COMPTABLE"]).status_code == 409

    # Facturation avec n° de facture fournisseur + échéance saisis dans l'aperçu
    fac = client.post(f"/api/commercial/receptions/{rec['id']}/facturer", headers=h["COMPTABLE"], json={
        "reference": "FT-2026-0453", "date_facture": "2026-07-14", "echeance": "2026-08-14"}).json()
    assert fac["reference"] == "FT-2026-0453" and fac["echeance"] == "2026-08-14"

    # Une commande vierge distincte reste annulable
    cmd2 = client.post(f"/api/commercial/commandes?societe_id={sid}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "lignes": [{"article_id": cim["id"], "qte": 5, "prix_unitaire": 11}]}).json()
    ann = client.post(f"/api/commercial/commandes/{cmd2['id']}/annuler", headers=h["COMPTABLE"])
    assert ann.status_code == 200 and ann.json()["statut"] == "annulee"


def test_achats_historique_unifie(ctx):
    """L'historique des achats liste toutes les entrées quelle que soit l'origine :
    facture directe et achat via avance à justifier apparaissent ensemble."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid, ben, cid = ids["societe_id"], ids["beneficiaire_id"], ids["caisse_id"]
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")

    # 1) Achat direct (facture)
    fa = client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"], "lignes": [{"article_id": cim["id"], "qte": 30, "prix_unitaire": 11}]}).json()

    # 2) Achat via avance à justifier (marchandises)
    rid = client.post("/api/requisitions", headers=h["COMPTABLE"], json={
        "societe_id": sid, "objet": "Achat urgent", "devise": "USD", "nature": "marchandise",
        "lignes": [{"description": "Ciment", "quantite": 1, "prix_unitaire": 116}]}).json()["id"]
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["DG"], json={"decision": "valide"})
    client.post(f"/api/requisitions/{rid}/valider-demande", headers=h["ADMIN"], json={"decision": "valide"})
    odp = client.post("/api/ordres-depense", headers=h["DFI"], json={"requisition_id": rid, "beneficiaire_tiers_id": ben}).json()["id"]
    client.post(f"/api/caisse/{cid}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 100000})
    client.post(f"/api/ordres-depense/{odp}/executer", headers=h["CAISSIER_CENTRAL"], json={"caisse_id": cid})
    with TestSession() as s:
        avance_id = str(s.execute(select(models.Avance)).scalar_one().id)
    client.post("/api/avances/justifier", headers=h["COMPTABLE"], json={
        "avance_id": avance_id, "devise_solde": "USD",
        "marchandises": [{"article_id": cim["id"], "qte": 10, "prix_unitaire": 10}]})  # 100 HT + 16 TVA

    hist = client.get(f"/api/commercial/achats-historique?societe_id={sid}", headers=h["COMPTABLE"]).json()
    origines = {a["origine"] for a in hist}
    assert "Facture d'achat" in origines and "Avance à justifier" in origines
    fac_row = next(a for a in hist if a["reference"] == fa["numero"])
    assert fac_row["tiers"] == fourn["nom"] and fac_row["total_valeur"] == 330.0

    # Synthèse ventes accessible (aucune vente ici → zéros)
    syn = client.get(f"/api/commercial/ventes-synthese?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert syn["chiffre_affaires"] == 0.0 and "palmares" in syn


def test_circuit2_commande_reception_facture(ctx):
    """Circuit 2 : commande → réception (D 31/C 408, stock in) → facture (D 408+TVA/C 401).
    Réception partielle, frais annexes, et le 408 se solde entre réception et facture."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")

    # Commande de 200 sacs @ 11
    r = client.post(f"/api/commercial/commandes?societe_id={sid}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "lignes": [{"article_id": cim["id"], "qte": 200, "prix_unitaire": 11}]})
    assert r.status_code == 201, r.text
    cmd = r.json()
    assert cmd["numero"].startswith("CMD-") and cmd["statut"] == "envoyee"
    lc_id = cmd["lignes"][0]["id"]

    # Transporteur distinct (le frais n'est PAS la dette du fournisseur des marchandises)
    transp = client.post(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "fournisseur", "code": "TRANSP2", "nom": "Transporteur Y"}).json()

    # Réception partielle : 100 sacs + transport 100 à crédit chez Y → coût 1200, CUMP 12
    r = client.post(f"/api/commercial/commandes/{cmd['id']}/receptionner", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_commande_id": lc_id, "qte_recue": 100}],
        "frais": [{"libelle": "Transport", "compte": "6085", "montant_ht": 100,
                   "mode": "credit", "tiers_id": transp["id"]}], "repartition": "quantite"})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["total_valeur"] == 1200.0 and rec["lignes"][0]["cout"] == 1200.0

    s = next(l for l in client.get(f"/api/commercial/stock?societe_id={sid}", headers=h["COMPTABLE"]).json()["lignes"] if l["code"] == "CIM50")
    assert s["stock_qte"] == 100.0 and s["stock_valeur"] == 1200.0 and s["cump"] == 12.0

    # La commande est « réceptionnée » partiellement (reste 100)
    cmd2 = client.get(f"/api/commercial/commandes/{cmd['id']}", headers=h["COMPTABLE"]).json()
    assert cmd2["statut"] == "receptionnee" and cmd2["lignes"][0]["reste"] == 100.0

    # Après réception : stock 31 = 1200 (coût), 408 = 1100 (marchandises SEULES),
    # le transport a sa propre dette 401(Y) = 116 (100 + TVA), 603 crédité des frais incorporés (100)
    def bal():
        return {l["compte"]: l for l in client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()["lignes"]}
    b1 = bal()
    assert b1["31"]["solde_debiteur"] == 1200.0 and b1["408"]["solde_crediteur"] == 1100.0
    assert b1["6085"]["solde_debiteur"] == 100.0 and b1["603"]["solde_crediteur"] == 100.0

    # Facturation du fournisseur des marchandises : marchandises SEULES (frais déjà comptabilisés)
    r = client.post(f"/api/commercial/receptions/{rec['id']}/facturer", headers=h["COMPTABLE"])
    assert r.status_code == 201, r.text
    fac = r.json()
    assert fac["total_ht"] == 1100.0 and fac["total_frais"] == 0.0
    assert fac["total_tva"] == 176.0 and fac["total_ttc"] == 1276.0   # marchandises 1100 * 16%

    # 408 soldé (0) ; grand livre auxiliaire : X doit 1276 (marchandise), Y doit 116 (transport)
    b2 = bal()
    assert "408" not in b2 or (b2["408"]["solde_debiteur"] == 0.0 and b2["408"]["solde_crediteur"] == 0.0)
    assert b2["601"]["solde_debiteur"] == 1100.0    # achat au prix (op 1)
    gl = client.get(f"/api/comptabilite/grand-livre?societe_id={sid}&compte=401", headers=h["COMPTABLE"]).json()
    mvts = [m for cpt in gl if cpt["compte"] == "401" for m in cpt["mouvements"]]
    solde = lambda nom: round(sum(m["credit"] - m["debit"] for m in mvts if m["tiers"] == nom), 2)
    assert solde(fourn["nom"]) == 1276.0 and solde("Transporteur Y") == 116.0
    assert client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()["equilibre"] is True

    # Double facturation refusée
    assert client.post(f"/api/commercial/receptions/{rec['id']}/facturer", headers=h["COMPTABLE"]).status_code == 409


def test_reception_frais_paye_caisse_sortie_reelle(ctx):
    """Un frais accessoire réglé comptant à la réception crée une VRAIE sortie de caisse
    (mouvement + crédit 571), pas une simple mention : plus de frais « flottant »."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid, cid = ids["societe_id"], ids["caisse_id"]
    cim = next(a for a in client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json() if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")
    caisse = next(c for c in client.get(f"/api/caisses?societe_id={sid}", headers=h["CAISSIER_CENTRAL"]).json() if c["est_principale"])

    cmd = client.post(f"/api/commercial/commandes?societe_id={sid}", headers=h["COMPTABLE"], json={
        "tiers_id": fourn["id"], "lignes": [{"article_id": cim["id"], "qte": 100, "prix_unitaire": 11}]}).json()

    # Sans caisse ouverte, régler un frais comptant est refusé (pas de sortie possible)
    r = client.post(f"/api/commercial/commandes/{cmd['id']}/receptionner", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_commande_id": cmd["lignes"][0]["id"], "qte_recue": 100}],
        "frais": [{"libelle": "Manutention", "montant_ht": 50, "mode": "caisse", "caisse_id": caisse["id"]}]})
    assert r.status_code == 409

    # Caisse ouverte → la réception passe et débite réellement la caisse du frais TTC (58)
    client.post(f"/api/caisse/{cid}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 1000})
    r = client.post(f"/api/commercial/commandes/{cmd['id']}/receptionner", headers=h["COMPTABLE"], json={
        "lignes": [{"ligne_commande_id": cmd["lignes"][0]["id"], "qte_recue": 100}],
        "frais": [{"libelle": "Manutention", "montant_ht": 50, "mode": "caisse", "caisse_id": caisse["id"]}]})
    assert r.status_code == 201, r.text

    jr = client.get(f"/api/caisse/{cid}/journal", headers=h["CAISSIER_CENTRAL"]).json()
    assert any(m["sens"] == "sortie" and m["montant"] == 58.0 for m in jr["mouvements"])   # 50 + TVA 16%
    assert jr["soldes"]["USD"] == 942.0                                                     # 1000 − 58
    bal = {l["compte"]: l for l in client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()["lignes"]}
    assert bal["571"]["solde_crediteur"] == 58.0 and bal["6085"]["solde_debiteur"] == 50.0
    assert client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()["equilibre"] is True


def test_achat_frais_annexes_cout_acquisition(ctx):
    """Frais annexes (transport commun) répartis sur le lot → le stock entre au
    coût d'acquisition (prix + frais), pas au seul prix d'achat."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]
    arts = client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json()
    cim = next(a for a in arts if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")

    # 100 sacs @ 11 (HT 1100) + transport commun 200 → coût d'acquisition 1300, CUMP 13
    r = client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"], "repartition": "quantite",
        "lignes": [{"article_id": cim["id"], "qte": 100, "prix_unitaire": 11}],
        "frais": [{"libelle": "Transport", "compte": "611", "montant_ht": 200}]})
    assert r.status_code == 201, r.text
    fa = r.json()
    assert fa["total_ht"] == 1100.0 and fa["total_frais"] == 200.0
    assert fa["total_tva"] == 208.0        # 176 (articles) + 32 (frais)
    assert fa["total_ttc"] == 1508.0
    assert fa["lignes"][0]["frais_reparti"] == 200.0 and fa["lignes"][0]["cout_entree"] == 1300.0

    # Stock entré au coût d'acquisition : CUMP 13 (et non 11)
    stk = client.get(f"/api/commercial/stock?societe_id={sid}", headers=h["COMPTABLE"]).json()
    s = next(l for l in stk["lignes"] if l["code"] == "CIM50")
    assert s["stock_qte"] == 100.0 and s["stock_valeur"] == 1300.0 and s["cump"] == 13.0

    # Écritures équilibrées : le 611 (transport) est bien mouvementé
    bal = client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert bal["equilibre"] is True
    assert any(l["compte"] == "611" for l in bal["lignes"])
    assert any(l["compte"] == "31" for l in bal["lignes"])


def test_frais_annexes_contrepartie_autre_fournisseur(ctx):
    """Ciment acheté au fournisseur X, mais le transport est dû à un fournisseur Y
    (à crédit) : chaque frais garde SA propre contrepartie. Le 401 de X ne porte que
    la marchandise ; le 401 de Y ne porte que le transport."""
    client, ids, _ = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    sid = ids["societe_id"]
    arts = client.get(f"/api/commercial/articles?societe_id={sid}", headers=h["COMPTABLE"]).json()
    cim = next(a for a in arts if a["code"] == "CIM50")
    fourn = next(t for t in client.get(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"]).json() if t["type"] == "fournisseur")

    # Fournisseur de transport distinct
    tr = client.post(f"/api/commercial/tiers?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "fournisseur", "code": "TRANSP", "nom": "Transporteur Y"})
    assert tr.status_code == 201, tr.text
    transporteur = tr.json()

    # 100 sacs @ 11 (HT 1100) chez X + transport 200 à crédit chez Y
    r = client.post(f"/api/commercial/factures?societe_id={sid}", headers=h["COMPTABLE"], json={
        "type": "achat", "tiers_id": fourn["id"], "repartition": "quantite",
        "lignes": [{"article_id": cim["id"], "qte": 100, "prix_unitaire": 11}],
        "frais": [{"libelle": "Transport", "compte": "6081", "montant_ht": 200,
                   "mode": "credit", "tiers_id": transporteur["id"]}]})
    assert r.status_code == 201, r.text
    fa = r.json()
    assert fa["total_ttc"] == 1508.0
    assert fa["frais"][0]["mode"] == "credit" and fa["frais"][0]["contrepartie"] == "Transporteur Y"
    # Stock toujours au coût d'acquisition (prix + frais)
    stk = client.get(f"/api/commercial/stock?societe_id={sid}", headers=h["COMPTABLE"]).json()
    s = next(l for l in stk["lignes"] if l["code"] == "CIM50")
    assert s["stock_valeur"] == 1300.0 and s["cump"] == 13.0

    # Grand livre auxiliaire : X doit 1276 (marchandise TTC), Y doit 232 (transport TTC)
    gl = client.get(f"/api/comptabilite/grand-livre?societe_id={sid}&compte=401", headers=h["COMPTABLE"]).json()
    mvts = [m for c in gl if c["compte"] == "401" for m in c["mouvements"]]
    def solde(tiers_nom):
        return sum(m["credit"] - m["debit"] for m in mvts if m["tiers"] == tiers_nom)
    assert round(solde(fourn["nom"]), 2) == 1276.0
    assert round(solde("Transporteur Y"), 2) == 232.0
    bal = client.get(f"/api/comptabilite/balance?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert bal["equilibre"] is True


def test_operation_caisse_genere_piece_comptable(ctx):
    """Un encaissement/sortie manuel de caisse crée une pièce comptable en attente
    (contrepartie 471 à reclasser par le comptable)."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    cid, sid = ids["caisse_id"], ids["societe_id"]

    client.post(f"/api/caisse/{cid}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 100})

    # Encaissement manuel 250 USD → D 571 / C 471
    r = client.post(f"/api/caisse/{cid}/operation", headers=h["CAISSIER_CENTRAL"], json={
        "sens": "entree", "nature": "Recette diverse", "beneficiaire": "Client X",
        "legs": [{"devise": "USD", "montant": 250}]})
    assert r.status_code == 201, r.text
    assert r.json()["piece_comptable"].startswith("CA-")

    pend = client.get(f"/api/comptabilite/ecritures?societe_id={sid}", headers=h["COMPTABLE"]).json()
    assert len(pend) == 1
    ecr = pend[0]
    assert ecr["statut"] == "en_attente"
    d_line = next(l for l in ecr["lignes"] if l["sens"] == "D")
    c_line = next(l for l in ecr["lignes"] if l["sens"] == "C")
    assert d_line["compte"] == "571" and float(d_line["montant_usd"]) == 250
    assert c_line["compte"] == "471" and float(c_line["montant_usd"]) == 250

    # Sortie manuelle 40 USD → D 471 / C 571
    client.post(f"/api/caisse/{cid}/operation", headers=h["CAISSIER_CENTRAL"], json={
        "sens": "sortie", "nature": "Frais divers", "legs": [{"devise": "USD", "montant": 40}]})
    pend = client.get(f"/api/comptabilite/ecritures?societe_id={sid}", headers=h["COMPTABLE"]).json()
    ecr2 = next(e for e in pend if e["numero"] != ecr["numero"])
    d2 = next(l for l in ecr2["lignes"] if l["sens"] == "D")
    c2 = next(l for l in ecr2["lignes"] if l["sens"] == "C")
    assert d2["compte"] == "471" and c2["compte"] == "571"


def test_cloture_caisse_avec_ecart(ctx):
    """Clôture : calcul de l'écart théorique/physique, justification obligatoire,
    verrouillage de la session et rapport Z ré-imprimable."""
    client, ids, TestSession = ctx
    pw, u = ids["password"], ids["users"]
    h = {role: _login(client, email, pw) for role, email in u.items()}
    cid = ids["caisse_id"]

    client.post(f"/api/caisse/{cid}/ouvrir", headers=h["CAISSIER_CENTRAL"], json={"fond_initial_usd": 500})
    client.post(f"/api/caisse/{cid}/operation", headers=h["CAISSIER_CENTRAL"], json={
        "sens": "entree", "nature": "Recette", "legs": [{"devise": "USD", "montant": 100}]})
    # Théorique = 600 USD

    # Écart sans justification → refusé
    r = client.post(f"/api/caisse/{cid}/cloturer", headers=h["CAISSIER_CENTRAL"],
                    json={"physique_usd": 595})
    assert r.status_code == 400

    # Écart de −5 justifié → accepté
    r = client.post(f"/api/caisse/{cid}/cloturer", headers=h["CAISSIER_CENTRAL"],
                    json={"physique_usd": 595, "commentaire": "Manquant non identifié"})
    assert r.status_code == 200, r.text
    rap = r.json()
    assert rap["theorique"]["USD"] == 600
    assert rap["physique"]["USD"] == 595
    assert rap["ecart"]["USD"] == -5

    # Session verrouillée : plus d'opération possible
    r = client.post(f"/api/caisse/{cid}/operation", headers=h["CAISSIER_CENTRAL"], json={
        "sens": "entree", "nature": "Recette", "legs": [{"devise": "USD", "montant": 10}]})
    assert r.status_code == 409

    # Rapport Z ré-imprimable
    z = client.get(f"/api/caisse/session/{rap['session_id']}/rapport-z", headers=h["CAISSIER_CENTRAL"]).json()
    assert z["statut"] == "cloturee" and z["ecart"]["USD"] == -5

