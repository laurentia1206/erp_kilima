/* Suivi des files métier. Les autorisations et les délais sont calculés au serveur. */
const Pilotage=(()=>{
  let data=null, sid=null, scope='moi', busy=false, page=1, lastBadge=0;
  const filters={q:'',module:'',user:'',niveau:''};
  const niveaux={a_attribuer:'Affectation à vérifier',escalade:'Remontée DFI',relance:'Relance',a_traiter:'À traiter'};
  const el=()=>document.querySelector('#view-pilotage');
  const dfi=()=>societes.find(s=>s.id===currentSocieteId)?.roles.includes('DFI');
  const date=v=>v?new Date(v).toLocaleString('fr-FR',{dateStyle:'short',timeStyle:'short'}):'Non renseignée';
  const age=h=>h==null?'Date indisponible':h<24?`${Math.floor(h)} h`:`${Math.floor(h/24)} j ${Math.floor(h%24)} h`;
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  function reset(){data=null;sid=null;scope='moi';lastBadge=0;Object.keys(filters).forEach(k=>filters[k]='');const b=document.querySelector('#pilotage-alertes');if(b){b.textContent='Suivi des tâches';b.classList.remove('pilot-alert');}}
  function filtrer(rows,f){return rows.filter(r=>(!f.module||r.module===f.module)&&(!f.niveau||r.niveau===f.niveau)&&(!f.user||r.responsables.some(u=>u.id===f.user))&&norm([r.reference,r.action,r.detail,...r.responsables.map(u=>u.nom),...r.roles].join(' ')).includes(norm(f.q)));}
  function init(){
    NAV.find(g=>g.g==='Pilotage').items.push({v:'pilotage',l:'Suivi des tâches',i:'ti-list-check'});
    TITLES.pilotage=['Suivi des tâches','Responsables, relances et points à débloquer'];RENDER.pilotage=ouvrir;
    const button=document.createElement('button');button.id='pilotage-alertes';button.className='btn btn-sm';button.textContent='Suivi des tâches';
    button.onclick=()=>go('pilotage');document.querySelector('.topbar-right').prepend(button);
    setInterval(()=>{if(!token||!me||!currentSocieteId||document.hidden)return;if(activeView==='pilotage')charger();else if(Date.now()-lastBadge>120000)badge();},30000);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden&&token&&me&&currentSocieteId){if(activeView==='pilotage')charger();else badge();}});
  }
  function shell(){
    el().innerHTML=`<div class="pilot-hero"><div><span class="pilot-kicker">Pilotage opérationnel</span><h2>Voir ce qui attend. Débloquer ce qui suit.</h2><p>Une vue des dossiers enregistrés, des personnes habilitées et des étapes à terminer.</p></div><div class="pilot-live" id="pilot-live" role="status">Chargement…</div></div>
    <div class="pilot-toolbar"><label>Périmètre<select id="pilot-scope" class="form-select"><option value="moi">Mes tâches</option>${dfi()?'<option value="equipe">Équipe · supervision DFI</option>':''}</select></label><button class="btn" id="pilot-refresh">Actualiser</button>${dfi()?'<button class="btn" id="pilot-policy">Régler les délais</button>':''}<button class="btn" id="pilot-pdf">Rapport PDF / imprimer</button><button class="btn" id="pilot-excel">Excel</button></div>
    <div id="pilot-error" role="alert"></div><div id="pilot-kpis" class="pilot-kpis"></div>
    <div class="pilot-filters"><label>Recherche<input class="form-input" id="pilot-q" type="search" placeholder="Dossier, tâche, responsable…"></label><label>Module<select class="form-select" id="pilot-module"></select></label><label>Utilisateur habilité<select class="form-select" id="pilot-user"></select></label><label>Priorité<select class="form-select" id="pilot-niveau"><option value="">Toutes les priorités</option>${Object.entries(niveaux).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><button class="btn" id="pilot-reset">Effacer les filtres</button></div>
    <div id="pilot-result"></div><details class="pilot-help"><summary>Comment lire ce suivi ?</summary><p>Une tâche peut attendre une personne nommée ou une équipe habilitée. La présence d’un dossier dans la file d’un utilisateur ne prouve pas une faute personnelle. Plusieurs validateurs peuvent avoir une action sur le même dossier.</p><p>L’ancienneté utilise la date indiquée dans le détail. Lorsqu’une date d’étape n’existe pas, la date de création est utilisée et signalée. Les délais sont en heures calendaires, nuits et week-ends compris. Une échéance métier dépassée remonte au DFI ; elle n’est pas remplacée par le délai de suivi.</p><p>Les relances sont internes à l’ERP : elles apparaissent automatiquement quand l’application est ouverte, sans courriel ni notification téléphone. Le suivi se rafraîchit toutes les 30 secondes sur cet écran, toutes les 2 minutes pour le compteur ailleurs. Une tâche traitée disparaît au prochain rafraîchissement.</p><p>Couverture actuelle : réquisitions, ordres, avances, transferts, comptabilité, inventaires, réceptions fournisseurs, pointages saisis, demandes d’avance et paie. Sont aussi suivis : courses à valider ou facturer, interventions ouvertes, documents de flotte à renouveler, arrivées et départs prévus, commandes clients hors groupe à facturer et dossiers TVA sauvegardés sans référence de dépôt. Les tâches jamais saisies, congés, déclarations sociales, facturation des engins et certaines étapes intersociétés nécessitent des règles complémentaires. Un tableau vide ne certifie pas la clôture de toute l’activité.</p></details>`;
    el().querySelector('#pilot-scope').value=scope;
    el().querySelector('#pilot-scope').onchange=e=>{scope=e.target.value;data=null;page=1;charger();};
    el().querySelector('#pilot-refresh').onclick=()=>charger();
    el().querySelector('#pilot-policy')?.addEventListener('click',parametres);
    el().querySelector('#pilot-pdf').onclick=()=>rapport(false);
    el().querySelector('#pilot-excel').onclick=()=>rapport(true);
    for(const [id,key] of [['q','q'],['module','module'],['user','user'],['niveau','niveau']]){
      const input=el().querySelector('#pilot-'+id);input.value=filters[key];input.addEventListener(id==='q'?'input':'change',()=>{filters[key]=input.value;page=1;resultats();});
    }
    el().querySelector('#pilot-reset').onclick=()=>{Object.keys(filters).forEach(k=>filters[k]='');shell();afficher();};
  }
  async function ouvrir(){
    if(sid!==currentSocieteId){data=null;Object.keys(filters).forEach(k=>filters[k]='');scope=dfi()?'equipe':'moi';}
    sid=currentSocieteId;page=1;shell();if(data)afficher();await charger();
  }
  async function charger(){
    if(busy||activeView!=='pilotage'||!token)return;
    busy=true;const wanted=currentSocieteId,portee=scope,version=navigationVersion,auth=token;
    try{
      const result=await api(`/pilotage/taches?societe_id=${wanted}&portee=${portee}`);
      if(wanted!==currentSocieteId||portee!==scope||activeView!=='pilotage'||version!==navigationVersion||auth!==token)return;
      data=result;sid=wanted;el().querySelector('#pilot-error').textContent='';afficher();
    }catch(e){if(wanted===currentSocieteId&&activeView==='pilotage'){el().querySelector('#pilot-error').textContent='Actualisation impossible : '+e.message;el().querySelector('#pilot-live').textContent='Données non actualisées';}}
    finally{busy=false;}
  }
  function options(id,rows,current,first){const input=el().querySelector(id);input.innerHTML=`<option value="">${first}</option>`+rows.map(([v,l])=>`<option value="${esc(v)}">${esc(l)}</option>`).join('');input.value=current;if(input.value!==current){input.value='';return '';}return current;}
  function afficher(){
    if(!data)return;
    const s=data.compteurs;
    el().querySelector('#pilot-live').textContent='Mis à jour à '+new Date(data.actualise_a).toLocaleTimeString('fr-FR');
    el().querySelector('#pilot-kpis').innerHTML=[['',s.total,'Actions en attente',`${s.dossiers} dossiers distincts`],['escalade',s.escalade,'Remontées DFI','Délai ou échéance dépassé'],['relance',s.relance,'Relances internes','À traiter en priorité'],['a_attribuer',s.a_attribuer,'À clarifier','Affectation ou circuit à vérifier']].map(([key,n,label,sub])=>`<button class="pilot-kpi ${key}" data-level="${key}"><strong>${n}</strong><span>${label}</span><small>${sub}</small></button>`).join('');
    el().querySelectorAll('[data-level]').forEach(b=>b.onclick=()=>{filters.niveau=b.dataset.level;el().querySelector('#pilot-niveau').value=filters.niveau;page=1;resultats();});
    filters.module=options('#pilot-module',[...new Set(data.taches.map(r=>r.module))].sort().map(x=>[x,x]),filters.module,'Tous les modules');
    filters.user=options('#pilot-user',data.utilisateurs.map(u=>[u.id,u.nom]).sort((a,b)=>a[1].localeCompare(b[1])),filters.user,'Tous les utilisateurs');
    resultats();
  }
  function resultats(){
    if(!data)return;
    const rows=filtrer(data.taches,filters),pages=Math.max(1,Math.ceil(rows.length/50));page=Math.min(page,pages);
    const summaries=data.utilisateurs.map(u=>{const ts=rows.filter(r=>r.responsables.some(x=>x.id===u.id));return {...u,total:ts.length,alertes:ts.filter(r=>['escalade','relance'].includes(r.niveau)).length};}).filter(u=>u.total).sort((a,b)=>b.alertes-a.alertes||b.total-a.total);
    el().querySelector('#pilot-result').innerHTML=`${data.portee==='equipe'?`<details class="pilot-summary"><summary>Répartition par utilisateur habilité · ${summaries.length} personne${summaries.length>1?'s':''}</summary><p class="muted">Files individuelles pouvant se recouper : ne pas additionner ces nombres comme des dossiers uniques.</p><div class="pilot-people">${summaries.map(u=>`<button class="btn" data-person="${u.id}"><b>${esc(u.nom)}</b><span>${u.total} actions · ${u.alertes} alertes</span></button>`).join('')||'<p>Aucune affectation active dans ce filtre.</p>'}</div></details>`:''}
      <div class="pilot-count"><b>${rows.length} action${rows.length>1?'s':''} dans cette sélection</b><span>Page ${page} / ${pages}</span></div>
      <div class="pilot-table"><table><thead><tr><th>Priorité / ancienneté</th><th>Action attendue</th><th>Qui peut intervenir ?</th><th>Ce qui attend ensuite</th><th>Détail</th></tr></thead><tbody>${rows.slice((page-1)*50,page*50).map(r=>`<tr><td><span class="pilot-status ${r.niveau}">${niveaux[r.niveau]}</span><div class="muted">${age(r.age_heures)}</div>${r.echeance_depassee?'<small>Échéance métier dépassée</small>':''}</td><td><b>${esc(r.action)}</b><div>${esc(r.reference)} · ${esc(r.module)}</div></td><td>${r.responsables.length?esc(r.responsables.map(u=>u.nom).slice(0,3).join(', '))+(r.responsables.length>3?` +${r.responsables.length-3}`:''):'Affectation à vérifier'}<div class="muted">${r.affectation==='nominative'?'Responsabilité nominative':'Équipe habilitée · '+esc(r.roles.join(' / '))}</div></td><td>${esc(r.impact)}</td><td><button class="btn btn-sm" data-task="${esc(r.id)}">Examiner</button></td></tr>`).join('')||'<tr><td colspan="5"><div class="pilot-empty">Aucune tâche dans cette sélection.<br><small>Les autres activités et les opérations non saisies ne sont pas évaluées ici.</small></div></td></tr>'}</tbody></table></div>
      <div class="pilot-pages"><button class="btn" data-prev ${page===1?'disabled':''}>Précédent</button><button class="btn" data-next ${page===pages?'disabled':''}>Suivant</button></div>`;
    el().querySelectorAll('[data-person]').forEach(b=>b.onclick=()=>{filters.user=b.dataset.person;el().querySelector('#pilot-user').value=filters.user;page=1;resultats();});
    el().querySelectorAll('[data-task]').forEach(b=>b.onclick=()=>examiner(data.taches.find(r=>r.id===b.dataset.task)));
    el().querySelector('[data-prev]').onclick=()=>{page--;resultats();};el().querySelector('[data-next]').onclick=()=>{page++;resultats();};
  }
  function examiner(r){
    if(!r)return;
    const root=modal({title:r.reference,body:`<div class="pilot-detail"><span class="pilot-status ${r.niveau}">${niveaux[r.niveau]}</span><h3>${esc(r.action)}</h3><p>${esc(r.detail)}</p>${r.blocage?`<p class="banner">${esc(r.blocage)}</p>`:''}<dl><dt>Qui peut intervenir ?</dt><dd>${esc(r.responsables.map(u=>u.nom).join(', ')||'Affectation à vérifier')}</dd><dt>Type de responsabilité</dt><dd>${r.affectation==='nominative'?'Personne liée au dossier':'Équipe habilitée ; aucune personne désignée exclusivement'}</dd><dt>Ancienneté calculée depuis</dt><dd>${date(r.debut)} · ${esc(r.base_date)}</dd><dt>Relance interne à partir du</dt><dd>${r.relance_at?date(r.relance_at):'Délai non configuré ou date indisponible'}</dd><dt>Remontée au DFI à partir du</dt><dd>${r.escalade_at?date(r.escalade_at):'Délai non configuré ou date indisponible'}</dd><dt>Échéance métier enregistrée</dt><dd>${date(r.echeance)}</dd><dt>Étape dépendante</dt><dd>${esc(r.impact)}</dd></dl></div>`,footer:'<button class="btn" id="pilot-close">Fermer</button><button class="btn btn-primary" id="pilot-open">Ouvrir le module concerné</button>'});
    const overlay=document.querySelector('#modal-root').lastElementChild;
    overlay.querySelector('#pilot-close').onclick=closeModal;
    overlay.querySelector('#pilot-open').onclick=async()=>{closeModal();await go(r.vue);if(['req_validation','req_precision','ordre_emission'].includes(r.type))await detailsRequisition(r.document_id);};
  }
  function rapport(excel){
    if(!data||sid!==currentSocieteId){toast('Actualisez le suivi avant de générer le rapport.','ko');return;}
    const rows=filtrer(data.taches,filters),soc=societes.find(s=>s.id===sid);
    const cols=['Priorité','Module','Dossier','Action attendue','Utilisateurs habilités','Affectation / rôles','Depuis','Base de la date','Ancienneté (h)','Échéance métier','Relance interne','Remontée DFI','Étape dépendante','Observation'];
    const values=rows.map(r=>[niveaux[r.niveau],r.module,r.reference,r.action,r.responsables.map(u=>u.nom).join(', '),r.affectation==='nominative'?'Nominative':r.roles.join(' / '),date(r.debut),r.base_date,r.age_heures??'',r.echeance?date(r.echeance):'',r.relance_at?date(r.relance_at):'',r.escalade_at?date(r.escalade_at):'',r.impact,[r.blocage,r.detail].filter(Boolean).join(' · ')]);
    const title='Suivi des tâches · '+(soc?.nom||'Société');
    const contexte=`Situation au ${date(data.actualise_a)} · ${data.portee==='equipe'?'Supervision DFI':'Mes tâches'} · ${rows.length} actions. Filtres : ${filters.module||'tous modules'} ; ${niveaux[filters.niveau]||'toutes priorités'} ; ${data.utilisateurs.find(u=>u.id===filters.user)?.nom||'tous utilisateurs'} ; recherche : ${filters.q||'aucune'}.`;
    if(excel)return Editions.excel(title,cols,values,contexte+' Les files par utilisateur peuvent se recouper.');
    return Editions.tableau(title,contexte,['Priorité','Dossier / module','Action attendue','Intervenants habilités','Depuis / ancienneté','Suite attendue'],rows.map(r=>[niveaux[r.niveau],r.reference+' · '+r.module,r.action+(r.blocage?' — '+r.blocage:''),r.responsables.map(u=>u.nom).join(', ')||'Affectation à vérifier',date(r.debut)+' · '+age(r.age_heures),r.impact]),'Les files par utilisateur peuvent se recouper. Ce suivi des tâches enregistrées ne constitue pas une évaluation individuelle. Dates et règles détaillées disponibles dans Excel et dans le dossier.');
  }
  async function parametres(){
    const company=currentSocieteId,auth=token;
    try{
      const p=await api(`/pilotage/delais?societe_id=${company}`);if(company!==currentSocieteId||auth!==token)return;
      modal({title:'Délais de suivi · société active',wide:true,body:`<p>Activez les types de tâches à suivre. Les délais sont comptés depuis la date indiquée dans le dossier, en <b>heures calendaires</b>. Ils s’appliquent aussi aux dossiers déjà ouverts. Aucun paiement ni blocage n’est déclenché.</p><p class="banner">Les relances sont visibles dans l’ERP. La remontée au DFI apparaît dans sa supervision. Les échéances métier déjà enregistrées restent prioritaires.</p><div class="pilot-policy">${Object.entries(p.types).map(([k,v])=>`<div data-rule="${k}"><label><input type="checkbox" ${p.regles[k]?'checked':''}> ${esc(v.action)}<small>${esc(v.module)}</small></label><label>Relance (h)<input class="form-input" data-remind type="number" min="1" max="8759" step="1" value="${p.regles[k]?.relance_h||24}"></label><label>Remontée DFI (h)<input class="form-input" data-escalate type="number" min="2" max="8760" step="1" value="${p.regles[k]?.escalade_h||48}"></label></div>`).join('')}</div><p id="pilot-save-error" class="err" role="alert"></p>`,footer:'<button class="btn" id="pilot-cancel">Annuler</button><button class="btn btn-primary" id="pilot-save">Enregistrer les délais</button>'});
      const root=document.querySelector('#modal-root').lastElementChild;root.querySelector('#pilot-cancel').onclick=closeModal;
      root.querySelector('#pilot-save').onclick=async()=>{
        if(company!==currentSocieteId)return;
        const values={};for(const r of root.querySelectorAll('[data-rule]'))values[r.dataset.rule]=r.querySelector('input[type=checkbox]').checked?{relance_h:Number(r.querySelector('[data-remind]').value),escalade_h:Number(r.querySelector('[data-escalate]').value)}:null;
        const button=root.querySelector('#pilot-save');button.disabled=true;
        try{await api(`/pilotage/delais?societe_id=${company}`,{method:'PUT',body:{version:p.version,regles:values}});closeModal();toast('Délais enregistrés pour cette société.','ok');await charger();await badge();}
        catch(e){root.querySelector('#pilot-save-error').textContent=e.message;button.disabled=false;}
      };
    }catch(e){toast(e.message,'ko');}
  }
  async function badge(){
    lastBadge=Date.now();const company=currentSocieteId,auth=token;if(!company||!token||!me)return;
    try{const p=await api(`/pilotage/taches?societe_id=${company}&portee=${dfi()?'equipe':'moi'}&resume=1`);if(company!==currentSocieteId||auth!==token)return;
      const n=p.compteurs.relance+p.compteurs.escalade+p.compteurs.a_attribuer,b=document.querySelector('#pilotage-alertes');b.textContent=`Suivi · ${n} alerte${n>1?'s':''}`;b.classList.toggle('pilot-alert',n>0);b.title='Société active · mis à jour à '+new Date(p.actualise_a).toLocaleTimeString('fr-FR');
    }catch{const b=document.querySelector('#pilotage-alertes');if(b){b.textContent='Suivi · à actualiser';b.classList.remove('pilot-alert');}}
  }
  return {init,badge,filtrer,reset};
})();
