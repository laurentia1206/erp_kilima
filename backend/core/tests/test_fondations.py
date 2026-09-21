from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3
import uuid

import bcrypt
from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from jose import jwt
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core import comptabilite, stock_lib
from core.auth import creer_token
from core.backups import sauvegarder_sqlite
from core.config_views import _inserer_affectation
from core.models import (Article, AuditLog, Depot, Ecriture, Exercice, Journal,
                         LigneEcriture, MouvementStock, Role, SequenceCompteur,
                         Societe, StockDepot, Utilisateur)
from core.models import PieceJointe


class ComptabiliteTests(TestCase):
    def setUp(self):
        self.sid = uuid.uuid4()
        self.lignes = [{"sens": "D", "compte": "601", "montant_usd": 12.5},
                       {"sens": "C", "compte": "401", "montant_usd": 12.5}]

    def poster(self, lignes=None):
        return comptabilite.post_ecriture(
            self.sid, "OD", "Opérations diverses", "od", date(2026, 9, 14),
            "Achat test", self.lignes if lignes is None else lignes,
            "test", "test", None, None, None)

    def test_ecriture_equilibree_et_auditee(self):
        ecr = self.poster()
        self.assertEqual(ecr.numero, "OD-2026-00001")
        self.assertEqual(list(LigneEcriture.objects.filter(ecriture=ecr).order_by("ordre")
                              .values_list("montant_usd", flat=True)), [Decimal("12.50")] * 2)
        self.assertEqual(AuditLog.objects.filter(categorie='metier').count(), 1)
        self.assertEqual(self.poster().numero, "OD-2026-00002")

    def test_montants_non_finis_negatifs_et_trop_grands_refuses(self):
        for montant in [float("nan"), float("inf"), -1, "abc", None, "10000000000000000"]:
            with self.subTest(montant=montant), self.assertRaises(ValidationError):
                self.poster([{**l, "montant_usd": montant} for l in self.lignes])
        self.assertEqual(Ecriture.objects.count(), 0)
        self.assertEqual(SequenceCompteur.objects.count(), 0)

    def test_structure_et_desequilibre_refuses(self):
        for lignes in [[], self.lignes[:1], [{**self.lignes[0], "sens": "X"}, self.lignes[1]],
                       [{**self.lignes[0], "compte": ""}, self.lignes[1]],
                       [{**self.lignes[0], "montant_usd": 12.49}, self.lignes[1]]]:
            with self.subTest(lignes=lignes), self.assertRaises(ValidationError):
                self.poster(lignes)

    def test_equilibre_verifie_apres_arrondi_de_chaque_ligne(self):
        # Avant : D arrondi(total)=0.01, C=0.01, mais deux débits stockés à zéro.
        with self.assertRaises(ValidationError):
            self.poster([{"sens": "D", "compte": "601", "montant_usd": .004},
                         {"sens": "D", "compte": "602", "montant_usd": .004},
                         {"sens": "C", "compte": "401", "montant_usd": .008}])

    def test_arrondi_decimal_et_sans_modification_des_arguments(self):
        lignes = [{**l, "montant_usd": "1.005"} for l in self.lignes]
        self.poster(lignes)
        self.assertEqual(LigneEcriture.objects.first().montant_usd, Decimal("1.01"))
        self.assertEqual(lignes[0]["montant_usd"], "1.005")

    def test_exercice_ferme_refuse(self):
        Exercice.objects.create(societe_id=self.sid, annee=2026, date_debut=date(2026, 1, 1),
                                date_fin=date(2026, 12, 31), statut="cloture")
        with self.assertRaises(ValidationError):
            self.poster()
        self.assertFalse(Ecriture.objects.exists())

    def test_journal_inactif_refuse(self):
        Journal.objects.create(societe_id=self.sid, code="OD", libelle="OD", type="od", actif=False)
        with self.assertRaises(ValidationError):
            self.poster()
        self.assertFalse(Exercice.objects.exists())

    def test_echec_audit_annule_toute_lecriture_et_numero(self):
        with patch("core.services.enregistrer_audit", side_effect=RuntimeError("Panne simulée")):
            with self.assertRaises(RuntimeError):
                self.poster()
        for modele in [Ecriture, LigneEcriture, Exercice, Journal, SequenceCompteur]:
            self.assertFalse(modele.objects.exists(), modele.__name__)


class AccesTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = Utilisateur.objects.create(email="test@kilima.cd", nom="Test",
            password_hash=bcrypt.hashpw(b"test-password", bcrypt.gensalt(rounds=4)).decode())
        self.societe = Societe.objects.create(code="TEST", nom="Société test")
        self.role = Role.objects.create(code="DFI", libelle="DFI")
        _inserer_affectation(self.user.id, self.societe.id, self.role.id)

    def test_installation_vierge_affectations_multi_roles(self):
        autre = Role.objects.create(code="COMPTABLE", libelle="Comptable")
        _inserer_affectation(self.user.id, self.societe.id, autre.id)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + creer_token(self.user.id))
        r = self.client.get("/api/societes")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()[0]["roles"]), {"DFI", "COMPTABLE"})

    def test_session_absente_ou_invalide_renvoie_401(self):
        for token in [None, "incorrect", jwt.encode(
            {"sub": str(self.user.id), "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
            settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)]:
            self.client.credentials(**({"HTTP_AUTHORIZATION": "Bearer " + token} if token else {}))
            r = self.client.get("/api/auth/me")
            self.assertEqual(r.status_code, 401)
            self.assertIn("Bearer", r["WWW-Authenticate"])

    def test_societe_non_autorisee_renvoie_403(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + creer_token(self.user.id))
        r = self.client.get("/api/dashboard", {"societe_id": str(uuid.uuid4())})
        self.assertEqual(r.status_code, 403)

    def test_compte_desactive_ne_peut_plus_utiliser_son_jeton(self):
        token = creer_token(self.user.id)
        self.user.actif = False
        self.user.save()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_connexion_et_saisie_invalide(self):
        r = self.client.post("/api/auth/login", {"username": self.user.email, "password": "test-password"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("access_token", r.json())
        r = self.client.post("/api/auth/login", {"username": [], "password": None}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_justificatif_autre_societe_refuse_en_lecture_et_ecriture(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + creer_token(self.user.id))
        ecriture = Ecriture.objects.create(societe_id=uuid.uuid4(), exercice_id=uuid.uuid4(),
            numero="OD-TEST", date_ecriture=date.today(), libelle="Autre société")
        pj = PieceJointe.objects.create(document_type="ecriture", document_id=ecriture.id,
            nom_fichier="preuve.txt", chemin_stockage="preuve.txt")
        r = self.client.get("/api/pieces-jointes", {"document_type": "ecriture", "document_id": str(ecriture.id)})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get(f"/api/pieces-jointes/{pj.id}/download").status_code, 403)
        r = self.client.post("/api/pieces-jointes", {"document_type": "ecriture",
            "document_id": str(ecriture.id), "file": SimpleUploadedFile("preuve.txt", b"preuve")}, format="multipart")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(PieceJointe.objects.count(), 1)

    def test_justificatif_autorise_et_traversee_refusee(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + creer_token(self.user.id))
        ecriture = Ecriture.objects.create(societe_id=self.societe.id, exercice_id=uuid.uuid4(),
            numero="OD-TEST", date_ecriture=date.today(), libelle="Société autorisée")
        with TemporaryDirectory() as tmp, patch("core.config_views.UPLOADS", Path(tmp) / "uploads"):
            r = self.client.post("/api/pieces-jointes", {"document_type": "ecriture",
                "document_id": str(ecriture.id), "file": SimpleUploadedFile("preuve.txt", b"preuve")}, format="multipart")
            self.assertEqual(r.status_code, 201, r.content)
            pid = r.json()["id"]
            r = self.client.get(f"/api/pieces-jointes/{pid}/download")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(b"".join(r.streaming_content), b"preuve")
            r.close()
            (Path(tmp) / "secret.txt").write_text("secret")
            PieceJointe.objects.filter(id=pid).update(chemin_stockage="../secret.txt")
            self.assertEqual(self.client.get(f"/api/pieces-jointes/{pid}/download").status_code, 404)


class StockTests(TestCase):
    def setUp(self):
        self.sid = uuid.uuid4()
        self.article = Article.objects.create(societe_id=self.sid, code="A", designation="Ciment")
        self.source = Depot.objects.create(societe_id=self.sid, code="CENTRAL", libelle="Central")
        self.cible = Depot.objects.create(societe_id=self.sid, code="BAR", libelle="Bar")
        stock_lib.entree(self.article, self.source, 10, 100, "achat", "FA-TEST")

    def test_transfert_conserve_totaux_et_trace_deux_mouvements(self):
        self.assertEqual(stock_lib.transferer(self.article, self.source, self.cible, 3, "TD-TEST"), 30)
        self.article.refresh_from_db()
        self.assertEqual(self.article.stock_qte, 10)
        self.assertEqual(self.article.stock_valeur, 100)
        self.assertEqual(stock_lib.qte_disponible(self.source.id, self.article.id), 7)
        self.assertEqual(stock_lib.qte_disponible(self.cible.id, self.article.id), 3)
        self.assertEqual(MouvementStock.objects.filter(reference="TD-TEST").count(), 2)

    def test_stock_insuffisant_refuse_sans_mouvement(self):
        with self.assertRaises(ValidationError):
            stock_lib.sortie(self.article, self.source, 11, "vente", "FV-TEST")
        with self.assertRaises(ValidationError):
            stock_lib.transferer(self.article, self.source, self.cible, 11, "TD-TEST")
        self.article.refresh_from_db()
        self.assertEqual(self.article.stock_qte, 10)
        self.assertEqual(MouvementStock.objects.count(), 1)

    def test_objet_article_obsolete_recharge_avant_sortie(self):
        ancien = Article.objects.get(id=self.article.id)
        stock_lib.sortie(self.article, self.source, 3, "vente", "FV-1")
        stock_lib.sortie(ancien, self.source, 2, "vente", "FV-2")
        self.article.refresh_from_db()
        self.assertEqual(self.article.stock_qte, 5)
        self.assertEqual(self.article.stock_valeur, 50)

    def test_depot_autre_societe_inactif_et_meme_depot_refuses(self):
        autre = Depot.objects.create(societe_id=uuid.uuid4(), code="AUTRE", libelle="Autre")
        for cible in [autre, self.source]:
            with self.assertRaises(ValidationError):
                stock_lib.transferer(self.article, self.source, cible, 1, "TD")
        self.cible.actif = False
        self.cible.save()
        with self.assertRaises(ValidationError):
            stock_lib.transferer(self.article, self.source, self.cible, 1, "TD")

    def test_valeurs_invalides_refusees(self):
        for qte in [0, -1, float("nan"), float("inf"), "abc"]:
            with self.subTest(qte=qte), self.assertRaises(ValidationError):
                stock_lib.entree(self.article, self.source, qte, 1, "achat", "FA")

    def test_panne_journal_annule_les_soldes(self):
        with patch("core.stock_lib.MouvementStock.objects.create", side_effect=RuntimeError("Panne")):
            with self.assertRaises(RuntimeError):
                stock_lib.transferer(self.article, self.source, self.cible, 3, "TD")
        self.assertEqual(stock_lib.qte_disponible(self.source.id, self.article.id), 10)
        self.assertFalse(StockDepot.objects.filter(depot_id=self.cible.id).exists())


class FichiersTests(SimpleTestCase):
    def test_traversee_vers_dossier_de_meme_prefixe_refusee(self):
        with TemporaryDirectory() as tmp:
            racine = Path(tmp) / "static"
            racine.mkdir()
            voisin = Path(tmp) / "static-secret"
            voisin.mkdir()
            (voisin / "secret.txt").write_text("secret")
            with patch("core.frontend_views.STATIC", racine):
                r = self.client.get("/static/../static-secret/secret.txt")
                self.assertEqual(r.status_code, 404)

    def test_frontend_et_entetes(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r["X-Frame-Options"], "DENY")
        r.close()

    def test_sauvegarde_inclut_donnees_du_journal_wal(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "test.db"
            db = sqlite3.connect(source)
            try:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE essai (valeur TEXT)")
                db.execute("INSERT INTO essai VALUES ('confirmé')")
                db.commit()
                cible = sauvegarder_sqlite(source)
                copie = sqlite3.connect(cible)
                try:
                    self.assertEqual(copie.execute("SELECT valeur FROM essai").fetchone()[0], "confirmé")
                    self.assertEqual(copie.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                finally:
                    copie.close()
                self.assertEqual(sauvegarder_sqlite(source), cible)
            finally:
                db.close()

    @override_settings(ACCESS_TOKEN_EXPIRE_MINUTES=10)
    def test_duree_jeton_configurable(self):
        payload = jwt.decode(creer_token(uuid.uuid4()), settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        restant = payload["exp"] - datetime.now(timezone.utc).timestamp()
        self.assertGreater(restant, 595)
        self.assertLessEqual(restant, 600)
