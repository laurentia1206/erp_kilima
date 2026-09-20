"""Paie mensuelle : composition contractuelle, variables documentées et calcul figé."""
from decimal import Decimal as D, ROUND_DOWN
from .rh_calculs import simulation, arrondi, entier
from .rh_views import argent, texte, choix
from rest_framework.exceptions import ValidationError

TENSIONS = [100,116,133,154,178,206,237,274,317,366,422,488,564,651,752,868,1000]


def calculer(contrat, periode, p):
    if contrat.base_salaire != 'net':
        raise ValidationError('Cette paie concerne les contrats au net. Qualifiez la rémunération contractuelle avant préparation.')
    composition = contrat.remuneration.get('parametres', {})
    if not composition:
        raise ValidationError('Reprenez d’abord une simulation de rémunération dans le contrat de cet agent.')
    jours = argent(p.get('jours_payes'))
    if not 0 < jours <= 26:
        raise ValidationError('Jours rémunérés : de 0,01 à 26. Un mois sans rémunération doit être documenté parmi les exclusions.')
    tension = entier(p, 'tension', 100, 1000)
    if tension not in TENSIONS: raise ValidationError('Catégorie du barème SMIG invalide.')
    note = texte(p, 'controle_temps', 3000, True)
    variables = {k: argent(p.get(k, '0')) for k in ['primes_variables', 'heures_130', 'heures_160', 'heures_200']}
    if any(variables[k] > 250 for k in ['heures_130','heures_160','heures_200']):
        raise ValidationError('Vérifiez les heures supplémentaires du mois.')
    ref_variables = texte(p, 'reference_variables', 2000)
    if any(variables.values()) and not ref_variables:
        raise ValidationError('Les variables et heures supplémentaires exigent une référence de validation.')
    nuit = choix(p.get('regime_nuit'), ['aucun','exclusif','alternant_hotel','autre','exclusion_documentee'])
    heures_nuit = argent(p.get('heures_nuit', '0'))
    if heures_nuit > 310: raise ValidationError('Vérifiez les heures de nuit.')
    ref_nuit = texte(p, 'reference_nuit', 2000)
    if nuit != 'aucun' and not ref_nuit: raise ValidationError('Documentez le régime et la qualification du travail de nuit.')
    if nuit == 'aucun' and heures_nuit: raise ValidationError('Sélectionnez le régime du travail de nuit.')
    param = {**composition, 'date_reference': periode.mois+'-01', 'taux_cdf': periode.parametres['taux_cdf'],
             'source_taux': periode.parametres['source_taux'], 'jours_transport': entier(p,'jours_transport',0,31),
             'charges_famille': entier(p,'charges_famille',0,9),
             'reference_famille': texte(p,'reference_famille',300), 'trajet_cdf':str(argent(p.get('trajet_cdf','0')))}
    for k in ['brut_base','logement','transport','primes']:
        param[k] = str(arrondi(D(composition[k])*jours/26))
    cible = arrondi(contrat.salaire*jours/26)
    param['net_vise'] = str(cible)
    brut_initial = D(param['brut_base'])
    # Ajustement explicite du brut mensuel pour honorer le net ; contrat jamais modifié.
    def essai(centimes):
        return simulation({**param,'brut_base':str(D(centimes)/100)})[1]
    bas, haut = 1, max(100,int(cible*300))
    if D(essai(bas)['net']) > cible:
        raise ValidationError('Les indemnités dépassent le net proratisé. Revoyez la composition de rémunération avec les RH.')
    while D(essai(haut)['net']) < cible:
        haut *= 2
        if haut > 10000000000000: raise ValidationError('Net contractuel hors plage de calcul.')
    while haut-bas > 1:
        milieu = (haut+bas)//2
        if D(essai(milieu)['net']) < cible: bas=milieu
        else: haut=milieu
    regulier=essai(haut)
    if abs(D(regulier['net'])-cible) > D('.01'): raise ValidationError('Rapprochement du net requis avant calcul.')
    param['brut_base']=str(D(haut)/100)
    facteur=D(param['taux_cdf']) if contrat.devise=='USD' else D(1)
    smig_mensuel=D(21500)*26*tension/100
    minimum=arrondi(smig_mensuel*jours/26/facteur)
    if D(param['brut_base'])+D(param['primes']) < minimum:
        raise ValidationError('Rémunération inférieure au minimum de la catégorie sélectionnée : revoyez le contrat.')
    horaire=(D(param['brut_base'])+D(param['primes']))/jours*26/D(periode.parametres.get('heures_mensuelles_reference','195'))
    hs=arrondi(horaire*sum(variables[k]*t for k,t in [('heures_130',D('1.3')),('heures_160',D('1.6')),('heures_200',D(2))]))
    taux_nuit={'aucun':D(0),'exclusif':D('.10'),'alternant_hotel':D('.25'),'autre':D('.30'),'exclusion_documentee':D(0)}[nuit]
    majoration_nuit=arrondi(horaire*heures_nuit*taux_nuit)
    primes_fixes=param['primes']
    param['primes']=str(D(primes_fixes)+variables['primes_variables']+hs+majoration_nuit)
    param,r=simulation(param)
    base=D(r['base_cnss'])
    inpp=arrondi(base*D(periode.parametres['taux_inpp'])/100)
    onem=arrondi(base*D('.005'))
    # Code du travail art.114 : après impôt, cotisations et logement forfaitaire.
    saisissable=max(D(0),D(r['net'])-D(param['logement']))
    seuil=smig_mensuel*5/facteur
    plafond=(min(saisissable,seuil)/5+max(D(0),saisissable-seuil)/3).quantize(D('.01'),rounding=ROUND_DOWN)
    saisie={'jours_payes':str(jours),'tension':tension,'controle_temps':note,
            **{k:str(v) for k,v in variables.items()},'reference_variables':ref_variables,
            'regime_nuit':nuit,'heures_nuit':str(heures_nuit),'reference_nuit':ref_nuit,
            **{k:param[k] for k in ['jours_transport','charges_famille','reference_famille','trajet_cdf']}}
    r.update({'version':'RDC-PAIE-MENSUELLE-2026-v1','parametres_calcul':param,
              'nom':contrat.agent.nom,'matricule':contrat.agent.matricule,'numero_cnss':contrat.agent.numero_cnss,'nif':contrat.agent.nif,
              'contrat':contrat.reference,'net_contractuel':str(contrat.salaire),'net_proratise':str(cible),
              'ajustement_brut_net':str(arrondi(D(param['brut_base'])-brut_initial)),
              'primes_fixes':primes_fixes,'heures_supplementaires':str(hs),'majoration_nuit':str(majoration_nuit),
              'inpp':str(inpp),'onem':str(onem),'plafond_retenues':str(plafond),
              'cout_total':str(arrondi(D(r['cout_avec_cnss'])+inpp+onem)),
              'alertes':['Régime général salarié 2026. Les variables et les droits du mois doivent être rapprochés des pièces par les RH.',
                          'Le brut régulier est ajusté pour préserver le net contractuel proratisé, avant variables et remboursements.',
                          'INPP et ONEM : assiette salariale hors véritables indemnités de logement et transport, à confirmer lors du contrôle réglementaire.']})
    return saisie,r
