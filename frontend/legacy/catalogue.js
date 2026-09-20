/* Sélection et création dans le formulaire courant ; aucune copie intersociété. */
"use strict";
const Catalogue = (() => {
  const norm = value => ModuleUX.normalize(value).replace(/\s+/g,' ');
  const company = () => societes.find(s=>s.id===currentSocieteId)?.nom || '';
  const label = item => `${item.nom||''}${Object.hasOwn(item,'societe_id') ? `${item.code?' · '+item.code:''}${item.societe_id===null?' · Fiche partagée':' · Société active'}` : ''}`;
  const addOption = (select, item, article=false) => {
    let option=[...select.options].find(o=>o.value===item.id);
    if(!option){option=document.createElement('option');option.value=item.id;select.append(option);}
    option.textContent=article?`${item.code} — ${item.designation}`:label(item);
    option.dataset.intra=String(!!item.intra_groupe);
    return option;
  };
  const append = (select,item,article=false)=>{
    addOption(select,item,article);
    select.value=item.id;select.dispatchEvent(new Event('change',{bubbles:true}));
  };
  async function quick(kind, done, settings={}) {
    const sid=currentSocieteId, article=kind==='article';
    const endpoint=settings.endpoint || (article?'/commercial/articles':'/commercial/tiers');
    let records;
    try {records=await api(`${endpoint}?societe_id=${sid}${article||endpoint==='/hotel/clients'||endpoint==='/beneficiaires'?'':`&type=${kind}`}`);}
    catch(e){toast(e.message,'ko');return;}
    if(sid!==currentSocieteId)return;
    const defaultTva=article?await api(`/comptabilite/comptes-config?societe_id=${sid}`).then(d=>d.tva_taux_defaut).catch(()=>16):0;
    if(sid!==currentSocieteId)return;
    modal({title:`Créer un ${article?'article':kind==='beneficiaire'?'bénéficiaire':kind}`,
      body:`<div class="catalogue-scope">Fiche propre à <b>${esc(company())}</b></div>
      ${kind==='beneficiaire'?'<div class="form-group"><label class="form-label">Type de bénéficiaire</label><select class="form-select cat-kind"><option value="agent">Agent</option><option value="fournisseur">Fournisseur</option><option value="client">Client</option></select><p class="muted">Choisissez un agent existant dans les résultats lorsqu’il est déjà enregistré. Une nouvelle fiche bénéficiaire ne crée pas de compte de connexion.</p></div>':''}
      <div class="form-row"><div class="form-group"><label class="form-label">Code unique dans cette société</label><input class="form-input cat-code" maxlength="32" /></div>
      <div class="form-group"><label class="form-label">${article?'Désignation':'Nom'}</label><input class="form-input cat-name" maxlength="255" /></div></div>
      <div class="cat-matches" aria-live="polite"></div>
      ${article?`<div class="form-row"><div class="form-group"><label class="form-label">Nature</label><select class="form-select cat-nature"><option value="marchandise">Marchandise / article vendu</option><option value="matiere_premiere">Matière première</option><option value="consommable">Consommable</option></select></div><div class="form-group"><label class="form-label">Unité</label><input class="form-input cat-unit" value="unité" /></div></div>
      <div class="form-row"><div class="form-group"><label class="form-label">Prix d'achat USD</label><input class="form-input cat-buy" type="number" min="0" step="any" value="0" /></div><div class="form-group"><label class="form-label">Prix de vente USD</label><input class="form-input cat-sell" type="number" min="0" step="any" value="0" /></div><div class="form-group"><label class="form-label">TVA %</label><input class="form-input cat-tax" type="number" min="0" step="any" value="${defaultTva}" /></div></div>
      <label><input class="cat-stock" type="checkbox" checked /> Géré en stock</label> <label><input class="cat-vat" type="checkbox" checked /> Assujetti à la TVA</label>`:
      endpoint==='/hotel/clients'?'':`<label><input class="cat-intra" type="checkbox" /> Société du groupe (intra-groupe)</label>${kind==='beneficiaire'?'':'<div class="form-group"><label class="form-label">Plafond de crédit USD (facultatif)</label><input class="form-input cat-credit" type="number" min="0" step="any" /></div>'}`}
      <div class="cat-error err" role="alert"></div>
      <label class="cat-confirm hidden"><input type="checkbox" /> J'ai vérifié : il s'agit d'une personne ou d'un article distinct, avec un autre code.</label>`,
      footer:'<button class="btn cat-cancel">Annuler</button><button class="btn btn-primary cat-save">Créer et sélectionner</button>'});
    const overlay=document.querySelector('#modal-root').lastElementChild;
    const $c=s=>overlay.querySelector(s);
    const acceptable=item=>item.actif!==false && (!article || (!settings.stockRequired || item.gere_stock!==false) && (!settings.natureLocked || item.nature===(settings.nature||'marchandise')));
    const finish=item=>{if(sid!==currentSocieteId||!overlay.isConnected)return;if(!acceptable(item)){$c('.cat-error').textContent='Cette fiche ne correspond pas à ce champ (nature, stock ou statut).';return;}closeModal();done?.(item);};
    $c('.cat-cancel').onclick=closeModal;
    if(article){$c('.cat-nature').value=settings.nature||'marchandise'; if(settings.natureLocked)$c('.cat-nature').disabled=true;if(settings.stockRequired)$c('.cat-stock').disabled=true;}
    const matches=()=>{
      $c('.cat-confirm input').checked=false;$c('.cat-confirm').classList.add('hidden');
      const code=norm($c('.cat-code').value), name=norm($c('.cat-name').value);
      const found=records.filter(r=>(code&&norm(r.code)===code)||(name.length>=2&&norm(r.designation||r.nom).includes(name))).slice(0,8);
      $c('.cat-matches').innerHTML=found.length?'<p>Fiches déjà présentes — vérifiez avant de créer :</p>'+found.map(r=>`<button type="button" class="catalogue-result" data-id="${r.id}"><b>${esc(r.code)} — ${esc(article?r.designation:label(r))}</b><span>${r.actif===false?'Archivée — à réactiver dans la gestion des fiches':'Sélectionner cette fiche'}</span></button>`).join(''):'';
      $c('.cat-matches').querySelectorAll('button').forEach(b=>{const item=found.find(r=>r.id===b.dataset.id); b.disabled=!acceptable(item); b.onclick=()=>finish(item);});
    };
    $c('.cat-code').oninput=matches;$c('.cat-name').oninput=matches;
    $c('.cat-save').onclick=async()=>{
      const button=$c('.cat-save');if(button.disabled)return;
      if(sid!==currentSocieteId){$c('.cat-error').textContent='La société a changé. Fermez et rouvrez ce formulaire.';return;}
      const code=$c('.cat-code').value.trim(),name=$c('.cat-name').value.trim();
      if(!code||name.length<2){$c('.cat-error').textContent='Code et nom complet requis.';return;}
      const body={code,confirmer_homonyme:$c('.cat-confirm input').checked};
      if(article)Object.assign(body,{designation:name,nature:$c('.cat-nature').value,unite:$c('.cat-unit').value.trim()||'unité',prix_achat:+$c('.cat-buy').value,prix_vente:+$c('.cat-sell').value,taux_tva:+$c('.cat-tax').value,assujetti_tva:$c('.cat-vat').checked,gere_stock:$c('.cat-stock').checked});
      else Object.assign(body,{type:kind==='beneficiaire'?$c('.cat-kind').value:kind,nom:name,intra_groupe:!!$c('.cat-intra')?.checked,limite_credit_usd:$c('.cat-credit')?.value?+$c('.cat-credit').value:null});
      button.disabled=true;
      try{const item=await api(`${endpoint}?societe_id=${sid}`,{method:'POST',body});finish(item);toast('Fiche créée et sélectionnée.','ok');}
      catch(e){$c('.cat-error').textContent=e.message;if(e.data?.can_confirm_similar==='True'||e.data?.can_confirm_similar===true)$c('.cat-confirm').classList.remove('hidden');}
      finally{if(overlay.isConnected)button.disabled=false;}
    };
  }
  function bind(select, settings={}) {
    if(!select||select.disabled||select.dataset.catalogue)return;
    select.dataset.catalogue='true';
    const button=document.createElement('button');button.type='button';button.className='btn btn-sm catalogue-open';button.textContent='Rechercher / créer…';select.after(button);
    button.onclick=()=>{
      const sid=currentSocieteId,items=[...select.options].filter(o=>o.value).map(o=>({id:o.value,label:o.textContent}));
      modal({title:settings.kind==='article'?'Choisir un article':`Choisir un ${settings.kind==='beneficiaire'?'bénéficiaire':settings.kind||'client'}`,
        body:`<div class="catalogue-scope">${esc(company())}</div><label class="form-label">Rechercher par nom ou code</label><input class="form-input catalogue-search" type="search" aria-label="Rechercher une fiche" /><div class="catalogue-results"></div>`,
        footer:`<button class="btn catalogue-close">Annuler</button>${settings.create!==false?'<button class="btn btn-primary catalogue-create">Créer une nouvelle fiche</button>':''}`});
      const overlay=document.querySelector('#modal-root').lastElementChild;
      const pick=item=>{if(sid!==currentSocieteId||!select.isConnected)return;select.value=item.id;select.dispatchEvent(new Event('change',{bubbles:true}));closeModal();};
      const draw=()=>{const q=norm(overlay.querySelector('input').value);const found=items.filter(i=>norm(i.label).includes(q));const host=overlay.querySelector('.catalogue-results');host.innerHTML=found.map(i=>`<button type="button" class="catalogue-result" data-id="${i.id}">${esc(i.label)}</button>`).join('')||'<p class="muted">Aucune fiche correspondante dans cette liste.</p>';host.querySelectorAll('button').forEach(b=>b.onclick=()=>pick(items.find(i=>i.id===b.dataset.id)));};
      overlay.querySelector('input').oninput=draw;draw();overlay.querySelector('.catalogue-close').onclick=closeModal;
      if(settings.create!==false)overlay.querySelector('.catalogue-create').onclick=()=>{
        closeModal();
        if(settings.openCreate){settings.openCreate();return;}
        quick(settings.kind||'client',item=>{settings.accept?.(item);append(select,item,settings.kind==='article');},settings);
      };
    };
  }
  function enhance(root) {
    root.querySelectorAll('#o-benef,#x-benef').forEach(s=>bind(s,{kind:'beneficiaire',endpoint:'/beneficiaires',create:has('DFI','COMPTABLE','CAISSIER_CENTRAL','CAISSIER_VENDEUR')}));
    for(const [selector,kind] of [['#dv-cli,#co-cli,#ct-cli,#fe-tiers','client'],['#cm-prop','fournisseur']])
      root.querySelectorAll(selector).forEach(s=>bind(s,{kind,create:has('DFI','COMPTABLE','CAISSIER_CENTRAL','CAISSIER_VENDEUR')}));
    for(const [selector,newSelector] of [['.fl-art','.fl-anew'],['.cl-art','.cl-anew'],['.jm-art','.jm-anew']])
      root.querySelectorAll(selector).forEach(s=>bind(s,{kind:'article',create:has('DFI','COMPTABLE'),openCreate:()=>s.parentElement.querySelector(newSelector).click()}));
    for(const [selector,newSelector,kind] of [['#f-tiers','#f-tnew',null],['#cmd-tiers','#cmd-tnew','fournisseur']])
      root.querySelectorAll(selector).forEach(s=>bind(s,{kind:kind||'client / fournisseur',create:has('DFI','COMPTABLE','CAISSIER_CENTRAL','CAISSIER_VENDEUR'),openCreate:()=>root.querySelector(newSelector).click()}));
  }
  function init(){
    const root=document.querySelector('#modal-root');let queued=false;
    new MutationObserver(()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;root.querySelectorAll('.modal-overlay').forEach(enhance);});}).observe(root,{childList:true,subtree:true});
  }
  function confirmConflict(error,onConfirm){
    if(![true,'True'].includes(error.data?.can_confirm_similar))return false;
    modal({title:'Vérifier une fiche similaire',body:`<p>${esc(error.message)}</p><p class="catalogue-scope">Confirmez uniquement s’il s’agit d’une personne ou d’un article distinct. Aucune fusion de fiches ne sera effectuée.</p>`,footer:'<button class="btn cat-keep">Revenir et vérifier</button><button class="btn btn-primary cat-distinct">Confirmer une fiche distincte</button>'});
    const root=document.querySelector('#modal-root').lastElementChild;
    root.querySelector('.cat-keep').onclick=closeModal;
    root.querySelector('.cat-distinct').onclick=()=>{closeModal();onConfirm();};return true;
  }
  return {quick,bind,append,addOption,enhance,norm,init,label,confirmConflict};
})();
