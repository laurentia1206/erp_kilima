/* Cycle de paie : les montants et autorisations sont calculés côté serveur. */
const RHMensuel=(()=>{
  const H=RH,prives=['RH','DRH','DFI'],payeurs=['CAISSIER_CENTRAL','CAISSIER_VENDEUR','COMPTABLE'];
  const etats={brouillon:'Préparation RH',controle:'Contrôlée · attend le DFI',valide:'Validée · à régler',cloture:'Clôturée'};
  const roles=()=>societes.find(s=>s.id===currentSocieteId)?.roles||[];
  const peut=rs=>roles().some(r=>rs.includes(r));
  const money=(v,d)=>`${fmtNum(v)} ${esc(d)}`;
  const num=(n,l,v='0',extra='')=>H.champ(n,l,'number',v,`min="0" step="0.01" required ${extra}`);
  function init(){
    NAV.find(g=>g.g==='Ressources humaines').items.push({v:'rh-mensuel',l:'Paie mensuelle',i:'ti-calendar-dollar',roles:[...prives,...payeurs]});
    TITLES['rh-mensuel']=['Paie mensuelle','Préparation, contrôle RH, validation DFI et règlement'];
    RENDER['rh-mensuel']=liste;
  }
  async function liste(){
    const el=$('#view-rh-mensuel');el.innerHTML='<p class="muted">Chargement des paies…</p>';
    try{const rows=await H.appel('paies');
      el.innerHTML=`<div class="rh-intro"><div><span class="rh-kicker">Fin de mois</span><h2>Une paie expliquée, contrôlée et suivie.</h2><p>Préparez les bulletins de la société, faites contrôler les variables, puis valider le montant à payer.</p></div>${peut(prives)?'<button class="btn btn-primary" data-new>+ Préparer un mois</button>':''}</div>
      <p class="banner">Préparation → contrôle RH → validation DFI → paiement → clôture. Les prêts et avances versés se remboursent selon leurs accords signés. Le décompte final reste un dossier distinct.</p>
      ${H.table(['Mois','Étape','Bulletins','Nets à payer',''],rows.map(o=>`<tr><td><b>${o.mois}</b></td><td>${etats[o.statut]}</td><td>${o.payes} réglés / ${o.nombre}</td><td>${money(o.totaux.USD,'USD')}<br>${money(o.totaux.CDF,'CDF')}</td><td><button class="btn" data-open="${o.id}">Ouvrir</button></td></tr>`))}`;
      el.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>ouvrir(b.dataset.open));
      if(el.querySelector('[data-new]'))el.querySelector('[data-new]').onclick=()=>nouveau();
    }catch(e){el.innerHTML=`<p class="err">${esc(e.message)}</p>`;}
  }
  function nouveau(o=null){
    const q=o?.parametres||{};
    H.formulaire('Préparer une paie mensuelle',H.champ('mois','Mois de paie','month',o?.mois||H.dateLocale().slice(0,7),'required min="2026-01" max="2026-12"'+(o?' readonly':''))+
      num('taux_cdf','Taux de paie : CDF pour 1 USD',q.taux_cdf||'','min="0.01"')+H.champ('source_taux','Source et date du taux','text',q.source_taux||'','required')+
      num('heures_mensuelles_reference','Heures normales mensuelles (45 h/semaine = 195 h)',q.heures_mensuelles_reference||'195','max="195" min="1"')+H.champ('effectif','Effectif total de la société (INPP)','number',q.effectif||'','required min="1" step="1"')+H.select('secteur','Employeur',[['prive','Secteur privé'],['public','Secteur public']],q.secteur||'prive')+
      H.zone('reference_reglementaire','Références fiscales et sociales vérifiées pour ce mois',q.reference_reglementaire||'')+
      '<p class="rh-wide banner">Régime général salarié RDC 2026. CNSS : 5 % salarié et 13 % employeur. ONEM : 0,5 %. INPP : 3,5 % jusqu’à 50 agents, 3 % de 51 à 300, 2 % au-delà ; secteur public 4 %. Le DFI devra confirmer les bases et les barèmes avant comptabilisation, notamment la méthode mensuelle IRPP et le texte INPP applicable.</p>',
      p=>H.appel('paies',{method:'POST',body:{...p,effectif:Number(p.effectif),...(o?{id:o.id,revision:o.revision}:{})}}),o?()=>ouvrir(o.id):liste);
  }
  async function ouvrir(id){
    const el=$('#view-rh-mensuel');el.innerHTML='<p class="muted">Chargement du mois…</p>';
    try{const o=await H.appel('paies/'+id),prive=peut(prives),draft=o.statut==='brouillon',refresh=()=>ouvrir(id);
      el.innerHTML=`<div class="rh-toolbar"><button class="btn" data-back>← Toutes les paies</button><b>${o.mois} · ${etats[o.statut]}</b></div>
      <div class="rh-intro"><div><span class="rh-kicker">${o.payes} / ${o.nombre} bulletins réglés</span><h2>${money(o.totaux.USD,'USD')} · ${money(o.totaux.CDF,'CDF')}</h2><p>${prive?'Le brut régulier est ajusté au net contractuel proratisé. Les variables et remboursements s’appliquent ensuite.':'Seuls les montants validés sont disponibles au paiement.'}</p></div></div>
      <div class="rh-toolbar">${prive&&draft?'<button class="btn btn-primary" data-add>+ Préparer un bulletin</button><button class="btn" data-params>Paramètres du mois</button>':''}${prive?'<button class="btn" data-etat>État de paie / imprimer</button><button class="btn" data-declarations>Préparer les déclarations</button>':''}
      ${draft&&peut(['RH','DRH'])?'<button class="btn btn-primary" data-action="controler">Terminer le contrôle RH</button>':''}${o.statut==='controle'&&prive?'<button class="btn" data-action="rouvrir">Rouvrir avec motif</button>':''}${o.statut==='controle'&&peut(['DFI'])?'<button class="btn btn-primary" data-action="valider">Valider et comptabiliser</button>':''}${o.statut==='valide'&&peut(['DFI'])?'<button class="btn btn-primary" data-action="cloturer">Clôturer la paie</button>':''}</div>
      ${H.table(['Agent','Net à payer','Règlement',''],o.bulletins.map(b=>`<tr><td><b>${esc(b.nom)}</b><div class="muted">${esc(b.matricule)}</div></td><td>${money(b.net_a_payer,b.devise)}</td><td>${b.paye?'Réglé'+(b.paiement?' · '+esc(b.paiement.date):' · net nul'):'À régler'}${b.paiement?'<div class="muted">'+esc(b.paiement.reference)+'</div>':''}</td><td>${prive?`<button class="btn" data-bulletin="${b.id}">Bulletin</button>`:''}${draft&&prive?` <button class="btn" data-edit="${b.id}">Recalculer</button>`:''}${o.statut==='valide'&&!b.paye&&peut(payeurs)?` <button class="btn btn-primary" data-pay="${b.id}">Enregistrer le paiement</button>`:''}</td></tr>`))}
      ${prive&&draft?'<p class="banner">Un pointage absent ne vaut pas absence. Les RH doivent rapprocher les jours rémunérés, congés et variables. Un agent sans bulletin devra faire l’objet d’une exclusion motivée au contrôle.</p>':''}
      <details><summary>Historique des décisions</summary>${o.decisions.map(x=>`<p>${esc(x.date.slice(0,10))} · ${esc(x.nom)} · ${esc(x.action)}<br>${esc(x.commentaire)}</p>`).join('')||'<p class="muted">Aucune décision.</p>'}</details>`;
      el.querySelector('[data-back]').onclick=liste;
      if(el.querySelector('[data-add]'))el.querySelector('[data-add]').onclick=()=>choisir(o,refresh);
      if(el.querySelector('[data-params]'))el.querySelector('[data-params]').onclick=()=>nouveau(o);
      el.querySelectorAll('[data-bulletin]').forEach(x=>x.onclick=()=>imprimerBulletin(o,o.bulletins.find(b=>b.id===x.dataset.bulletin)));
      el.querySelectorAll('[data-edit]').forEach(x=>x.onclick=()=>editer(o,o.contrats.find(c=>c.id===o.bulletins.find(b=>b.id===x.dataset.edit).contrat_id),o.bulletins.find(b=>b.id===x.dataset.edit),refresh));
      el.querySelectorAll('[data-pay]').forEach(x=>x.onclick=()=>payer(o,o.bulletins.find(b=>b.id===x.dataset.pay),refresh));
      el.querySelectorAll('[data-action]').forEach(x=>x.onclick=()=>decider(o,x.dataset.action,refresh));
      if(prive){el.querySelector('[data-etat]').onclick=()=>etat(o);el.querySelector('[data-declarations]').onclick=()=>declarations(o);}
    }catch(e){el.innerHTML=`<p class="err">${esc(e.message)}</p><button class="btn" id="rh-mois-retour">Retour</button>`;$('#rh-mois-retour').onclick=liste;}
  }
  function choisir(o,refresh){
    const cs=o.contrats.filter(c=>!o.bulletins.some(b=>b.agent_id===c.agent_id));
    if(!cs.length){toast('Aucun contrat restant à préparer. Les contrats doivent inclure une composition issue du simulateur.','ko');return;}
    const root=H.formulaire('Choisir le contrat',H.select('contrat_id','Agent et contrat',cs.map(c=>[c.id,c.matricule+' — '+c.nom+' · '+c.reference])),()=>{},()=>{});
    root.querySelector('form').onsubmit=e=>{e.preventDefault();const c=cs.find(x=>x.id===root.querySelector('[name=contrat_id]').value);closeModal();editer(o,c,null,refresh);};
  }
  async function editer(o,c,b,refresh){
    if(!c){toast('Le contrat a changé. Rechargez la paie.','ko');return;}
    if(!c.composition?.brut_base){
      try{const simulations=(await H.appel('simulations')).filter(s=>s.resultat.devise===c.devise&&Number(s.resultat.net)===Number(c.net));
        if(!simulations.length){toast('Conservez d’abord une simulation correspondant exactement au net du contrat : '+money(c.net,c.devise)+'. Revenez ensuite préparer ce bulletin.','ko');return;}
        H.formulaire('Compléter la composition du contrat — '+c.nom,`<p class="rh-wide">Ce contrat a un net de ${money(c.net,c.devise)}. Choisissez une simulation donnant ce même net pour conserver le détail brut, logement, transport et primes.</p>`+H.select('simulation_id','Proposition de rémunération',simulations.map(s=>[s.id,s.nom+' · '+s.parametres.date_reference])),
          p=>H.appel(`contrats/${c.id}/composition`,{method:'POST',body:{...p,revision:c.revision}}),refresh);
      }catch(e){toast(e.message,'ko');}return;
    }
    const p=b?.saisie||{},comp=c.composition,dettes=o.dettes.filter(d=>d.agent_id===c.agent_id&&d.devise===c.devise&&Number(d.echeance)>0);
    const root=H.formulaire('Préparer le bulletin — '+c.nom,
      `<p class="banner rh-wide">Net contractuel : <b>${money(c.net,c.devise)}</b>. Le net régulier est proratisé sur 26 jours ; l’ajustement éventuel du brut reste visible sur le bulletin. Contrat à partir du ${esc(c.debut)}${c.fin?' jusqu’au '+esc(c.fin):''}.</p>`+
      num('jours_payes','Jours rémunérés validés (base 26)',p.jours_payes||'26','max="26" min="0.01"')+H.select('tension','Catégorie SMIG — coefficient',[100,116,133,154,178,206,237,274,317,366,422,488,564,651,752,868,1000].map(v=>[String(v),String(v)]),String(p.tension||100))+
      H.zone('controle_temps','Rapprochement présence, congés, absences et jours payés',p.controle_temps||'')+
      num('primes_variables','Primes variables brutes du mois',p.primes_variables||'0')+
      num('heures_130','Heures supplémentaires à 130 %',p.heures_130||'0')+num('heures_160','Heures supplémentaires à 160 %',p.heures_160||'0')+num('heures_200','Heures supplémentaires à 200 %',p.heures_200||'0')+
      H.zone('reference_variables','Référence des variables et heures approuvées',p.reference_variables||'')+
      H.select('regime_nuit','Travail de nuit',[['aucun','Aucun'],['exclusif','Travail exclusivement nocturne — 10 %'],['alternant_hotel','Alternance jour / nuit en hôtel — 25 %'],['autre','Autre travail de nuit — 30 %'],['exclusion_documentee','Exclusion légale documentée']],p.regime_nuit||'aucun')+
      num('heures_nuit','Heures de nuit rémunérées',p.heures_nuit||'0')+H.zone('reference_nuit','Qualification du régime de nuit et justificatifs',p.reference_nuit||'')+
      H.champ('jours_transport','Jours de déplacement','number',p.jours_transport??comp.jours_transport,'required min="0" max="31" step="1"')+num('trajet_cdf','Coût justifié du trajet en CDF',p.trajet_cdf??comp.trajet_cdf)+
      H.champ('charges_famille','Charges de famille fiscalement admises','number',p.charges_famille??comp.charges_famille,'required min="0" max="9" step="1"')+H.champ('reference_famille','Justificatifs des charges de famille','text',p.reference_famille??comp.reference_famille)+
      '<h3 class="rh-wide">Remboursements convenus</h3><p class="rh-wide muted">Saisissez uniquement les retenues prévues par les accords. La quotité légale et le solde seront contrôlés. Une échéance non retenue n’est pas reportée automatiquement.</p>'+
      (dettes.map(d=>num('dette_'+d.id,`${d.nature==='pret_personnel'?'Prêt':'Avance'} ${d.id.slice(0,8)} · échéance ${money(d.echeance,d.devise)}`,b?.retenues.find(x=>x.dette_id===d.id)?.montant||'0')).join('')||'<p class="rh-wide muted">Aucun prêt ou avance versé avec échéance ce mois.</p>'),
      p=>H.appel(`paies/${o.id}/preparer`,{method:'POST',body:{...p,revision:o.revision,contrat_id:c.id,tension:Number(p.tension),jours_transport:Number(p.jours_transport),charges_famille:Number(p.charges_famille),retenues:dettes.filter(d=>Number(p['dette_'+d.id])>0).map(d=>({dette_id:d.id,montant:p['dette_'+d.id]}))}}),refresh);
    root.querySelector('[data-save-rh]').textContent='Calculer et conserver le bulletin';
  }
  function decider(o,action,refresh){
    const manquants=[...new Map((o.contrats||[]).filter(c=>!o.bulletins.some(b=>b.agent_id===c.agent_id)).map(c=>[c.agent_id,c])).values()];
    const titres={controler:'Terminer le contrôle RH',rouvrir:'Rouvrir la préparation',valider:'Valider et comptabiliser la paie',cloturer:'Clôturer le mois'};
    H.formulaire(titres[action],`<p class="rh-wide">${o.mois} · ${o.nombre} bulletins · ${money(o.totaux.USD,'USD')} · ${money(o.totaux.CDF,'CDF')}</p>`+
      (action==='controler'?manquants.map(c=>H.champ('ex_'+c.agent_id,'Motif d’exclusion — '+esc(c.nom),'text','','required')).join(''):'')+
      (action==='valider'?'<p class="banner rh-wide">Cette validation fige les bulletins et crée les écritures comptables. Vérifiez les assiettes, les taux applicables et les arrondis IRPP avec vos références fiscales.</p><label class="rh-wide"><input type="checkbox" name="reglementation_verifiee" required> J’ai rapproché les calculs fiscaux et sociaux, notamment IRPP et INPP, des références applicables.</label>':'')+
      H.zone('commentaire','Vérifications effectuées et commentaire'),p=>H.appel(`paies/${o.id}/decision`,{method:'POST',body:{...p,action,revision:o.revision,reglementation_verifiee:p.reglementation_verifiee==='on',exclusions:manquants.map(c=>({agent_id:c.agent_id,motif:p['ex_'+c.agent_id]}))}}),refresh);
  }
  function imprimerBulletin(o,b){
    const r=b.resultat,p=r.parametres_calcul,dev=b.devise;
    H.imprimer('Bulletin de paie — '+esc(b.nom),`${o.mois} · ${esc(b.matricule)} · ${etats[o.statut]} · ${b.paye?'Réglé':'Non réglé'}`,['Rubrique','Montant / détail'],[
      ['Contrat',esc(r.contrat)],['Jours rémunérés',b.saisie.jours_payes],['Net contractuel mensuel',money(r.net_contractuel,dev)],['Net régulier proratisé',money(r.net_proratise,dev)],
      ['Brut de base du mois',money(p.brut_base,dev)],['Dont ajustement du brut pour maintien du net',money(r.ajustement_brut_net,dev)],['Primes fixes',money(r.primes_fixes,dev)],['Primes variables',money(b.saisie.primes_variables,dev)],['Heures supplémentaires',money(r.heures_supplementaires,dev)],['Majoration de nuit',money(r.majoration_nuit,dev)],['Logement',money(p.logement,dev)],['Transport',money(p.transport,dev)],['Total brut',money(r.brut_total,dev)],
      ['CNSS salarié',money(r.cnss_salarie,dev)],['IRPP',money(r.irpp,dev)],['Net avant remboursements',money(r.net,dev)],...b.retenues.map(x=>['Remboursement accord '+x.dette_id.slice(0,8),money(x.montant,dev)]),['Net à payer',money(b.net_a_payer,dev)],['CNSS employeur',money(r.cnss_employeur,dev)],['INPP employeur',money(r.inpp,dev)],['ONEM employeur',money(r.onem,dev)],['Coût employeur',money(r.cout_total,dev)],['Taux de paie',`1 USD = ${fmtNum(o.parametres.taux_cdf)} CDF`],['Paiement',b.paiement?esc(b.paiement.date+' · '+b.paiement.mode+' · '+b.paiement.reference):'Non versé'],['Rapprochement du temps',esc(b.saisie.controle_temps)]],o.statut==='brouillon'||o.statut==='controle'?'PROJET — non validé, ne vaut pas ordre de paiement.':'Bulletin figé après validation DFI. Signature du bénéficiaire : ____________________');
  }
  function etat(o){H.imprimer('État de paie',o.mois+' · '+etats[o.statut],['Matricule','Agent','Devise','Brut','CNSS salarié','IRPP','Retenues','Net à payer','Règlement'],o.bulletins.map(b=>[esc(b.matricule),esc(b.nom),b.devise,fmtNum(b.resultat.brut_total),fmtNum(b.resultat.cnss_salarie),fmtNum(b.resultat.irpp),fmtNum(b.resultat.retenues_total),fmtNum(b.net_a_payer),b.paye?'Réglé':'Non réglé']),'Les totaux doivent être rapprochés séparément par devise.');}
  function declarations(o){
    const rows=o.bulletins.map(b=>{const r=b.resultat;return [esc(b.matricule),esc(b.nom),esc(r.numero_cnss||'À compléter'),...['base_cnss','cnss_salarie','cnss_employeur','base_irpp','irpp','inpp','onem'].map(k=>fmtNum(b.declarations_cdf[k])),b.paiement?.date||'Non payé'];});
    H.imprimer('Préparation des déclarations sociales et fiscales — CDF',o.mois+' · '+etats[o.statut],['Matricule','Agent','CNSS','Base sociale','CNSS salarié','CNSS employeur','Base IRPP','IRPP','INPP','ONEM','Date de règlement'],rows,
      'État de rapprochement, non transmis aux organismes. IRPP et ONEM : rapprocher avec le mois de paiement ; CNSS : mois de service. Vérifier identifiants, assiettes, taux de conversion et formats officiels avant dépôt. Aucun coefficient de minoration n’est appliqué.');
  }
  function payer(o,b,refresh){
    const modes=peut(['CAISSIER_CENTRAL','CAISSIER_VENDEUR'])?[['caisse','Espèces en caisse'],['banque','Virement bancaire confirmé']]:[['banque','Virement bancaire confirmé']];
    const root=H.formulaire('Enregistrer le paiement — '+b.nom,`<p class="banner rh-wide">Net validé : <b>${money(b.net_a_payer,b.devise)}</b>. Enregistrez le versement effectif une seule fois. Le logiciel n’envoie pas de virement à la banque.</p>`+
      H.select('mode','Mode de règlement',modes)+H.champ('date','Date du versement','date',H.dateLocale(),'required')+
      H.select('caisse_id','Caisse de la société',o.caisses.map(c=>[c.id,c.libelle]))+H.select('compte_bancaire_id','Compte bancaire de la société',o.banques.filter(c=>c.devise===b.devise).map(c=>[c.id,c.libelle]))+
      H.champ('reference','Référence du reçu signé / du virement','text','','required maxlength="64"')+
      '<label class="rh-wide" data-bank-confirm><input type="checkbox" name="virement_confirme"> Le virement a été exécuté et confirmé par la banque.</label>',
      p=>H.appel(`bulletins/${b.id}/payer`,{method:'POST',body:{...p,revision:b.revision,virement_confirme:p.virement_confirme==='on'}}),refresh);
    const f=root.querySelector('form'),mode=f.querySelector('[name=mode]');
    const update=()=>{for(const [name,visible]of [['caisse_id',mode.value==='caisse'],['compte_bancaire_id',mode.value==='banque']]){const e=f.querySelector('[name='+name+']');e.closest('label').hidden=!visible;e.disabled=!visible;}f.querySelector('[data-bank-confirm]').hidden=mode.value!=='banque';};mode.onchange=update;update();
    root.querySelector('[data-save-rh]').textContent='Confirmer le paiement effectif';
  }
  return {init};
})();
