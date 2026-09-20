from datetime import date
from decimal import Decimal as D
from django.test import TestCase
from core.tests import test_rh as base
from core.rh_calculs import irpp_mensuel, simulation
from core.models import RHSimulation, RHContrat, RHDecompte, Ecriture, MouvementCaisse


class RHCalculsTests(TestCase):
    call=base.RHTests.call
    def setUp(self):
        base.RHTests.setUp(self)

    def param(self,**kw):
        return {'date_reference':'2026-04-01','devise':'USD','taux_cdf':'2300','source_taux':'Hypothèse de test',
            'brut_base':'1000','logement':'300','transport':'50','primes':'100','net_vise':'1200',
            'trajet_cdf':'1000','jours_transport':26,'charges_famille':0,'justification_indemnites':'Logement contractuel et transport documenté',**kw}

    def test_tranches_limites_plafond_et_famille(self):
        for base_cdf,attendu in [('0','0'),('162000','4860'),('1800000','250560'),('3600000','790560'),('10000000','3000000')]:
            self.assertEqual(irpp_mensuel(D(base_cdf))[0],D(attendu))
        self.assertEqual(irpp_mensuel(D('10000000'),9)[0],D('2857699.20'))
        self.assertEqual(irpp_mensuel(D('162083.33'))[0],D('4860'))

    def test_assiettes_distinctes_et_prime_incluse(self):
        r=self.call('simuler',self.param())['resultat']
        self.assertEqual(r['base_cnss'],'1100.00')
        self.assertEqual(r['cnss_salarie'],'55.00')
        self.assertEqual(r['base_irpp_cdf'],'2403500.00')
        # 250560 + (2403500 - 1800000) * 30 % = 431610 CDF.
        self.assertEqual(r['irpp_cdf'],'431610.00')
        self.assertEqual(r['irpp'],'187.66')
        self.assertEqual(r['net'],'1207.34')
        self.assertFalse(Ecriture.objects.exists());self.assertFalse(MouvementCaisse.objects.exists())

    def test_logement_excedent_fiscal_non_cnss_et_transport_non_justifie(self):
        p,r=simulation(self.param(logement='500',trajet_cdf='0'))
        self.assertEqual(r['base_cnss'],'1100.00')
        self.assertEqual(r['logement_exonere_irpp'],'330.00')
        self.assertEqual(r['transport_exonere_irpp'],'0.00')
        self.assertEqual(r['base_irpp'],'1265.00')

    def test_erreurs_et_cloisonnement(self):
        for kw in [{'brut_base':'NaN'},{'taux_cdf':'0'},{'charges_famille':10},{'charges_famille':1},
                   {'jours_transport':'26'},{'date_reference':'2025-01-01'},{'justification_indemnites':''}]:
            self.call('simuler',self.param(**kw),status=400)
        self.call('simuler',self.param(),role='RESP_EQUIPE',status=403)
        self.call('simuler',self.param(),sid=self.autre.id,status=403)

    def test_simulation_figee_reprise_contrat_et_tentative_changement(self):
        s=self.call('simulations',{**self.param(),'nom':'Proposition A'},status=201)
        contrat={'nature':'contrat','reference':'C-SIM','type_contrat':'CDI','debut':'2026-04-01','base_salaire':'net',
            'devise':'USD','salaire':'1200','simulation_id':s['id']}
        self.call(f'agents/{self.a.id}/dossier',contrat,status=400)
        contrat['salaire']='1207.34'
        d=self.call(f'agents/{self.a.id}/dossier',contrat,status=201)
        self.assertEqual(d['contrats'][0]['remuneration']['resultat']['net'],'1207.34')
        self.assertEqual(RHSimulation.objects.get().parametres['date_reference'],'2026-04-01')
        self.call('simulations',role='COMPTABLE',status=403)
        self.assertFalse(Ecriture.objects.exists())

    def test_decompte_detail_et_pas_de_retenue_ni_sortie_automatique(self):
        c=RHContrat.objects.create(societe=self.s,agent=self.a,reference='FINAL',type_contrat='CDI',debut=date(2020,1,1),salaire=1000,base_salaire='net',devise='USD',created_by=self.users['RH'].id,updated_by=self.users['RH'].id)
        p={'agent_id':str(self.a.id),'contrat_id':str(c.id),'date_depart':'2026-09-15','motif':'licenciement','categorie_preavis':'I_V',
            'remuneration_reference':'1300','moyenne_variables_12m':'260','reliquat_salaire':'600','jours_conges':'12',
            'preavis_mois':'0','preavis_jours':'56','autres_droits':'100','diviseur_journalier':26,
            'reference_solde_conges':'Registre fictif vérifié','references':'Hypothèse pédagogique, référence 12 mois'}
        d=self.call('decomptes',p,status=201)
        self.assertEqual(d['resultat']['indemnite_conges'],'720.00')
        self.assertEqual(d['resultat']['indemnite_preavis'],'3360.00')
        self.assertEqual(d['resultat']['total_droits_bruts'],'4780.00')
        self.assertEqual(d['resultat']['preavis_repere']['jours_ouvrables'],56)
        self.a.refresh_from_db();self.assertIsNone(self.a.date_sortie)
        self.assertFalse(Ecriture.objects.exists());self.assertFalse(MouvementCaisse.objects.exists())
        self.call('decomptes',{**p,'motif':'demission'},status=400)
        self.call('decomptes',{**p,'motif':'fin_cdd'},status=400)
        self.call('decomptes',role='RESP_EQUIPE',status=403)
