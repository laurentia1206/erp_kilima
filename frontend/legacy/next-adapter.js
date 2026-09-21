/* Frontière explicite : React possède l'enveloppe ; les modules possèdent leurs vues. */
(() => {
  let navigationBusy = false;
  let taskTarget = null;
  const holds = new Set();
  window.KilimaNext.canLeave=()=>{
    if(!holds.size)return true;
    toast('Terminez la saisie ou fermez la fenêtre avant de quitter cet écran.','ko');return false;
  };
  const routeView = () => {
    const match = location.pathname.match(/^\/espace\/([a-z0-9-]+)\/?$/);
    return match?.[1] || null;
  };
  function snapshot(extra={}) {
    if(!me)taskTarget=null;
    const groups = me ? visibleModules().map(group => ({
      name:group.g, items:group.items.map(item=>({view:item.v, label:me.super_administrateur&&item.v==='administration'?'Utilisateurs & rôles':me.super_administrateur&&item.v==='audit'?'Journal de sécurité':item.l, icon:item.i, badge:item.badge})),
    })) : [];
    const title = me?.super_administrateur&&activeView==='administration'?'Utilisateurs & rôles':me?.super_administrateur&&activeView==='audit'?'Journal de sécurité':TITLES[activeView]?.[0] || 'Accueil';
    return { user:me, companies:societes, companyId:currentSocieteId, view:activeView, title, taskTarget:me && taskTarget?.view===activeView ? taskTarget : null,
      subtitle:me?.super_administrateur&&activeView==='administration'?'Comptes utilisateurs, rôles et affectations':TITLES[activeView]?.[1] || '', groups, ...extra };
  }
  function publish(extra={}) {
    if(extra.navigated && me) {
      const url='/espace/'+activeView;
      if(location.pathname!==url)history.pushState(null,'',url);
      document.title=snapshot().title+' · KILIMA HOLDINGS';
    }
    window.dispatchEvent(new CustomEvent('kilima:state',{detail:snapshot(extra)}));
  }
  window.KilimaNext.publish=publish;
  window.KilimaNext.initialView=()=>{
    const requested=routeView();
    return requested && visibleModules().some(g=>g.items.some(i=>i.v===requested)) ? requested : null;
  };
  for(const view of ['accueil','pilotage','audit','stock','taux','articles','hotel-chambres','depots','inventaires','hotel-reception','cuisine','balance','grand-livre','saisie-od','plan-comptable','lettrage','rapprochement','cockpit','etats','analytique','tva','compta','rapports-commercial', 'dashboard', 'config-hotel', 'config-engins', 'config-transport', 'config-maintenance', 'contrats-transport', 'flotte-documents', 'engins-rpe', 'flotte', 'engins-parc', 'engins-heures', 'maintenance-parc', 'maintenance-interventions', 'carburant', 'tarifs-pos', 'transferts', 'caisse-exec', 'intersociete', 'nouvelle-req', 'requisitions', 'approbation', 'ordres', 'avances', 'caisse', 'courses', 'config', 'administration', 'systeme', 'rh', 'rh-simulateur', 'rh-decomptes', 'rh-finances', 'rh-paiements', 'rh-mensuel', 'achats', 'ventes', 'commandes', 'receptions', 'devis', 'pos'])if(view==='accueil'||window.KilimaNext.owns?.(view))RENDER[view]=()=>{};
  const bridge={
    snapshot, api,
    refreshAccountingBadge:()=>refreshComptaBadge(),
    holdNavigation(){const key={};holds.add(key);return ()=>holds.delete(key);},
    async download(path,filename,body){
      if(!path.startsWith('/')||path.startsWith('//'))throw new Error('Chemin de document invalide.');
      const auth=token,company=currentSocieteId;
      const headers={Authorization:'Bearer '+auth};if(body!==undefined)headers['Content-Type']='application/json';
      const result=await fetch(API+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body)});
      if(result.status===401){logout();throw new Error('Session expirée. Veuillez vous reconnecter.');}
      if(!result.ok){const error=await result.json().catch(()=>({}));throw new Error(typeof error.detail==='string'?error.detail:'Le document ne peut pas être téléchargé.');}
      const blob=await result.blob();
      if(auth!==token||company!==currentSocieteId)throw new Error('Session ou société modifiée. Rouvrez le document.');
      const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
    },
    async openTask(view,type,documentId){
      await go(view);
      if(activeView===view&&['req_validation','req_precision','ordre_emission'].includes(type)){taskTarget={view,type,documentId};publish();}
    },
    clearTask(){taskTarget=null;publish();},
    async restore(){
      // Après un remontage React de développement, restaurer uniquement une vue vide.
      if(me && !window.KilimaNext.owns?.(activeView) && !$('#view-'+activeView)?.childElementCount)await go(activeView);
    },
    async start(){if(token){try{await boot();}catch(error){logout();throw error;}}publish();},
    async login(email,password){
      const result=await api('/auth/login',{method:'POST',form:true,body:{username:email,password}});
      token=result.access_token;localStorage.setItem('kh_token',token);
      try{await boot();}catch(error){logout();throw error;}
    },
    async changePassword(oldPassword,newPassword){
      const result=await api('/systeme/mot-de-passe',{method:'POST',body:{ancien:oldPassword,nouveau:newPassword}});
      token=result.access_token;localStorage.setItem('kh_token',token);
      try{await boot();}catch(error){logout();throw error;}
    },
    logout(){
      if(!window.KilimaNext.canLeave())return;
      // Capturer le jeton avant l'effacement local. Une panne de réseau ne doit
      // jamais empêcher la déconnexion ni déconnecter une future session.
      const auth=token;
      if(auth)fetch(API+'/auth/logout',{method:'POST',headers:{Authorization:'Bearer '+auth},keepalive:true}).catch(()=>{});
      logout();history.replaceState(null,'','/');document.title='ERP KILIMA HOLDINGS';
    },
    async navigate(view,group){
      if(navigationBusy||!me)return;
      navigationBusy=true;
      try{await go(view,group);}finally{navigationBusy=false;}
    },
    async selectCompany(id){
      if(!me || !societes.some(s=>s.id===id) || id===currentSocieteId)return;
      if(!window.KilimaNext.canLeave())return;
      if(pendingWrites.size || $('#modal-root').childElementCount){toast('Terminez l’opération ou fermez la fenêtre avant de changer de société.','ko');return;}
      if(!Clotures.confirmLeave())return;
      taskTarget=null;currentSocieteId=id;localStorage.setItem('kh_societe_'+me.id,id);
      renderSidebar();refreshBadge();refreshComptaBadge();await go('accueil');Pilotage.badge();
    },
    closeModal,
  };
  window.KilimaERP=bridge;
  window.addEventListener('popstate',()=>{
    if(!me)return;
    const view=routeView() || (me.super_administrateur?'systeme':'accueil');
    bridge.navigate(view).then(()=>{if(routeView()!==activeView)history.replaceState(null,'','/espace/'+activeView);});
  });
  document.addEventListener('keydown',event=>{
    const overlay=$('#modal-root').lastElementChild;
    if(event.key==='Escape' && overlay){closeModal();return;}
    if(event.key==='Tab' && overlay){
      const controls=[...overlay.querySelectorAll('button,input,select,textarea,a[href],[tabindex="0"]')].filter(x=>!x.disabled&&x.getClientRects().length);
      const first=controls[0],last=controls.at(-1);
      if(!first){event.preventDefault();return;}
      if(event.shiftKey&&(document.activeElement===first||!controls.includes(document.activeElement))){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&(document.activeElement===last||!controls.includes(document.activeElement))){event.preventDefault();first.focus();}
    }
  });
})();
