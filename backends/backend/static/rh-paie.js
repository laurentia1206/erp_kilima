/* Propositions de rémunération : calcul serveur, puis reprise explicite au contrat. */
const RHPaie=(()=>{
  const H=RH,prives=['RH','DRH','DFI'];
  const num=(n,l,v='0',extra='')=>H.champ(n,l,'number',v,`min="0" step="0.01" required ${extra}`);
  const monnaie=(n,d)=>`${fmtNum(n)} ${esc(d)}`;
  const roles=()=>societes.find(s=>s.id===currentSocieteId)?.roles||[];
  function init(){
    NAV.find(g=>g.g==='Ressources humaines').items.push(
      {v:'rh-simulateur',l:'Simulateur d’engagement',i:'ti-calculator',roles:prives},
      {v:'rh-decomptes',l:'Décomptes finals',i:'ti-file-description',roles:prives});
    TITLES['rh-simulateur']=['Simulateur d’engagement','Composer la rémunération et vérifier le net convenu'];
    TITLES['rh-decomptes']=['Décomptes finals','Préparer et documenter les droits de départ'];
    RENDER['rh-simulateur']=render;RENDER['rh-decomptes']=decomptes;
  }
  function resultats(s){
    const r=s.resultat,p=s.parametres,d=r.devise;
    return `<div class="rh-net"><span>Net mensuel simulé</span><strong>${monnaie(r.net,d)}</strong><p>Écart avec le net visé : <b>${Number(r.ecart_net_vise)>0?'+':''}${monnaie(r.ecart_net_vise,d)}</b></p></div>`+
      H.table(['Calcul','Montant'],[['Brut de base',p.brut_base],['Primes brutes',p.primes],['Logement',p.logement],['Transport',p.transport],['Total des composantes',r.brut_total],['CNSS salarié — 5 %',r.cnss_salarie],['IRPP salarié',r.irpp],['Net avant remboursements',r.net],['CNSS employeur — 13 %',r.cnss_employeur],['Coût avec CNSS (hors autres charges)',r.cout_avec_cnss]].map(([l,v])=>`<tr><td>${l}</td><td>${monnaie(v,d)}</td></tr>`))+
      `<details><summary>Voir les bases et les tranches fiscales</summary><p>Base CNSS : ${monnaie(r.base_cnss,d)} · Base IRPP : ${monnaie(r.base_irpp_cdf,'CDF')}</p><p>Logement exonéré IRPP : ${monnaie(r.logement_exonere_irpp,d)} · Transport exonéré : ${monnaie(r.transport_exonere_irpp,d)}</p><p>IRPP calculé : ${monnaie(r.irpp_cdf,'CDF')} · Revenu annuel arrondi : ${monnaie(r.detail_irpp.revenu_annuel_arrondi,'CDF')}</p>${H.table(['Tranche annuelle','Taux','Impôt annuel CDF'],r.detail_irpp.tranches.map(t=>`<tr><td>${fmtNum(t.base_annuelle)}</td><td>${t.taux} %</td><td>${fmtNum(t.impot_annuel)}</td></tr>`))}<p>Réduction familiale annuelle : ${monnaie(r.detail_irpp.reduction_famille_annuelle,'CDF')}</p><p>Version : ${esc(r.version)}</p></details>`+
      `<details class="rh-hypotheses"><summary>Hypothèses et vérifications avant engagement</summary><ul>${r.alertes.map(a=>`<li>${esc(a)}</li>`).join('')}</ul></details>`;
  }
  function imprimer(s){const p=s.parametres,r=s.resultat;
    H.imprimer('Proposition de rémunération — '+esc(s.nom||'Simulation'),`Simulation au ${p.date_reference} · ${esc(r.version)} · 1 USD = ${fmtNum(p.taux_cdf)} CDF · ${esc(p.source_taux)}`,
      ['Rubrique','Montant / information'],[
        ['Brut de base',monnaie(p.brut_base,p.devise)],['Primes',monnaie(p.primes,p.devise)],['Logement',monnaie(p.logement,p.devise)],['Transport',monnaie(p.transport,p.devise)],
        ['Total composantes',monnaie(r.brut_total,p.devise)],['Base CNSS',monnaie(r.base_cnss,p.devise)],['CNSS salarié',monnaie(r.cnss_salarie,p.devise)],['Base IRPP CDF',fmtNum(r.base_irpp_cdf)],['IRPP',monnaie(r.irpp,p.devise)],['Net simulé',monnaie(r.net,p.devise)],['Net visé',monnaie(p.net_vise,p.devise)],['Écart',monnaie(r.ecart_net_vise,p.devise)],['CNSS employeur',monnaie(r.cnss_employeur,p.devise)],
        ['Transport justifié',`${p.jours_transport} jours · trajet : ${fmtNum(p.trajet_cdf)} CDF · maximum 6 trajets/jour`],['Indemnités — références',esc(p.justification_indemnites)],['Charges de famille',`${p.charges_famille} · ${esc(p.reference_famille)}`],
        ...r.alertes.map(a=>['À vérifier',esc(a)])],'Proposition à vérifier — ne vaut ni contrat signé, ni bulletin de paie, ni déclaration.');
  }
  async function render(initial={}){
    const el=$('#view-rh-simulateur'),sid=currentSocieteId;
    el.innerHTML='<p class="muted">Chargement du simulateur…</p>';
    try{
      const archives=await H.appel('simulations');let calc=null;const p=initial.parametres||{};
      el.innerHTML=`<div class="rh-intro"><div><span class="rh-kicker">Préparer un engagement</span><h2>Du brut proposé au net convenu.</h2><p>Ajustez les composantes mensuelles, calculez le net, puis conservez la proposition à reprendre au contrat.</p></div></div>
        <div class="rh-sim-layout"><section class="card"><div class="card-body"><form id="rh-sim-form" class="rh-form">
        ${H.champ('date_reference','Date de simulation','date',p.date_reference||H.dateLocale(),'required min="2026-01-01" max="2026-12-31"')}
        ${H.select('devise','Devise des composantes',[['USD','USD'],['CDF','CDF']],p.devise||'USD')}
        ${num('taux_cdf','Change : CDF pour 1 USD',p.taux_cdf||'','min="0.01"')}${H.champ('source_taux','Référence du taux (date / source)','text',p.source_taux||'','required')}
        ${num('brut_base','Salaire brut de base',p.brut_base||'')}${num('net_vise','Net mensuel visé',p.net_vise||'')}
        ${num('logement','Indemnité de logement',p.logement||'0')}${num('transport','Indemnité de transport',p.transport||'0')}
        ${num('primes','Primes brutes incluses dans la proposition',p.primes||'0')}
        ${H.champ('jours_transport','Jours de déplacement / mois','number',p.jours_transport??26,'required min="0" max="31" step="1"')}
        ${num('trajet_cdf','Coût justifié d’un trajet en CDF',p.trajet_cdf||'0')}
        ${H.champ('charges_famille','Charges de famille fiscalement admises','number',p.charges_famille??0,'required min="0" max="9" step="1"')}
        ${H.zone('justification_indemnites','Logement / transport : nature réelle et justificatifs',p.justification_indemnites||'')}
        ${H.champ('reference_famille','Référence des justificatifs familiaux','text',p.reference_famille||'')}
        <p class="muted rh-wide">Les primes sont imposables et cotisables. Le coût du trajet est celui du taxi pour un cadre, du bus pour les autres salariés. Le net affiché précède tout remboursement de dette.</p>
        <p class="err rh-wide" role="alert"></p><button class="btn btn-primary rh-wide" type="submit">Calculer le net</button></form></div></section>
        <section class="card"><div class="card-body"><div id="rh-sim-result"><div class="rh-empty"><i class="ti ti-calculator"></i><h3>Votre proposition apparaîtra ici</h3><p>Renseignez les composantes et le taux de change, puis calculez le net.</p></div></div><div class="rh-toolbar"><button class="btn btn-primary" id="rh-sim-save" disabled>Conserver la proposition</button><button class="btn" id="rh-sim-print" disabled>Imprimer</button></div></div></section></div>
        <h3>Propositions conservées pour cette société</h3>${H.table(['Proposition','Date','Net simulé',''],archives.map(s=>`<tr><td>${esc(s.nom)}</td><td>${s.parametres.date_reference}</td><td>${monnaie(s.resultat.net,s.resultat.devise)}</td><td><button class="btn" data-sim-open="${s.id}">Consulter / reprendre</button></td></tr>`))}`;
      const f=$('#rh-sim-form'),save=$('#rh-sim-save'),print=$('#rh-sim-print');
      f.oninput=()=>{calc=null;save.disabled=print.disabled=true;$('#rh-sim-result').innerHTML='<p class="banner">Les composantes ont changé. Recalculez pour obtenir le nouveau net.</p>';};
      f.onsubmit=async e=>{e.preventDefault();const b=f.querySelector('[type=submit]');b.disabled=true;f.querySelector('.err').textContent='';
        try{const data=Object.fromEntries(new FormData(f));data.jours_transport=Number(data.jours_transport);data.charges_famille=Number(data.charges_famille);
          const capture=JSON.stringify(data);const r=await H.appel('simuler',{method:'POST',body:data},sid);
          const actuel=Object.fromEntries(new FormData(f));actuel.jours_transport=Number(actuel.jours_transport);actuel.charges_famille=Number(actuel.charges_famille);
          if(sid!==currentSocieteId||!f.isConnected||capture!==JSON.stringify(actuel))return;
          calc=r;$('#rh-sim-result').innerHTML=resultats(calc);save.disabled=print.disabled=false;
        }catch(err){f.querySelector('.err').textContent=err.message;}finally{b.disabled=false;}};
      print.onclick=()=>{if(calc)imprimer(calc);};
      save.onclick=()=>{if(!calc)return;const r=calc;H.formulaire('Conserver cette proposition',H.champ('nom','Nom / référence de la proposition','text',initial.nom||'','required maxlength="180"')+`<p class="rh-wide">Net simulé : ${monnaie(r.resultat.net,r.resultat.devise)}. Les composantes et règles de ce calcul seront conservées ensemble.</p>`,v=>H.appel('simulations',{method:'POST',body:{...r.parametres,nom:v.nom}},sid),()=>render());};
      el.querySelectorAll('[data-sim-open]').forEach(b=>b.onclick=()=>ouvrir(archives.find(s=>s.id===b.dataset.simOpen)));
    }catch(e){el.innerHTML=`<p class="err">${esc(e.message)}</p>`;}
  }
  function ouvrir(s){
    modal({wide:true,title:s.nom,body:resultats(s),footer:'<button class="btn" data-print>Imprimer</button><button class="btn" data-recalcul>Nouvelle variante</button><button class="btn btn-primary" data-contrat>Reprendre pour un contrat</button>'});
    const root=$('#modal-root').lastElementChild;
    root.querySelector('[data-print]').onclick=()=>imprimer(s);
    root.querySelector('[data-recalcul]').onclick=()=>{closeModal();render(s);};
    root.querySelector('[data-contrat]').onclick=async()=>{try{
      const agents=await H.appel('agents');if(!agents.length)throw new Error('Créez d’abord le dossier de l’agent dans Personnel & pointages.');
      closeModal();H.formulaire('Choisir le dossier agent',H.select('agent_id','Agent',agents.map(a=>[a.id,a.matricule+' — '+a.nom])),()=>{},()=>{});
      const r=$('#modal-root').lastElementChild;r.querySelector('form').onsubmit=e=>{e.preventDefault();const a=agents.find(a=>a.id===r.querySelector('[name=agent_id]').value);closeModal();H.contrat(a,s,()=>render());};
    }catch(e){toast(e.message,'ko');}};
  }
  function imprimerDecompte(d){const p=d.parametres,r=d.resultat;
    H.imprimer('Préparation du décompte final — '+esc(r.nom),`${esc(r.matricule)} · Contrat ${esc(r.reference_contrat)} · Départ ${d.date_depart} · ${esc(d.motif)}`,
      ['Élément','Détail'],[['Années de service',r.annees_service],['Rémunération brute de référence',monnaie(p.remuneration_reference,r.devise)],['Moyenne mensuelle des variables sur 12 mois',monnaie(p.moyenne_variables_12m,r.devise)],['Diviseur journalier',p.diviseur_journalier],['Reliquat de salaire brut',monnaie(p.reliquat_salaire,r.devise)],['Jours de congés restants',p.jours_conges],['Référence du solde de congés',esc(p.reference_solde_conges)],['Indemnité de congés',monnaie(r.indemnite_conges,r.devise)],['Préavis retenu',`${p.preavis_mois} mois + ${p.preavis_jours} jours`],['Indemnité de préavis',monnaie(r.indemnite_preavis,r.devise)],['Autres droits documentés',monnaie(p.autres_droits,r.devise)],['TOTAL DES DROITS BRUTS',monnaie(r.total_droits_bruts,r.devise)],['Calculs et justificatifs',esc(p.references)],...r.alertes.map(a=>['À contrôler',esc(a)])],
      'Préparation uniquement — net final, retenues et validations à compléter avant paiement.');
  }
  async function decomptes(){
    const el=$('#view-rh-decomptes');el.innerHTML='<p class="muted">Chargement…</p>';
    try{const [rows,agents]=await Promise.all([H.appel('decomptes'),H.appel('agents')]);
      el.innerHTML=`<div class="rh-intro"><div><span class="rh-kicker">Fin de contrat</span><h2>Des droits de départ détaillés.</h2><p>Rapprochez le contrat, les congés et les rémunérations antérieures pour préparer le décompte.</p></div></div><p class="banner">Cette première étape calcule les droits bruts. Le calcul du net final et son circuit de paiement sont encore en cours de réalisation. Les dettes ne sont pas déduites ici.</p><div class="rh-toolbar"><button class="btn btn-primary" id="rh-dc-new">+ Préparer un décompte</button></div>${H.table(['Agent','Départ','Motif','Droits bruts',''],rows.map(d=>`<tr><td>${esc(d.resultat.nom)}</td><td>${d.date_depart}</td><td>${esc(d.motif)}</td><td>${monnaie(d.resultat.total_droits_bruts,d.resultat.devise)}</td><td><button class="btn" data-dc="${d.id}">Détail / imprimer</button></td></tr>`))}`;
      el.querySelectorAll('[data-dc]').forEach(b=>b.onclick=()=>imprimerDecompte(rows.find(d=>d.id===b.dataset.dc)));
      $('#rh-dc-new').onclick=()=>{
        if(!agents.length){toast('Créez d’abord le dossier et le contrat de l’agent.','ko');return;}
        H.formulaire('Choisir un agent',H.select('agent_id','Agent',agents.map(a=>[a.id,a.matricule+' — '+a.nom])),()=>{},()=>{});
        const root=$('#modal-root').lastElementChild;root.querySelector('form').onsubmit=async e=>{e.preventDefault();try{const d=await H.appel(`agents/${root.querySelector('[name=agent_id]').value}/dossier`);if(!d.contrats.length)throw new Error('Enregistrez d’abord le contrat de cet agent.');closeModal();formDecompte(d);}catch(err){root.querySelector('.err').textContent=err.message;}};
      };
    }catch(e){el.innerHTML=`<p class="err">${esc(e.message)}</p>`;}
  }
  function formDecompte(d){
    H.formulaire('Préparer les droits bruts — '+d.agent.nom,
      H.select('contrat_id','Contrat concerné',d.contrats.map(c=>[c.id,c.reference+' · '+c.devise+' · '+c.type_contrat]))+
      H.champ('date_depart','Date effective du départ','date',H.dateLocale(),'required')+
      H.select('motif','Motif',[['','Choisir le motif'],['fin_cdd','Fin de CDD'],['demission','Démission'],['licenciement','Licenciement'],['retraite','Retraite'],['accord','Accord des parties'],['deces','Décès']])+
      H.select('categorie_preavis','Catégorie à vérifier pour le préavis',[['I_V','Catégories I à V'],['maitrise','Agent de maîtrise'],['cadre','Cadre / direction']])+
      '<p class="muted rh-wide">CDI, repères employeur : catégories I–V, 14 jours ouvrables + 7 par année ; maîtrise, 1 mois + 8 jours par année ; cadre, 3 mois + 15 jours par année. Démission : moitié. Saisissez ci-dessous uniquement le préavis réellement indemnisable, après examen du motif et du préavis déjà presté.</p>'+
      num('remuneration_reference','Rémunération brute mensuelle de référence','')+num('moyenne_variables_12m','Moyenne mensuelle des variables sur 12 mois')+
      num('reliquat_salaire','Salaire brut restant dû (hors éléments ci-dessous)')+H.champ('diviseur_journalier','Diviseur pour un jour rémunéré','number',26,'required min="1" max="31" step="1"')+
      num('jours_conges','Jours de congés non pris, solde vérifié')+num('autres_droits','Autres droits bruts documentés')+
      num('preavis_mois','Préavis à indemniser — mois')+num('preavis_jours','Préavis à indemniser — jours supplémentaires')+
      H.zone('reference_solde_conges','Origine du solde de congés (registre, périodes, jours pris)')+
      H.zone('references','Calculs et pièces : base brute, moyenne des primes, motif, préavis, autres droits. Évitez de compter deux fois les mêmes sommes.'),
      p=>H.appel('decomptes',{method:'POST',body:{...p,agent_id:d.agent.id,diviseur_journalier:Number(p.diviseur_journalier)}}),decomptes);
  }
  return {init};
})();
