"""Calculs explicites, décimaux et datés. Aucune écriture ni retenue de dette."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from rest_framework.exceptions import ValidationError
from apps.rh.views import argent, jour, choix, texte

D=Decimal
CENT=D('.01')
VERSION='RDC-SALARIE-2026-v1'


def arrondi(n):
    return n.quantize(CENT,rounding=ROUND_HALF_UP)


def entier(p,cle,minimum,maximum,defaut=0):
    v=p.get(cle,defaut)
    if type(v) is not int or not minimum<=v<=maximum:
        raise ValidationError(f'{cle} : entier entre {minimum} et {maximum} attendu.')
    return v


def irpp_mensuel(base_cdf,charges=0):
    # Annualisation de la rémunération mensuelle ; art.118 : millier inférieur.
    annuel=(base_cdf*12/D(1000)).to_integral_value(rounding=ROUND_DOWN)*1000
    tranches=[];bas=D(0)
    for haut,taux in [(D(1944000),D('.03')),(D(21600000),D('.15')),(D(43200000),D('.30')),(None,D('.40'))]:
        assiette=max(D(0),(min(annuel,haut) if haut else annuel)-bas)
        tranches.append({'base_annuelle':str(assiette),'taux':str(taux*100),'impot_annuel':str(arrondi(assiette*taux))})
        if haut: bas=haut
    progressif=sum(D(t['impot_annuel']) for t in tranches)
    plafonne=min(progressif,annuel*D('.30'))
    # La fraction supérieure à la troisième tranche ne bénéficie pas de la réduction.
    part_eligible=min(plafonne,sum(D(t['impot_annuel']) for t in tranches[:3]))
    reduction=part_eligible*D('.02')*charges
    return arrondi((plafonne-reduction)/12),{'revenu_annuel_arrondi':str(annuel),'tranches':tranches,
        'impot_annuel_avant_plafond':str(arrondi(progressif)),'impot_annuel_plafonne':str(arrondi(plafonne)),
        'reduction_famille_annuelle':str(arrondi(reduction))}


def simulation(p):
    date_ref=jour(p.get('date_reference'))
    if date_ref.year!=2026: raise ValidationError('Ce barème de simulation couvre 2026. Une autre année exige sa version réglementaire.')
    devise=choix(p.get('devise'),['USD','CDF'])
    taux=argent(p.get('taux_cdf'))
    if not 0<taux<=1000000: raise ValidationError('Indiquez le taux : nombre de CDF pour 1 USD.')
    source_taux=texte(p,'source_taux',180,True)
    vals={k:argent(p.get(k,'0')) for k in ['brut_base','logement','transport','primes','net_vise','trajet_cdf']}
    if max(vals.values())>D('100000000000'): raise ValidationError('Montant hors plage de simulation.')
    if not vals['brut_base']: raise ValidationError('Le salaire brut de base doit être positif.')
    jours=entier(p,'jours_transport',0,31,26)
    charges=entier(p,'charges_famille',0,9)
    preuve_famille=texte(p,'reference_famille',300)
    if charges and not preuve_famille: raise ValidationError('Précisez la référence des justificatifs des charges de famille admissibles.')
    qualif=texte(p,'justification_indemnites',1000)
    if (vals['logement'] or vals['transport']) and not qualif:
        raise ValidationError('Précisez la nature réelle du logement et du transport et les références des justificatifs.')
    facteur=taux if devise=='USD' else D(1)
    remuneration=vals['brut_base']+vals['primes']
    # CNSS art.17 : salaire/primes inclus, véritables indemnités logement/transport exclues.
    base_cnss=remuneration
    cnss_salarie=arrondi(base_cnss*D('.05'))
    logement_exonere=min(vals['logement'],remuneration*D('.30'))
    transport_exonere=min(vals['transport'],vals['trajet_cdf']*6*jours/facteur)
    base_irpp=max(D(0),remuneration+vals['logement']-logement_exonere+vals['transport']-transport_exonere-cnss_salarie)
    impot_cdf,detail=irpp_mensuel(base_irpp*facteur,charges)
    irpp=arrondi(impot_cdf/facteur)
    brut_total=sum(vals[k] for k in ('brut_base','logement','transport','primes'))
    net=brut_total-cnss_salarie-irpp
    patron_cnss=arrondi(base_cnss*D('.13'))
    alertes=['Simulation d’engagement pour un salarié au régime général. Les associés actifs et régimes particuliers nécessitent leur propre calcul.',
        'Les montants de logement et transport doivent correspondre à de véritables indemnités ; renommer une prime ne la rend pas exonérée.',
        'IRPP : revenu mensuel annualisé, arrondi au millier de CDF inférieur, puis impôt annuel divisé par 12. Méthode à rapprocher du bordereau fiscal avant paie définitive.',
        'Coût affiché hors INPP, ONEM et autres charges patronales ; leur paramétrage est traité séparément.']
    if vals['transport'] and not vals['trajet_cdf']: alertes.append('Transport intégralement imposé : coût du trajet non renseigné.')
    if vals['logement']>logement_exonere: alertes.append('La part du logement supérieure au plafond fiscal est réintégrée dans la base IRPP.')
    param={**{k:str(v) for k,v in vals.items()},'date_reference':date_ref.isoformat(),'devise':devise,'taux_cdf':str(taux),
        'source_taux':source_taux,'jours_transport':jours,'charges_famille':charges,'reference_famille':preuve_famille,'justification_indemnites':qualif}
    return param,{'version':VERSION,'devise':devise,'brut_total':str(arrondi(brut_total)),
        'base_cnss':str(arrondi(base_cnss)),'cnss_salarie':str(cnss_salarie),'cnss_employeur':str(patron_cnss),
        'logement_exonere_irpp':str(arrondi(logement_exonere)),'transport_exonere_irpp':str(arrondi(transport_exonere)),
        'base_irpp':str(arrondi(base_irpp)),'base_irpp_cdf':str(arrondi(base_irpp*facteur)),
        'irpp_cdf':str(impot_cdf),'irpp':str(irpp),'net':str(arrondi(net)),
        'ecart_net_vise':str(arrondi(net-vals['net_vise'])),'cout_avec_cnss':str(arrondi(brut_total+patron_cnss)),
        'detail_irpp':detail,'alertes':alertes}


def decompte_brut(p,a,c):
    depart=jour(p.get('date_depart'))
    if depart<a.date_engagement or depart<c.debut: raise ValidationError('Le départ doit suivre l’engagement et le début du contrat.')
    motif=choix(p.get('motif'),['fin_cdd','demission','licenciement','retraite','accord','deces'])
    if motif=='fin_cdd' and (c.type_contrat!='CDD' or c.fin!=depart): raise ValidationError('La fin de CDD doit correspondre au terme du contrat sélectionné.')
    if c.fin and depart>c.fin: raise ValidationError('La date de départ dépasse le terme de ce contrat.')
    categorie=choix(p.get('categorie_preavis'),['I_V','maitrise','cadre'])
    annees=depart.year-a.date_engagement.year-((depart.month,depart.day)<(a.date_engagement.month,a.date_engagement.day))
    repere={'mois':0,'jours_ouvrables':14+7*annees}
    if categorie=='maitrise': repere={'mois':1,'jours_ouvrables':8*annees}
    if categorie=='cadre': repere={'mois':3,'jours_ouvrables':15*annees}
    repere['coefficient_demission']='0.5' if motif=='demission' else '1'
    if motif not in ('licenciement','demission') or c.type_contrat!='CDI': repere={'a_qualifier':True}
    montants={k:argent(p.get(k,'0')) for k in ('remuneration_reference','moyenne_variables_12m','reliquat_salaire','jours_conges','preavis_mois','preavis_jours','autres_droits')}
    diviseur=entier(p,'diviseur_journalier',1,31,26)
    if montants['jours_conges']>3660 or montants['preavis_jours']>3660 or montants['preavis_mois']>120: raise ValidationError('Durée hors plage.')
    if not montants['remuneration_reference']: raise ValidationError('La rémunération brute de référence est requise ; ne saisissez pas le net du contrat.')
    references=texte(p,'references',5000,True)
    ref_conges=texte(p,'reference_solde_conges',1000,True)
    # Préparation des droits bruts seulement : pas de déduction arbitraire des dettes.
    mensuel=montants['remuneration_reference']+montants['moyenne_variables_12m']
    conges=arrondi(mensuel/D(diviseur)*montants['jours_conges'])
    preavis=arrondi(mensuel*montants['preavis_mois']+mensuel/D(diviseur)*montants['preavis_jours'])
    if preavis and motif not in ('licenciement','accord'): raise ValidationError('Une indemnité de préavis à payer doit être qualifiée : utilisez un départ employeur ou un accord documenté.')
    total=arrondi(montants['reliquat_salaire']+conges+preavis+montants['autres_droits'])
    param={**{k:str(v) for k,v in montants.items()},'date_depart':depart.isoformat(),'motif':motif,'categorie_preavis':categorie,
        'diviseur_journalier':diviseur,'references':references,'reference_solde_conges':ref_conges}
    return param,{'version':'RDC-DECOMPTE-PREPARATION-v1','nom':a.nom,'matricule':a.matricule,'reference_contrat':c.reference,
        'devise':c.devise,'annees_service':annees,'preavis_repere':repere,'indemnite_conges':str(conges),
        'indemnite_preavis':str(preavis),'total_droits_bruts':str(total),
        'alertes':['Préparation des droits bruts, avant impôts, cotisations et retenues autorisées. Ce document n’est pas un ordre de paiement.',
        'Le solde des congés et les moyennes de rémunération doivent être rapprochés des historiques. Aucune acquisition ni indemnité de licenciement forfaitaire n’est supposée.',
        'Le préavis indiqué est un repère de durée pour CDI. Cause, catégorie, préavis presté ou dispensé et droits plus favorables doivent être examinés.',
        'Les dettes de l’agent ne sont pas automatiquement déduites. L’accord écrit et les validations requis restent nécessaires.',
        'Le reçu du solde ne vaut pas renonciation aux droits du travailleur.']}
