"""Recette G01 → G04 sur Django, données créées intégralement par le test."""
from decimal import Decimal

import bcrypt
from django.test import TestCase
from django.db import transaction
from rest_framework.test import APIClient

from core.auth import creer_token
from core.config_views import _inserer_affectation
from core.models import (Avance, BonReception, Caisse, Ecriture, LigneEcriture, MouvementCaisse, OrdreDepense,
                         PalierApprobateur, PalierValidation, Role, Societe, Tiers, Utilisateur)


class CircuitDecaissementTests(TestCase):
    def setUp(self):
        self.soc = Societe.objects.create(code="TEST", nom="Société de recette")
        self.clients = {}
        roles = {}
        for code in ["DFI", "DG", "ADMIN", "PRESIDENT", "COMPTABLE", "CAISSIER_CENTRAL"]:
            role = Role.objects.create(code=code, libelle=code)
            roles[code] = role
            user = Utilisateur.objects.create(email=code.lower() + "@test.local", nom=code,
                password_hash=bcrypt.hashpw(b"test-password", bcrypt.gensalt(rounds=4)).decode())
            _inserer_affectation(user.id, self.soc.id, role.id)
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION="Bearer " + creer_token(user.id))
            self.clients[code] = client
        for type_doc, etape, codes in [
            ("requisition", "demande", ["DG", "ADMIN"]),
            ("ordre_depense", "sortie_fonds", ["DFI", "DG", "ADMIN", "PRESIDENT"]),
        ]:
            palier = PalierValidation.objects.create(societe_id=self.soc.id,
                type_document=type_doc, etape=etape, montant_min_usd=0,
                montant_max_usd=None, libelle="Validation conjointe")
            for code in codes:
                PalierApprobateur.objects.create(palier=palier, role=roles[code], mode="conjoint")
        self.beneficiaire = Tiers.objects.create(societe_id=self.soc.id, code="AGENT", nom="Agent test", type="agent")
        self.caisse = Caisse.objects.create(societe_id=self.soc.id, libelle="Caisse", compte_comptable="571")

    def post(self, role, path, data, status=200):
        # refus() marque la transaction courante pour rollback. Chaque requête
        # doit avoir sa frontière, sans invalider la transaction du TestCase.
        with transaction.atomic():
            r = self.clients[role].post("/api/" + path, data, format="json")
        self.assertEqual(r.status_code, status, r.content)
        return r.json()

    def demande(self, role="COMPTABLE"):
        return self.post(role, "requisitions", {"societe_id": str(self.soc.id), "objet": "Achat fournitures",
            "devise": "USD", "lignes": [{"description": "Fournitures", "quantite": 1, "prix_unitaire": 5000}]}, 201)

    def ordre(self):
        req = self.demande()
        self.assertEqual(Decimal(req["montant_total_usd"]), Decimal("5000"))
        for role in ["DG", "ADMIN"]:
            validee = self.post(role, f"requisitions/{req['id']}/valider-demande", {"decision": "valide"})
        self.assertEqual(validee["statut"], "demande_validee")
        return self.post("DFI", "ordres-depense", {"requisition_id": req["id"],
            "beneficiaire_tiers_id": str(self.beneficiaire.id), "mode_paiement": "caisse"}, 201)

    def test_cycle_complet_avec_apurement_comptable(self):
        ordre = self.ordre()
        for role in ["DG", "ADMIN", "PRESIDENT"]:
            resultat = self.post(role, f"ordres-depense/{ordre['id']}/valider", {"decision": "valide"})
        self.assertEqual(resultat["statut"], "valide")
        self.post("CAISSIER_CENTRAL", f"caisse/{self.caisse.id}/ouvrir", {"fond_initial_usd": 10000}, 201)
        resultat = self.post("CAISSIER_CENTRAL", f"ordres-depense/{ordre['id']}/executer",
                             {"caisse_id": str(self.caisse.id), "type_avance": "boissons"})
        self.assertTrue(resultat["avance_numero"].startswith("AVJ-"))
        avance = Avance.objects.get()
        self.post("COMPTABLE", "avances/justifier", {"avance_id": str(avance.id),
            "solde_retourne": 0, "devise_solde": "USD",
            "lignes": [{"nature": "Fournitures", "devise": "USD", "montant": 5000, "compte_impute": "605"}]}, 201)
        avance.refresh_from_db()
        self.assertEqual(avance.statut, "justifiee")
        self.assertEqual(Ecriture.objects.count(), 2)
        soldes = {}
        for ecriture in Ecriture.objects.all():
            equilibre = Decimal(0)
            for ligne in LigneEcriture.objects.filter(ecriture=ecriture):
                signe = 1 if ligne.sens == "D" else -1
                montant = signe * ligne.montant_usd
                equilibre += montant
                soldes[ligne.compte_numero] = soldes.get(ligne.compte_numero, Decimal(0)) + montant
            self.assertEqual(equilibre, 0)
        self.assertEqual(soldes["421"], 0)
        self.assertEqual(soldes["571"], -5000)
        self.assertEqual(soldes["605"], 5000)
        # Une deuxième exécution ne doit jamais sortir une seconde fois les fonds.
        avant = MouvementCaisse.objects.count()
        self.post("CAISSIER_CENTRAL", f"ordres-depense/{ordre['id']}/executer",
                  {"caisse_id": str(self.caisse.id)}, 409)
        self.assertEqual(MouvementCaisse.objects.count(), avant)

    def test_decaissement_sans_cosignatures_refuse(self):
        ordre = self.ordre()
        self.post("CAISSIER_CENTRAL", f"ordres-depense/{ordre['id']}/executer",
                  {"caisse_id": str(self.caisse.id)}, 409)
        self.assertFalse(Avance.objects.exists())
        self.assertFalse(MouvementCaisse.objects.exists())

    def test_beneficiaire_reste_modifiable_au_paiement(self):
        """Décision de Laurent : conserver la substitution au décaissement."""
        ordre = self.ordre()
        for role in ["DG", "ADMIN", "PRESIDENT"]:
            self.post(role, f"ordres-depense/{ordre['id']}/valider", {"decision": "valide"})
        remplacant = Tiers.objects.create(societe_id=self.soc.id, code="REMPLACANT",
                                         nom="Bénéficiaire remplaçant", type="agent")
        self.post("CAISSIER_CENTRAL", f"caisse/{self.caisse.id}/ouvrir", {"fond_initial_usd": 10000}, 201)
        self.post("CAISSIER_CENTRAL", f"ordres-depense/{ordre['id']}/executer",
                  {"caisse_id": str(self.caisse.id), "type_avance": "boissons",
                   "beneficiaire_tiers_id": str(remplacant.id)})
        self.assertEqual(OrdreDepense.objects.get(id=ordre['id']).beneficiaire_tiers_id, remplacant.id)
        self.assertEqual(Avance.objects.get().beneficiaire_tiers_id, remplacant.id)
        self.assertEqual(BonReception.objects.get().receveur_tiers_id,remplacant.id)
        self.assertEqual(MouvementCaisse.objects.get().tiers_id,remplacant.id)
        self.assertTrue(LigneEcriture.objects.filter(tiers_id=remplacant.id).exists())

    def test_repertoire_identique_dfi_caissier_et_agents_sans_doublons(self):
        path=f'/api/beneficiaires?societe_id={self.soc.id}'
        a=self.clients['DFI'].get(path)
        b=self.clients['CAISSIER_CENTRAL'].get(path)
        self.assertEqual(a.status_code,200);self.assertEqual(a.json(),b.json())
        agents=[r for r in a.json() if r.get('agent_existant')]
        self.assertEqual(len(agents),6)
        # Lire le répertoire ne crée aucune nouvelle fiche financière.
        self.assertEqual(Tiers.objects.count(),1)

    def test_agent_existant_resolu_et_avances_partielles_conservent_leur_beneficiaire(self):
        ordre=self.ordre()
        for role in ['DG','ADMIN','PRESIDENT']:
            self.post(role,f"ordres-depense/{ordre['id']}/valider",{'decision':'valide'})
        self.post('CAISSIER_CENTRAL',f'caisse/{self.caisse.id}/ouvrir',{'fond_initial_usd':10000},201)
        entries=self.clients['DFI'].get(f'/api/beneficiaires?societe_id={self.soc.id}').json()
        agent=next(x for x in entries if x.get('agent_existant') and x['nom']=='COMPTABLE')
        self.post('CAISSIER_CENTRAL',f"ordres-depense/{ordre['id']}/executer",{'caisse_id':str(self.caisse.id),'montant':1000,'beneficiaire_tiers_id':agent['id']})
        linked=Tiers.objects.get(utilisateur_id=agent['utilisateur_id'])
        first=Avance.objects.get()
        self.assertEqual(first.beneficiaire_tiers_id,linked.id)
        self.post('CAISSIER_CENTRAL',f"ordres-depense/{ordre['id']}/executer",{'caisse_id':str(self.caisse.id),'montant':4000,'beneficiaire_tiers_id':str(self.beneficiaire.id)})
        first.refresh_from_db()
        self.assertEqual(first.beneficiaire_tiers_id,linked.id)
        self.assertEqual(Avance.objects.exclude(id=first.id).get().beneficiaire_tiers_id,self.beneficiaire.id)
        self.assertEqual(BonReception.objects.filter(receveur_tiers_id=linked.id).count(),1)

    def test_paiement_refuse_beneficiaire_prive_autre_societe(self):
        ordre=self.ordre()
        for role in ['DG','ADMIN','PRESIDENT']:
            self.post(role,f"ordres-depense/{ordre['id']}/valider",{'decision':'valide'})
        autre=Societe.objects.create(code='AUTRE',nom='Autre société')
        tiers=Tiers.objects.create(societe_id=autre.id,type='agent',code='X',nom='Agent autre société')
        self.post('CAISSIER_CENTRAL',f"ordres-depense/{ordre['id']}/executer",{'caisse_id':str(self.caisse.id),'beneficiaire_tiers_id':str(tiers.id)},400)
        self.assertFalse(Avance.objects.exists());self.assertFalse(BonReception.objects.exists())

    def test_auto_validation_interdite(self):
        req = self.demande("DG")
        self.post("DG", f"requisitions/{req['id']}/valider-demande", {"decision": "valide"}, 403)

    def test_creation_beneficiaire_visible_aux_deux_etapes_et_sans_compte_connexion(self):
        path=f'beneficiaires?societe_id={self.soc.id}'
        avant=Utilisateur.objects.count()
        body={'type':'fournisseur','code':'FOURN-1','nom':'Fournisseur de recette'}
        cree=self.post('DFI',path,body,201)
        self.post('CAISSIER_CENTRAL',path,{**body,'nom':'Autre nom'},409)
        for role in ('DFI','CAISSIER_CENTRAL'):
            liste=self.clients[role].get('/api/'+path).json()
            self.assertEqual(sum(x['id']==cree['id'] for x in liste),1)
        self.assertEqual(Utilisateur.objects.count(),avant)

    def test_agent_enregistre_propose_au_lieu_de_creer_un_homonyme(self):
        path=f'beneficiaires?societe_id={self.soc.id}'
        avant=Tiers.objects.count()
        erreur=self.post('CAISSIER_CENTRAL',path,
            {'type':'agent','code':'AGENT-BIS','nom':'comptable','confirmer_homonyme':True},409)
        self.assertTrue(erreur['existing_id'].startswith('agent:'))
        self.assertEqual(Tiers.objects.count(),avant)
