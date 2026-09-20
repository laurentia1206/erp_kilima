/* Ressources humaines — aucun calcul de paie implicite depuis un pointage. */
const RH = (() => {
  let section='agents', mois='', donnees=[], org={}, pointages=[], demandes=[];
  const jours=['Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche'];
  const dateLocale=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
  const duree=m=>`${Math.floor(m/60)} h ${String(m%60).padStart(2,'0')}`;
  const champ=(nom,label,type='text',val='',extra='')=>`<label class="form-group"><span class="form-label">${label}</span><input class="form-input" name="${nom}" type="${type}" value="${esc(val??'')}" ${extra}></label>`;
  const zone=(nom,label,val='')=>`<label class="form-group rh-wide"><span class="form-label">${label}</span><textarea class="form-input" name="${nom}" rows="3">${esc(val)}</textarea></label>`;
  const select=(nom,label,options,val='')=>`<label class="form-group"><span class="form-label">${label}</span><select class="form-select" name="${nom}">${options.map(([v,t])=>`<option value="${esc(v)}" ${String(v)===String(val)?'selected':''}>${esc(t)}</option>`).join('')}</select></label>`;
  const btn=(label,action,cls='')=>`<button class="btn ${cls}" data-rh="${action}">${label}</button>`;
  const table=(head,rows)=>`<div class="rh-table"><table><thead><tr>${head.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')||`<tr><td colspan="${head.length}" class="muted">Aucun enregistrement pour le moment.</td></tr>`}</tbody></table></div>`;
  const appel=(path,opts={},sid=currentSocieteId)=>api(`/rh/${path}${path.includes('?')?'&':'?'}societe_id=${sid}`,opts);
  function imprimer(titre,sousTitre,colonnes,lignes,pied=''){
    // Les vues RH échappent leurs libellés ; le rapport commun les échappe à nouveau.
    const texte=v=>{const t=document.createElement('textarea');t.innerHTML=String(v??'');return t.value;};
    const entete=texte(titre),sous=texte(sousTitre),cols=colonnes.map(texte),rows=lignes.map(r=>r.map(texte));
    return Editions.tableau(entete,sous,cols,rows,pied);
  }
  function init(){
    NAV.push({g:'Ressources humaines',roles:['RH','DRH','DFI','DG','ADMIN','RESP_EQUIPE','CAISSIER_CENTRAL','CAISSIER_VENDEUR','COMPTABLE'],items:[{v:'rh',l:'Personnel & pointages',i:'ti-users-group',roles:['RH','DRH','DFI','RESP_EQUIPE']}]});
    TITLES.rh=['Ressources humaines','Dossiers du personnel, organisation du travail et suivi quotidien'];RENDER.rh=render;
  }
  async function render(){
    const el=$('#view-rh');el.innerHTML='<p class="muted">Chargement des ressources humaines…</p>';
    try{
      mois ||= dateLocale().slice(0,7);
      [org,donnees]=await Promise.all([appel('organisation'),appel('agents')]);
      if(!org.dossiers && section!=='pointages')section='pointages';
      if(section==='pointages')pointages=await appel('pointages?mois='+mois);
      if(section==='demandes')demandes=await appel('demandes');
      const actifs=donnees.filter(a=>!a.date_sortie||a.date_sortie>=dateLocale());
      el.innerHTML=`<div class="rh-intro"><div><span class="rh-kicker">${esc(societes.find(s=>s.id===currentSocieteId)?.nom||'')}</span><h2>Chaque agent, un dossier suivi.</h2><p>${org.dossiers?'Organisez les équipes et consignez les faits utiles à la gestion du personnel.':'Pointage des agents des équipes dont vous êtes responsable.'}</p></div><div class="rh-total"><strong>${actifs.length}</strong><span>agent(s) en activité</span></div></div>
        <nav class="rh-tabs" aria-label="Rubriques RH">${(org.dossiers?[['agents','Dossiers agents'],['pointages','Pointages'],['organisation','Équipes & horaires'],['demandes','Congés & avances'],['reperes','Paie & cadre légal']]:[['pointages','Pointages']]).map(([k,t])=>`<button class="btn ${section===k?'btn-primary':''}" data-section="${k}" aria-current="${section===k?'page':'false'}">${t}</button>`).join('')}</nav><div id="rh-contenu"></div>`;
      el.querySelectorAll('[data-section]').forEach(b=>b.onclick=()=>{section=b.dataset.section;render();});
      ({agents:agentsVue,pointages:pointagesVue,organisation:organisationVue,demandes:demandesVue,reperes:reperesVue})[section]();
    }catch(e){el.innerHTML=`<p class="err" role="alert">${esc(e.message)}</p>`;}
  }
  function agir(actions){$('#rh-contenu').querySelectorAll('[data-rh]').forEach(b=>b.onclick=()=>Promise.resolve(actions[b.dataset.rh]?.()).catch(e=>toast(e.message,'ko')));}
  function formulaire(titre,contenu,enregistrer,rafraichir=render){
    const sid=currentSocieteId;
    modal({wide:true,title:titre,body:`<form class="rh-form">${contenu}<p class="err rh-wide" role="alert"></p></form>`,footer:'<button class="btn" onclick="closeModal()">Annuler</button><button class="btn btn-primary" data-save-rh>Enregistrer</button>'});
    const root=$('#modal-root').lastElementChild,form=root.querySelector('form'),b=root.querySelector('[data-save-rh]');
    b.onclick=()=>form.requestSubmit();
    form.onsubmit=async e=>{e.preventDefault();if(b.disabled)return;b.disabled=true;
      try{if(currentSocieteId!==sid)throw new Error('La société a changé. Rouvrez le formulaire.');await enregistrer(Object.fromEntries(new FormData(form)),form,sid);closeModal();toast('Enregistrement effectué.','ok');await rafraichir();}
      catch(err){form.querySelector('.err').textContent=err.message;}finally{b.disabled=false;}};
    return root;
  }
  function agentsVue(){
    const el=$('#rh-contenu');
    el.innerHTML=`<div class="rh-toolbar"><input class="form-input" id="rh-recherche" placeholder="Rechercher un nom, matricule ou poste" aria-label="Rechercher un agent">${btn('+ Ajouter un agent','ajouter','btn-primary')}${btn('Imprimer le registre','print')}</div><p class="muted">Les matricules et les dossiers sont propres à la société sélectionnée. Un compte de connexion n’est pas obligatoire.</p><div id="rh-liste"></div>`;
    const liste=()=>{$('#rh-liste').innerHTML=table(['Agent','Poste / équipe','Engagement','Situation',''],donnees.filter(a=>`${a.nom} ${a.matricule} ${a.poste} ${a.equipe}`.toLocaleLowerCase().includes($('#rh-recherche').value.toLocaleLowerCase())).map(a=>`<tr><td><b>${esc(a.nom)}</b><div class="muted">${esc(a.matricule)}</div></td><td>${esc(a.poste)}<div class="muted">${esc(a.equipe)}</div></td><td>${a.date_engagement}</td><td>${a.date_sortie?'Sortie : '+a.date_sortie:'En activité'}</td><td><button class="btn" data-agent="${a.id}">Ouvrir le dossier</button></td></tr>`));el.querySelectorAll('[data-agent]').forEach(b=>b.onclick=()=>ouvrirDossier(b.dataset.agent).catch(e=>toast(e.message,'ko')));};
    $('#rh-recherche').oninput=liste;liste();
    agir({ajouter:()=>ficheAgent(),print:()=>imprimer('Registre du personnel','Société : '+esc(societes.find(s=>s.id===currentSocieteId)?.nom),['Matricule','Nom','Poste','Équipe','Engagement','Sortie'],donnees.map(a=>[esc(a.matricule),esc(a.nom),esc(a.poste),esc(a.equipe),a.date_engagement,a.date_sortie||'—']),'État interne du registre du personnel')});
  }
  function ficheAgent(a={}){
    const opt=(rows,cle='nom')=>[['','Non affecté'],...rows.map(x=>[x.id,x[cle]])];
    formulaire(a.id?'Modifier la fiche agent':'Créer un dossier agent',
      champ('matricule','Matricule','text',a.matricule,'required maxlength="40"')+champ('nom','Nom complet','text',a.nom,'required maxlength="180"')+
      champ('poste','Poste','text',a.poste)+select('equipe_id','Équipe / département',opt(org.equipes),a.equipe_id)+
      select('horaire_id','Horaire habituel',opt(org.horaires),a.horaire_id)+select('utilisateur_id','Compte de connexion (facultatif)',[['','Aucun compte'],...org.utilisateurs.map(u=>[u.id,u.nom+' '+(u.prenom||'')])],a.utilisateur_id)+
      select('tiers_id','Compte agent dans les finances',opt(org.tiers_agents||[]),a.tiers_id)+
      champ('date_engagement','Date d’engagement','date',a.date_engagement||dateLocale(),'required')+champ('date_sortie','Date de sortie (si connue)','date',a.date_sortie)+
      champ('telephone','Téléphone','tel',a.telephone)+champ('email','Adresse électronique','email',a.email)+champ('numero_cnss','Numéro CNSS','text',a.numero_cnss)+champ('nif','NIF de l’agent','text',a.nif)+zone('adresse','Adresse',a.adresse)+
      zone('motif_homonyme','En cas d’homonymie uniquement : précisez comment les personnes ont été distinguées'),
      p=>appel('agents',{method:a.id?'PUT':'POST',body:{...p,id:a.id,revision:a.revision}}));
  }
  async function ouvrirDossier(id){
    const sid=currentSocieteId,d=await appel(`agents/${id}/dossier`),a=d.agent;
    const contrats=table(['Référence','Période','Rémunération contractuelle'],d.contrats.map(c=>`<tr><td>${esc(c.reference)} · ${c.type_contrat}<div>${esc(c.categorie)}</div></td><td>${c.debut} → ${c.fin||'Indéterminée'}</td><td>${fmtNum(c.salaire)} ${c.devise} ${c.base_salaire}<div>${esc(c.convention)}</div>${c.remuneration?.parametres?`<details><summary>Composantes à l’engagement</summary><p>Brut : ${fmtNum(c.remuneration.parametres.brut_base)} · Logement : ${fmtNum(c.remuneration.parametres.logement)} · Transport : ${fmtNum(c.remuneration.parametres.transport)} · Primes : ${fmtNum(c.remuneration.parametres.primes)} ${c.devise}</p><p>Simulation du ${esc(c.remuneration.parametres.date_reference)} · ${esc(c.remuneration.resultat.version)}</p></details>`:""}</td></tr>`));
    const historique=d.evenements.map(e=>`<article class="rh-event"><span class="muted">${e.date} · ${esc(e.nature)}</span><h4>${esc(e.titre)}</h4><p style="white-space:pre-wrap">${esc(e.contenu)}</p></article>`).join('')||'<p class="muted">Aucun événement consigné.</p>';
    modal({wide:true,title:`${a.matricule} — ${a.nom}`,body:`<div class="rh-dossier"><p>${esc(a.poste)} · ${esc(a.equipe||'Équipe non affectée')} · ${esc(a.horaire||'Horaire non affecté')}</p><p>Engagement : ${a.date_engagement} · ${esc(a.telephone)} · ${esc(a.email)}</p><p>CNSS : ${esc(a.numero_cnss||'Non renseigné')} · NIF : ${esc(a.nif||'Non renseigné')}</p><p>${esc(a.adresse)}</p><h3>Contrats enregistrés</h3>${contrats}<h3>Historique du dossier</h3>${historique}<h3>Documents confidentiels</h3>${d.documents.map(f=>`<p><button class="btn" data-doc-rh="${f.id}">${esc(f.nom)}</button> <span class="muted">${esc(f.nature)}</span></p>`).join('')||'<p class="muted">Ajoutez les contrats signés et pièces utiles (PDF, PNG, JPEG).</p>'}</div>`,footer:`<button class="btn" data-edit-rh>Fiche</button><button class="btn" data-contrat-rh>+ Contrat</button><button class="btn" data-event-rh>+ Événement</button><button class="btn" data-upload-rh>+ Document</button><button class="btn" data-print-rh>Imprimer</button>`});
    const root=$('#modal-root').lastElementChild;
    root.querySelector('[data-edit-rh]').onclick=()=>{closeModal();ficheAgent(a);};
    root.querySelector('[data-contrat-rh]').onclick=()=>{closeModal();contrat(a);};
    root.querySelector('[data-event-rh]').onclick=()=>{closeModal();evenement(a);};
    root.querySelector('[data-print-rh]').onclick=()=>imprimer('Dossier agent — '+esc(a.nom),esc(a.matricule+' · '+a.poste+' · '+a.equipe),['Élément','Détail'],[
      ['Engagement',a.date_engagement],['CNSS',esc(a.numero_cnss)],['NIF',esc(a.nif)],
      ...d.contrats.map(c=>['Contrat '+esc(c.reference),`${c.type_contrat} · ${c.debut} → ${c.fin||'Indéterminée'} · ${fmtNum(c.salaire)} ${c.devise} ${c.base_salaire} · ${esc(c.convention)}`]),
      ...d.evenements.map(e=>[`${e.date} · ${esc(e.nature)} · ${esc(e.titre)}`,esc(e.contenu)])],'Confidentiel — destiné aux personnes habilitées');
    root.querySelector('[data-upload-rh]').onclick=()=>{closeModal();formulaire('Ajouter un document — '+a.nom,champ('fichier','Document (5 Mo maximum)','file','','required accept=".pdf,.png,.jpg,.jpeg"')+champ('nature','Nature du document','text','Contrat','required'),async(p,f)=>{
      const r=await fetch(API+`/rh/agents/${a.id}/documents?societe_id=${sid}`,{method:'POST',headers:{Authorization:'Bearer '+token},body:new FormData(f)});if(!r.ok)throw new Error(messageErreur(await r.json(),r.statusText));
    });};
    root.querySelectorAll('[data-doc-rh]').forEach(b=>b.onclick=async()=>{try{const r=await fetch(API+`/rh/documents/${b.dataset.docRh}?societe_id=${sid}`,{headers:{Authorization:'Bearer '+token}});if(!r.ok)throw new Error('Accès au document refusé.');const url=URL.createObjectURL(await r.blob()),l=document.createElement('a');l.href=url;l.download=d.documents.find(f=>f.id===b.dataset.docRh).nom;l.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){toast(e.message,'ko');}});
  }
  function contrat(a,sim=null,rafraichir=render){formulaire('Enregistrer un contrat — '+a.nom,
    '<p class="banner rh-wide">Enregistrez les conditions du contrat signé. Un salaire net reste identifié comme net ; aucune conversion en brut n’est présumée.</p>'+
    champ('reference','Référence','text','','required')+select('type_contrat','Type',[['CDI','CDI'],['CDD','CDD'],['stage','Stage'],['apprentissage','Apprentissage']])+
    champ('debut','Début','date',a.date_engagement,'required')+champ('fin','Fin prévue','date')+champ('salaire','Salaire mensuel convenu','number','','min="0" step="0.01" required')+
    select('devise','Devise',[['USD','USD'],['CDF','CDF']])+select('base_salaire','Base contractuelle',[['brut','Brut'],['net','Net']])+champ('categorie','Catégorie professionnelle')+zone('convention','Convention applicable et conditions particulières'),
    p=>appel(`agents/${a.id}/dossier`,{method:'POST',body:{...p,nature:'contrat',simulation_id:sim?.id}}),rafraichir);
    const root=$('#modal-root').lastElementChild;
    root.querySelector('[name=base_salaire]').value='net';
    if(sim){
      root.querySelector('[name=salaire]').value=sim.resultat.net;root.querySelector('[name=salaire]').readOnly=true;
      root.querySelector('[name=debut]').value=sim.parametres.date_reference;
      for(const [name,value] of [['devise',sim.parametres.devise],['base_salaire','net']]){const s=root.querySelector(`[name=${name}]`);s.value=value;s.disabled=true;const h=document.createElement('input');h.type='hidden';h.name=name;h.value=value;root.querySelector('form').append(h);}
      root.querySelector('.banner').textContent=`Proposition « ${sim.nom} » : brut ${fmtNum(sim.parametres.brut_base)}, logement ${fmtNum(sim.parametres.logement)}, transport ${fmtNum(sim.parametres.transport)}, primes ${fmtNum(sim.parametres.primes)} ${sim.parametres.devise}. Net repris : ${fmtNum(sim.resultat.net)}. Pour modifier les montants, préparez une nouvelle variante dans le simulateur.`;
    }
  }
  function evenement(a){formulaire('Consigner un événement — '+a.nom,select('nature','Nature',[['administratif','Administratif'],['engagement','Engagement'],['disciplinaire','Dossier disciplinaire'],['formation','Formation'],['evaluation','Évaluation']])+champ('date','Date','date',dateLocale(),'required')+champ('titre','Objet','text','','required')+zone('contenu','Faits, documents de référence et suite donnée'),p=>appel(`agents/${a.id}/dossier`,{method:'POST',body:p}));}
  function heuresForm(s={}){return champ('debut','Début du service','time',s.debut||'08:00')+champ('fin','Fin du service','time',s.fin||'17:00')+select('lendemain','Fin du service',[['non','Le même jour'],['oui','Le lendemain']],s.lendemain?'oui':'non')+champ('pause_debut','Pause non travaillée : début','time',s.pause_debut)+champ('pause_fin','Pause non travaillée : fin','time',s.pause_fin);}
  function pointagesVue(){
    const el=$('#rh-contenu'),valides=pointages.filter(p=>p.statut==='valide');
    el.innerHTML=`<div class="rh-toolbar"><label>Mois <input id="rh-mois" class="form-input" type="month" value="${mois}"></label>${btn('+ Saisir un pointage','ajouter','btn-primary')}${btn('Imprimer le mois','print')}</div><div class="banner">${valides.length} pointage(s) validé(s) · ${duree(valides.reduce((n,p)=>n+p.minutes,0))} travaillées. Les jours sans saisie ne sont pas des absences. Les heures de nuit sont isolées ; elles ne déclenchent pas encore de paie.</div>${table(['Jour','Agent','Service','Temps / nuit','État',''],pointages.map(p=>`<tr><td>${p.jour}</td><td>${esc(p.nom)}<div class="muted">${esc(p.matricule)}</div></td><td>${esc(p.nature)}${p.debut?`<div>${p.debut.slice(11,16)} → ${p.fin.slice(11,16)}${p.fin.slice(0,10)!==p.jour?' (+1 j)':''}</div>`:''}<div class="muted">${esc(p.note)}</div></td><td>${duree(p.minutes)}<div class="muted">Nuit : ${duree(p.minutes_nuit)}</div>${p.minutes>480?'<span class="err">Plus de 8 h : à examiner</span>':''}</td><td>${p.statut==='valide'?'Validé':'À contrôler'}</td><td>${p.statut==='brouillon'?`<button class="btn" data-pointage="${p.id}">Modifier</button>`:''}${org.dossiers?`<button class="btn" data-decision="${p.id}">${p.statut==='valide'?'Rouvrir':'Valider'}</button>`:''}</td></tr>`))}`;
    $('#rh-mois').onchange=e=>{if(e.target.value){mois=e.target.value;render();}};
    agir({ajouter:()=>pointageForm(),print:()=>imprimer('Pointages — '+mois,'Les temps non validés ne sont pas approuvés pour la paie.',['Jour','Agent','Nature','Minutes travaillées','Minutes nuit','État'],pointages.map(p=>[p.jour,esc(p.nom),p.nature,p.minutes,p.minutes_nuit,p.statut]),'Temps locaux — Africa/Lubumbashi · Nuit : 19 h à 5 h')});
    el.querySelectorAll('[data-pointage]').forEach(b=>b.onclick=()=>pointageForm(pointages.find(p=>p.id===b.dataset.pointage)));
    el.querySelectorAll('[data-decision]').forEach(b=>b.onclick=()=>{const p=pointages.find(x=>x.id===b.dataset.decision),reouvrir=p.statut==='valide';formulaire(reouvrir?'Rouvrir le pointage':'Valider le pointage',`<p class="rh-wide">${esc(p.nom)} · ${p.jour} · ${duree(p.minutes)}</p>`+(reouvrir?zone('motif','Motif de correction (obligatoire)'):'<p class="rh-wide">La validation fige ce pointage. Elle ne déclenche aucune retenue ni paiement.</p>'),v=>appel(`pointages/${p.id}/decision`,{method:'POST',body:{...v,revision:p.revision,action:reouvrir?'rouvrir':'valider'}}));});
  }
  function pointageForm(p={}){
    const opts=donnees.map(a=>[a.id,a.matricule+' — '+a.nom]);
    if(!opts.length){toast('Créez ou affectez d’abord un agent à votre équipe.','ko');return;}
    const h={debut:p.debut?.slice(11,16),fin:p.fin?.slice(11,16),lendemain:p.fin&&p.fin.slice(0,10)!==p.jour,pause_debut:p.pause_debut?.slice(11,16),pause_fin:p.pause_fin?.slice(11,16)};
    const root=formulaire('Pointage journalier',select('agent_id','Agent',opts,p.agent_id)+champ('jour','Jour de début','date',p.jour||dateLocale(),`required max="${dateLocale()}"`)+select('nature','Situation',[['present','Présent'],['mission','Mission'],['absence','Absence à qualifier'],['repos','Repos'],['conge','Congé']],p.nature||'present')+`<div class="rh-form rh-wide" data-heures>${heuresForm(h)}</div>`+zone('note','Observation',p.note||''),v=>appel('pointages',{method:'POST',body:{...v,revision:p.revision,lendemain:v.lendemain==='oui'}}));
    const situ=root.querySelector('[name=nature]');situ.onchange=()=>{root.querySelector('[data-heures]').hidden=!['present','mission'].includes(situ.value);};situ.onchange();
    if(p.id){root.querySelector('[name=agent_id]').disabled=true;root.querySelector('[name=jour]').readOnly=true;const hidden=document.createElement('input');hidden.type='hidden';hidden.name='agent_id';hidden.value=p.agent_id;root.querySelector('form').append(hidden);}
  }
  function organisationVue(){
    $('#rh-contenu').innerHTML=`<div class="rh-toolbar">${btn('+ Équipe / département','equipe','btn-primary')}${btn('+ Horaire','horaire')}${btn('Imprimer','print')}</div><h3>Équipes et responsables de pointage</h3>${table(['Équipe','Responsable'],org.equipes.map(e=>`<tr><td>${esc(e.nom)}</td><td>${esc(org.utilisateurs.find(u=>u.id===e.responsable_id)?.nom||'Non affecté')}</td></tr>`))}<p class="muted">Le responsable doit disposer du rôle « Responsable d’équipe » dans cette société pour accéder au pointage. Aucun accès aux contrats ni aux rémunérations ne lui est donné par cette affectation.</p><h3>Horaires disponibles</h3>${table(['Horaire','Programme hebdomadaire','Repères'],org.horaires.map(h=>`<tr><td><b>${esc(h.nom)}</b><p>${esc(h.note)}</p></td><td>${h.semaine.map(s=>`${jours[s.jour]} : ${s.debut} → ${s.fin}${s.lendemain?' (+1 j)':''} · ${duree(s.minutes)}`).join('<br>')}</td><td>${duree(h.semaine.reduce((n,s)=>n+s.minutes,0))} / semaine${h.semaine.some(s=>s.minutes>480)||h.semaine.reduce((n,s)=>n+s.minutes,0)>2700?'<p class="err">Dépassement de la durée légale ordinaire : accord et heures supplémentaires à examiner.</p>':''}</td></tr>`))}`;
    agir({equipe:()=>formulaire('Créer une équipe',champ('nom','Nom de l’équipe','text','','required')+select('responsable_id','Responsable du pointage',[['','À affecter'],...org.utilisateurs.map(u=>[u.id,u.nom+' '+(u.prenom||'')])]),p=>appel('organisation',{method:'POST',body:{...p,nature:'equipe'}})),
      horaire:()=>formulaire('Créer un horaire habituel',champ('nom','Nom de l’horaire','text','','required')+`<fieldset class="rh-wide"><legend>Jours concernés par ce service</legend>${jours.map((j,i)=>`<label class="rh-day"><input type="checkbox" name="j${i}" ${i<5?'checked':''}> ${j}</label>`).join('')}</fieldset>`+heuresForm()+zone('note','Règle interne / rotation et observations'),(p,f)=>appel('organisation',{method:'POST',body:{nature:'horaire',nom:p.nom,note:p.note,semaine:jours.flatMap((_,i)=>p['j'+i]?[{jour:i,debut:p.debut,fin:p.fin,lendemain:p.lendemain==='oui',pause_debut:p.pause_debut,pause_fin:p.pause_fin}]:[])}})),
      print:()=>imprimer('Horaires de travail','Horaires habituels de la société sélectionnée',['Horaire','Jour','Début','Fin','Durée'],org.horaires.flatMap(h=>h.semaine.map(s=>[esc(h.nom),jours[s.jour],s.debut,s.fin+(s.lendemain?' (+1 j)':''),duree(s.minutes)])),'Les rotations particulières sont consignées dans le pointage journalier.')});
  }
  function demandesVue(){
    $('#rh-contenu').innerHTML=`<div class="rh-toolbar">${btn('+ Demande de congé','conge','btn-primary')}${btn('+ Demande d’avance sur salaire','avance')}${btn('Imprimer le registre','print')}</div><p class="banner">Registre des demandes reçues. Les avances sont instruites dans « Avances & prêts ». Les remboursements des avances et prêts versés se traitent dans « Paie mensuelle ». Les droits à congés automatiques restent à réaliser. Une demande reçue n’est ni un congé autorisé ni un paiement.</p>${table(['Agent','Demande','Période / montant','Motif','État'],demandes.map(d=>`<tr><td>${esc(d.nom)}</td><td>${d.nature==='conge'?'Congé · '+esc(d.type_conge):'Avance sur salaire'}</td><td>${d.nature==='conge'?`${d.debut} → ${d.fin}`:`${fmtNum(d.montant)} ${d.devise}`}</td><td>${esc(d.motif)}</td><td>${esc(({soumis:'Reçue — à traiter',instruit:'Accord en cours',verse:'Versée',rejete:'Rejetée'})[d.statut]||d.statut)}</td></tr>`))}`;
    const creer=nature=>formulaire(nature==='conge'?'Enregistrer une demande de congé':'Enregistrer une demande d’avance sur salaire',select('agent_id','Agent',donnees.map(a=>[a.id,a.matricule+' — '+a.nom]))+(nature==='conge'?select('type_conge','Type de congé',[['annuel','Annuel'],['maladie','Maladie'],['maternite','Maternité'],['circonstance','Circonstance'],['sans_solde','Sans solde']])+champ('debut','Du','date','','required')+champ('fin','Au inclus','date','','required'):champ('montant','Montant demandé','number','','required min="0.01" step="0.01"')+select('devise','Devise',[['USD','USD'],['CDF','CDF']]))+zone('motif','Motif de la demande'),p=>appel('demandes',{method:'POST',body:{...p,nature}}));
    agir({conge:()=>creer('conge'),avance:()=>creer('avance_salaire'),print:()=>imprimer('Registre des demandes RH','Demandes reçues — validation non effectuée',['Agent','Nature','Période / montant','Motif'],demandes.map(d=>[esc(d.nom),esc(d.nature),d.nature==='conge'?`${d.debut} → ${d.fin}`:`${fmtNum(d.montant)} ${d.devise}`,esc(d.motif)]),'Aucune autorisation de congé ni preuve de versement.')});
  }
  function reperesVue(){
    $('#rh-contenu').innerHTML=`<div class="card"><div class="card-body"><h3>Paie et déclarations : paramétrage préalable</h3><p>Les contrats distinguent déjà salaire brut ou net et devise USD ou CDF. Le simulateur d’engagement calcule le net et conserve les composantes à reprendre au contrat. Les décomptes finals disposent d’une préparation des droits bruts. Le menu « Paie mensuelle » permet maintenant préparation, contrôle RH, validation DFI, règlement et clôture. Il prépare aussi les bases sociales et fiscales à rapprocher avant dépôt. Le net du décompte final et les régularisations restent à réaliser.</p><ul><li>Horaires, primes et KPI : règles propres à chaque société.</li><li>Pointages : contrôle humain avant utilisation en paie.</li><li>Avances sur salaire : à distinguer des avances à justifier de la caisse.</li><li>Déclarations : rémunérations réelles et seules exclusions légalement justifiées.</li></ul><h3>Textes de référence consultés</h3><p><a href="https://dgrad.gouv.cd/wp-content/uploads/2022/01/Loi-16-010-du-15-juillet-2016-modifiant-et-completant-Loi-015-2002-Code-du-Travail.pdf" target="_blank" rel="noopener">Code du travail — modification de 2016</a> : durée ordinaire de 8 h/jour et 45 h/semaine ; repos hebdomadaire et majorations à contrôler.</p><p><a href="https://dgi.gouv.cd/impot-sur-le-revenu-des-personnes-physiques-irpp/" target="_blank" rel="noopener">DGI — IRPP</a> : barème progressif ; les règles doivent correspondre à la période de rémunération.</p><p><a href="https://cnss.cd/?page_id=1388" target="_blank" rel="noopener">CNSS — taux de cotisations</a> · <a href="https://www.app.onem.cd/employeurs/contribution-patronale" target="_blank" rel="noopener">ONEM — contribution patronale</a>. Les bases de calcul et les évolutions INPP doivent être vérifiées avant activation.</p><p class="muted">Recherche au 15 septembre 2026. Ces repères ne constituent pas un bulletin de paie ni une déclaration prête à déposer.</p></div></div>`;
  }
  return {init,champ,zone,select,btn,table,appel,formulaire,dateLocale,contrat,imprimer};
})();
