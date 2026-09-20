/* Journal confidentiel : filtres, consultation et exports validés côté serveur. */
const AuditJournal=(()=>{
  let serial=0, protectionSerial=0, page=1, borne=null, data=null, appliedParams=null;
  const root=()=>document.querySelector('#view-audit');
  const kind={donnees:'Modification de données',metier:'Opération métier',securite:'Sécurité',consultation:'Consultation / export',historique:'Historique'};
  const date=v=>v?new Date(v).toLocaleString('fr-FR',{timeZone:'Africa/Lubumbashi'}):'Non daté';
  const value=v=>v===undefined?'Non enregistré':v===null?'Vide':typeof v==='object'?JSON.stringify(v,null,2):String(v);
  function params(){
    const q=new URLSearchParams({societe_id:currentSocieteId,page:String(page)});
    root().querySelectorAll('[data-filter]').forEach(el=>{if(el.value)q.set(el.dataset.filter,el.value);});
    if(borne)q.set('borne',String(borne));
    return q;
  }
  function valid(ctx){return ctx.auth===token&&ctx.societe===currentSocieteId&&activeView==='audit'&&ctx.serial===serial;}
  function capture(){return {auth:token,societe:currentSocieteId,serial};}
  function init(){
    NAV.find(g=>g.g==='Pilotage').items.push({v:'audit',l:'Journal de traçabilité',i:'ti-history',roles:['DFI','ADMIN_SYS']});
    TITLES.audit=['Journal de traçabilité','Qui a fait quoi, quand et sur quel document'];RENDER.audit=ouvrir;
  }
  function ouvrir(){
    serial++;protectionSerial++;page=1;borne=null;data=null;appliedParams=null;
    const soc=societes.find(s=>s.id===currentSocieteId);
    if(!me?.super_administrateur&&!soc?.roles.some(r=>['DFI','ADMIN_SYS'].includes(r))){root().innerHTML='<div class="card">Ce journal est réservé au DFI et à l’administration de la société.</div>';return;}
    const today=new Date(),before=new Date(today);before.setDate(today.getDate()-7);
    const day=d=>d.toLocaleDateString('fr-CA',{timeZone:'Africa/Lubumbashi'});
    root().innerHTML=`<div class="audit-head"><div><h2>Journal de traçabilité</h2><p class="muted">${esc(me?.super_administrateur?"Comptes et habilitations":soc.nom)} · Heures de Lubumbashi · Données confidentielles</p></div><div class="audit-actions"><button class="btn" id="audit-refresh">Actualiser</button><button class="btn" id="audit-excel" disabled>Excel</button><button class="btn" id="audit-pdf" disabled>PDF</button></div></div>
      <div id="audit-protection" class="audit-protection" role="status">Vérification de la protection du journal…</div>
      <form class="card audit-filters" id="audit-filters">
        ${me?.super_administrateur?'<label>Périmètre<select class="form-input" data-filter="portee"><option value="global">Utilisateurs et habilitations</option></select></label>':`<label>Périmètre<select class="form-input" data-filter="portee"><option value="societe">Société active</option><option value="partage">Clients / fournisseurs partagés</option>${hasGlobal('ADMIN_SYS')?'<option value="global">Sécurité et réglages globaux</option>':''}</select></label>`}
        <label>Du<input class="form-input" type="date" data-filter="du" value="${day(before)}"></label><label>Au<input class="form-input" type="date" data-filter="au" value="${day(today)}"></label>
        <label>Utilisateur<select class="form-input" data-filter="utilisateur_id"><option value="">Tous les utilisateurs</option></select></label>
        <label>Module<select class="form-input" data-filter="module"><option value="">Tous les modules</option></select></label>
        <label>Type<select class="form-input" data-filter="categorie"><option value="">Tous les événements</option>${Object.entries(kind).map(([v,l])=>`<option value="${v}">${l}</option>`).join('')}</select></label>
        <label>Action ou référence<input class="form-input" data-filter="q" placeholder="Ex. article, validation, référence…" maxlength="100"></label>
        <label>Identifiant de requête<input class="form-input" data-filter="requete_id" placeholder="Regrouper une opération" maxlength="36"></label>
        <button class="btn btn-primary" type="submit">Appliquer les filtres</button><button class="btn" type="button" id="audit-clear">Réinitialiser</button>
      </form><p class="muted audit-note">Une opération peut produire plusieurs traces liées par un identifiant de requête. Les champs RH sensibles et les secrets sont masqués. Les anciennes traces incomplètes restent identifiées comme historiques.</p>
      <p id="audit-error" role="alert" class="err"></p><div id="audit-results" aria-live="polite">Chargement…</div>`;
    root().querySelector('#audit-filters').onsubmit=e=>{e.preventDefault();page=1;borne=null;charger();};
    root().querySelector('#audit-refresh').onclick=()=>{page=1;borne=null;charger();protection();};
    root().querySelector('#audit-clear').onclick=ouvrir;
    root().querySelector('[data-filter="portee"]').onchange=()=>{for(const key of ['utilisateur_id','module'])root().querySelector(`[data-filter="${key}"]`).value='';page=1;borne=null;charger();protection();};
    root().querySelector('#audit-excel').onclick=()=>exporter('xlsx');root().querySelector('#audit-pdf').onclick=()=>exporter('pdf');
    charger();protection();
  }
  async function protection(){
    const ctx=capture(),q=params(),check=++protectionSerial;
    const current=()=>ctx.auth===token&&ctx.societe===currentSocieteId&&activeView==='audit'&&check===protectionSerial;
    try{const p=await api('/audit/protection?'+q);if(!current())return;
      const el=root().querySelector('#audit-protection');el.classList.toggle('audit-danger',!p.active);
      el.textContent=p.active?'Protection en place · Modification et suppression des traces bloquées':'Protection incomplète — contactez immédiatement votre informaticien.';
      el.title=p.limite;
    }catch(e){if(current())root().querySelector('#audit-protection').textContent='Protection non vérifiée : '+e.message;}
  }
  async function charger(){
    serial++;const ctx=capture(),q=params();data=null;
    root().querySelector('#audit-error').textContent='';root().querySelector('#audit-results').textContent='Chargement…';
    root().querySelectorAll('#audit-excel,#audit-pdf').forEach(b=>b.disabled=true);
    try{
      const result=await api('/audit/journal?'+q);if(!valid(ctx))return;data=result;borne=result.borne;appliedParams=new URLSearchParams(q);if(borne)appliedParams.set('borne',String(borne));
      for(const [field,items] of [['utilisateur_id',result.utilisateurs.map(u=>[u.id,u.nom])],['module',result.modules.map(m=>[m,m])]]){
        const select=root().querySelector(`[data-filter="${field}"]`),saved=select.value;
        select.innerHTML='<option value="">Tous</option>'+items.map(([v,l])=>`<option value="${esc(v)}">${esc(l)}</option>`).join('');select.value=saved;
      }
      const pages=Math.max(1,Math.ceil(result.total/result.taille_page));
      root().querySelector('#audit-results').innerHTML=`<div class="audit-count"><b>${result.total} événements</b><span>Page ${page} / ${pages} · Situation chargée à ${new Date().toLocaleTimeString('fr-FR')}</span></div><div class="card audit-table"><table><thead><tr><th>Date / heure</th><th>Utilisateur</th><th>Action</th><th>Document / module</th><th>Type</th><th>Détail</th></tr></thead><tbody>${result.resultats.map(r=>`<tr><td>${esc(date(r.date))}<small>N° ${r.id}</small></td><td>${esc(r.utilisateur)}<small>${esc(r.adresse_ip||'IP non disponible')}</small></td><td><b>${esc(r.action)}</b><small>${esc((r.champs_modifies||[]).slice(0,5).join(', '))}${r.champs_modifies?.length>5?'…':''}</small></td><td>${esc(r.table)}<small>${esc(r.document||'Sans référence')} · ${esc(r.module)}</small></td><td><span class="audit-type">${esc(kind[r.categorie]||r.categorie)}</span></td><td><button class="btn btn-sm" data-detail="${r.id}">Examiner</button></td></tr>`).join('')||'<tr><td colspan="6" class="audit-empty">Aucun événement pour ces filtres.</td></tr>'}</tbody></table></div><div class="audit-pages"><button class="btn" id="audit-prev" ${page<=1?'disabled':''}>Précédent</button><button class="btn" id="audit-next" ${page>=pages?'disabled':''}>Suivant</button></div>`;
      root().querySelectorAll('[data-detail]').forEach(b=>b.onclick=()=>detail(b.dataset.detail));
      root().querySelector('#audit-prev').onclick=()=>{page--;charger();};root().querySelector('#audit-next').onclick=()=>{page++;charger();};
      root().querySelectorAll('#audit-excel,#audit-pdf').forEach(b=>b.disabled=!result.total);
    }catch(e){if(valid(ctx)){root().querySelector('#audit-error').textContent=e.message;root().querySelector('#audit-results').textContent='Aucune donnée affichée. Corrigez les filtres ou réessayez.';}}
  }
  async function detail(id){
    const ctx=capture();
    try{const r=await api(`/audit/journal/${id}?${appliedParams}`);if(!valid(ctx))return;
      const before=r.avant&&typeof r.avant==='object'?r.avant:{valeur:r.avant},after=r.apres&&typeof r.apres==='object'?r.apres:{valeur:r.apres};
      const keys=r.champs_modifies?.length?r.champs_modifies:[...new Set([...Object.keys(before),...Object.keys(after)])];
      modal({title:`Trace n° ${r.id} · ${r.action}`,wide:true,body:`<p><b>${esc(r.utilisateur)}</b> · ${esc(date(r.date))} · ${esc(kind[r.categorie]||r.categorie)}</p><p>${esc(r.table)} · ${esc(r.document||'Sans référence')}</p><p class="muted">IP : ${esc(r.adresse_ip||'Non disponible')} · ${esc(r.methode)} ${esc(r.chemin)}</p><div class="audit-diff"><table><thead><tr><th>Champ</th><th>Avant</th><th>Après</th></tr></thead><tbody>${keys.map(k=>`<tr><th>${esc(k)}</th><td><pre>${esc(value(before[k]))}</pre></td><td><pre>${esc(value(after[k]))}</pre></td></tr>`).join('')}</tbody></table></div><p class="muted">Requête : ${esc(r.requete_id||'Non disponible sur cette trace')} · Origine : ${esc(r.origine)}</p>`,footer:`<button class="btn" id="audit-close">Fermer</button>${r.requete_id?'<button class="btn btn-primary" id="audit-related">Voir les traces liées</button>':''}`});
      const overlay=document.querySelector('#modal-root').lastElementChild;overlay.querySelector('#audit-close').onclick=closeModal;
      if(r.requete_id)overlay.querySelector('#audit-related').onclick=()=>{closeModal();root().querySelector('[data-filter="requete_id"]').value=r.requete_id;page=1;borne=null;charger();};
    }catch(e){if(valid(ctx))toast(e.message,'ko');}
  }
  async function exporter(format){
    if(!data||!appliedParams)return;
    const ctx=capture(),q=new URLSearchParams(appliedParams);q.set('format_export',format);
    const button=root().querySelector(format==='pdf'?'#audit-pdf':'#audit-excel');button.disabled=true;
    try{
      const r=await fetch('/api/audit/export?'+q,{headers:{Authorization:'Bearer '+ctx.auth}});
      if(!r.ok){const error=await r.json().catch(()=>({}));throw new Error(error.detail||'Export impossible.');}
      const blob=await r.blob();if(!valid(ctx))return;
      const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='journal-audit.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){if(valid(ctx))toast(e.message,'ko');}finally{if(valid(ctx))button.disabled=!data?.total;}
  }
  return {init,ouvrir};
})();
