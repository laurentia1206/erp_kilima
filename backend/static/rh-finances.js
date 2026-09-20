const RHFinances=(()=>{
  const H=RH,prives=['RH','DRH','DFI'],decisionnaires=['DFI','DRH','DG','ADMIN'];
  const lib={avance_salaire:'Avance sur salaire',pret_personnel:'Prêt au personnel',recouvrement:'Avance à justifier — recouvrement',attente_dfi:'Validation DFI',attente_drh:'Validation DRH',attente_direction:'Validation DG / Administrateur',approuve:'Approuvé',rejete:'Rejeté',verse:'Versé'};
  const money=(n,d)=>`${fmtNum(n)} ${esc(d)}`;
  const roles=()=>societes.find(s=>s.id===currentSocieteId)?.roles||[];
  function init(){
    NAV.find(g=>g.g==='Ressources humaines').items.push({v:'rh-finances',l:'Avances & prêts',i:'ti-file-check',roles:[...prives,'DG','ADMIN']},{v:'rh-paiements',l:'Paiements RH',i:'ti-cash',roles:['DFI','CAISSIER_CENTRAL','CAISSIER_VENDEUR']});
    TITLES['rh-finances']=['Avances & prêts','Accord écrit, échéancier et validations successives'];TITLES['rh-paiements']=['Paiements RH','Versement des avances et prêts approuvés'];
    RENDER['rh-finances']=render;RENDER['rh-paiements']=paiements;
  }
  async function render(){
    const el=$('#view-rh-finances');el.innerHTML='<p class="muted">Chargement…</p>';
    try{const [pol,rows]=await Promise.all([H.appel('politique'),H.appel('dettes')]),preparer=roles().some(r=>prives.includes(r));
      el.innerHTML=`<div class="rh-intro"><div><span class="rh-kicker">Accords avec les agents</span><h2>Un dossier avant toute retenue.</h2><p>Avance courante : validation DFI. Prêt et recouvrement : DFI, puis DRH, puis DG ou Administrateur.</p></div></div>
        <div class="banner">Plafond des avances du mois : <b>${fmtNum(pol.plafond_avance_pct)} % du net contractuel</b>. Au-delà : prêt au personnel avec échéancier.<br>Avances à justifier : dossier possible après 30 jours, avec accord écrit. Leur validation n’est pas une justification de dépense et ne déclenche pas de retenue automatique.</div>
        <div class="rh-toolbar">${preparer?'<button class="btn btn-primary" id="rh-fin-new">+ Préparer un accord</button>':''}${roles().some(r=>['DFI','DRH'].includes(r))?'<button class="btn" id="rh-fin-pol">Plafond de la société</button>':''}</div>
        ${H.table(['Agent','Nature','Montant','État',''],rows.map(d=>`<tr><td>${esc(d.nom)}<div class="muted">${esc(d.matricule)}</div></td><td>${lib[d.nature]}${d.source_numero?'<div>'+esc(d.source_numero)+'</div>':''}</td><td>${money(d.montant,d.devise)}</td><td>${lib[d.statut]||esc(d.statut)}</td><td><button class="btn" data-dette="${d.id}">Ouvrir</button></td></tr>`))}
        <p class="muted">Les remboursements des avances et prêts sont repris dans la paie mensuelle selon les accords. Le solde diminue à la validation DFI de la paie. Les recouvrements d’avances à justifier attendent la confirmation du circuit de rapprochement.</p>`;
      el.querySelectorAll('[data-dette]').forEach(b=>b.onclick=()=>ouvrir(rows.find(d=>d.id===b.dataset.dette)));
      if($('#rh-fin-pol'))$('#rh-fin-pol').onclick=()=>H.formulaire('Plafond des avances sur salaire',H.champ('plafond_avance_pct','Pourcentage du net contractuel','number',pol.plafond_avance_pct,'required min="0" max="100" step="0.01"')+'<p class="rh-wide">Ce plafond détermine le circuit d’octroi. Les limites légales de retenue sur salaire sont distinctes.</p>',p=>H.appel('politique',{method:'POST',body:{...p,revision:pol.revision}}),render);
      if($('#rh-fin-new'))$('#rh-fin-new').onclick=async()=>{try{const agents=await H.appel('agents');if(!agents.length)throw new Error('Créez d’abord le dossier agent et son contrat net.');
        H.formulaire('Choisir l’agent',H.select('agent_id','Agent',agents.map(a=>[a.id,a.matricule+' — '+a.nom])),()=>{},()=>{});
        const root=$('#modal-root').lastElementChild;root.querySelector('form').onsubmit=async e=>{e.preventDefault();try{await preparerAccord(root.querySelector('[name=agent_id]').value);}catch(err){root.querySelector('.err').textContent=err.message;}};
      }catch(e){toast(e.message,'ko');}};
    }catch(e){el.innerHTML=`<p class="err">${esc(e.message)}</p>`;}
  }
  async function preparerAccord(id){
    const [d,demandes,sources]=await Promise.all([H.appel(`agents/${id}/dossier`),H.appel('demandes'),H.appel('avances-a-justifier?agent_id='+id)]);
    if(!d.documents.length)throw new Error('Ajoutez d’abord l’accord écrit signé dans les documents du dossier agent.');
    const req=demandes.filter(x=>x.agent_id===id&&x.nature==='avance_salaire'&&x.statut==='soumis'),eligibles=sources.filter(s=>s.eligible);
    const options=[...req.map(x=>['demande:'+x.id,'Demande — '+money(x.montant,x.devise)]),...eligibles.map(x=>['avance:'+x.id,x.numero+' — '+money(x.montant,x.devise)])];
    if(!options.length)throw new Error('Aucune demande d’avance disponible ni avance à justifier admissible après 30 jours.');
    closeModal();const root=H.formulaire('Accord et échéancier — '+d.agent.nom,
      H.select('source','Demande / avance à recouvrer',options)+H.select('accord_id','Accord écrit signé',d.documents.map(f=>[f.id,f.nom]))+
      '<p class="rh-wide">Reportez l’échéancier convenu et signé avec l’agent. Le total doit couvrir le montant de l’accord. Chaque mois ne doit apparaître qu’une fois.</p><div id="rh-mensualites" class="rh-wide"></div><button class="btn rh-wide" type="button" data-add-mois>+ Une mensualité</button>'+
      H.zone('motif','Objet de l’accord et modalités convenues'),
      (p,f)=>{const [type,source]=p.source.split(':');return H.appel('dettes',{method:'POST',body:{agent_id:id,accord_id:p.accord_id,motif:p.motif,[type==='demande'?'demande_id':'avance_source_id']:source,echeancier:[...f.querySelectorAll('[data-mensualite]')].map(r=>({mois:r.querySelector('[type=month]').value,montant:r.querySelector('[type=number]').value}))}});},render);
    const lignes=root.querySelector('#rh-mensualites');
    const ajout=(montant='')=>{const row=document.createElement('div');row.className='rh-echeance';row.dataset.mensualite='1';row.innerHTML=H.champ('','Mois','month',H.dateLocale().slice(0,7),'required')+H.champ('','Montant','number',montant,'required min="0.01" step="0.01"')+'<button class="btn" type="button" aria-label="Retirer cette mensualité">×</button>';row.querySelector('button').onclick=()=>row.remove();lignes.append(row);};
    root.querySelector('[data-add-mois]').onclick=()=>ajout();ajout(req[0]?.montant||eligibles[0]?.montant);
  }
  function ouvrir(d){
    const eligible={attente_dfi:['DFI'],attente_drh:['DRH'],attente_direction:['DG','ADMIN']}[d.statut]||[],peut=roles().some(r=>eligible.includes(r));
    modal({wide:true,title:`${lib[d.nature]} — ${d.nom}`,body:`<p><b>${money(d.montant,d.devise)}</b> · ${lib[d.statut]}</p><p>${esc(d.motif)}</p><p>Référence du net : ${money(d.salaire_reference,d.devise)} · Plafond à la préparation : ${d.plafond_pct} %</p>${H.table(['Mois','Mensualité'],d.echeancier.map(l=>`<tr><td>${esc(l.mois)}</td><td>${money(l.montant,d.devise)}</td></tr>`))}<p><b>Remboursé sur paie : ${money(d.rembourse,d.devise)}</b> · Solde de l’accord : ${money(d.solde,d.devise)}</p>${H.table(['Mois de paie','Retenue validée'],d.remboursements.map(x=>`<tr><td>${esc(x.mois)}</td><td>${money(x.montant,d.devise)}</td></tr>`))}<h3>Historique des décisions</h3>${d.decisions.map(v=>`<p>${esc(v.date.slice(0,10))} · ${esc(v.nom)} · ${lib[v.etape]} · ${esc(v.action)}<br>${esc(v.commentaire)}</p>`).join('')||'<p class="muted">Aucune décision.</p>'}`,footer:`<button class="btn" data-accord>Accord signé</button><button class="btn" data-print>Imprimer</button>${peut?'<button class="btn" data-rejet>Rejeter</button><button class="btn btn-primary" data-valider>Valider à mon niveau</button>':''}`});
    const root=$('#modal-root').lastElementChild,sid=currentSocieteId;
    root.querySelector('[data-accord]').onclick=async()=>{try{const r=await fetch(API+`/rh/dettes/${d.id}/accord?societe_id=${sid}`,{headers:{Authorization:'Bearer '+token}});if(!r.ok)throw new Error('Accès au document refusé.');const u=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=u;a.download=d.accord_nom;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}catch(e){toast(e.message,'ko');}};
    root.querySelector('[data-print]').onclick=()=>H.imprimer('Dossier RH — '+esc(d.nom),`${lib[d.nature]} · ${money(d.montant,d.devise)} · ${lib[d.statut]}`,['Élément','Détail'],[['Motif',esc(d.motif)],['Accord',esc(d.accord_nom)],...d.echeancier.map(l=>[l.mois,money(l.montant,d.devise)]),...d.decisions.map(v=>[lib[v.etape],esc(v.nom+' · '+v.action+' · '+v.commentaire)])],'Échéancier convenu — ce document ne prouve pas un versement ni un remboursement.');
    const decider=action=>{closeModal();H.formulaire(action==='valider'?'Valider cet accord':'Rejeter cet accord',`<p class="rh-wide">${esc(d.nom)} · ${money(d.montant,d.devise)} · ${lib[d.statut]}</p>`+H.zone('commentaire','Motif et vérifications effectuées (obligatoire)'),p=>H.appel(`dettes/${d.id}/decision`,{method:'POST',body:{...p,action,revision:d.revision}}),render);};
    if(peut){root.querySelector('[data-valider]').onclick=()=>decider('valider');root.querySelector('[data-rejet]').onclick=()=>decider('rejeter');}
  }
  async function paiements(){
    const el=$('#view-rh-paiements');el.innerHTML='<p class="muted">Chargement…</p>';
    try{const rows=await H.appel('a-payer'),peut=roles().some(r=>r.startsWith('CAISSIER_'));
      el.innerHTML=`<p class="banner">Seuls les accords approuvés peuvent être versés. La caisse doit être ouverte et approvisionnée dans la devise de l’accord. Le bénéficiaire reste l’agent titulaire de l’accord.</p>${H.table(['Agent','Nature','Montant','État',''],rows.map(d=>`<tr><td>${esc(d.nom)}</td><td>${lib[d.nature]}</td><td>${money(d.montant,d.devise)}</td><td>${lib[d.statut]}</td><td>${peut&&d.statut==='approuve'?`<button class="btn btn-primary" data-verser="${d.id}">Verser</button>`:''}</td></tr>`))}`;
      el.querySelectorAll('[data-verser]').forEach(b=>b.onclick=async()=>{try{const d=rows.find(d=>d.id===b.dataset.verser),caisses=await api('/caisses?societe_id='+currentSocieteId);const disponibles=caisses.filter(c=>c.session_ouverte);if(!disponibles.length)throw new Error('Ouvrez d’abord une session de caisse.');
        H.formulaire('Verser — '+d.nom,H.select('caisse_id','Caisse ouverte',disponibles.map(c=>[c.id,c.libelle]))+H.champ('reference','Référence du reçu signé','text','','required maxlength="64"')+`<p class="rh-wide">${money(d.montant,d.devise)} seront décaissés pour ${esc(d.nom)}. Cette action enregistre le paiement et sa pièce comptable.</p>`,async p=>{const r=await H.appel(`dettes/${d.id}/verser`,{method:'POST',body:{...p,revision:d.revision}});setTimeout(()=>H.imprimer('Versement RH — '+esc(r.numero),r.date,['Agent','Montant','Référence comptable'],[[esc(r.nom),money(r.montant,r.devise),esc(r.ecriture)]],'Signature du bénéficiaire : ____________________'),0);},paiements);
      }catch(e){toast(e.message,'ko');}});
    }catch(e){el.innerHTML=`<p class="err">${esc(e.message)}</p>`;}
  }
  return {init};
})();
