/* Administration globale : le serveur contrôle chaque opération. */
const Systeme=(()=>{
  let generation=0;
  const root=()=>document.querySelector('#view-systeme');
  const labels={consulter:'Consulter',creer:'Créer',modifier:'Modifier',supprimer:'Supprimer',executer:'Actions métier',exporter:'Exporter'};
  const groupes={'Pilotage':'pilotage','Réquisitions & validations':'approbations','Trésorerie':'tresorerie','Comptabilité':'comptabilite','Achats':'commercial','Ventes':'commercial','Point de vente':'commercial','Stocks & inventaires':'stocks','Ressources humaines':'rh','Hôtel & restauration':'hotel','Transport':'transport','Location d’engins':'engins','Parc & maintenance':'maintenance','Gestion du groupe':'groupe','Administration & réglages':'administration'};
  function moduleVue(view){
    if(view==='accueil'||view==='systeme')return null;
    if(view==='audit')return 'audit';
    if(view==='taux')return 'comptabilite';
    if(view==='flotte-documents')return 'maintenance';
    if(view==='carburant')return 'transport';
    return groupes[NAV.find(g=>g.items.some(i=>i.v===view))?.g];
  }
  function autorise(view){
    if(me?.super_administrateur)return ['systeme','administration','audit'].includes(view);
    if(view==='systeme')return false;
    return me?.permissions?.[moduleVue(view)]?.consulter!==false;
  }
  function init(){
    NAV.find(g=>g.g==='Paramètres').items.unshift({v:'systeme',l:'Super administration',i:'ti-shield-lock',roles:['SUPER_ADMIN']});
    TITLES.systeme=['Super administration','Comptes utilisateurs, rôles et permissions'];RENDER.systeme=ouvrir;
  }
  function courant(n,auth){return n===generation&&token===auth&&activeView==='systeme'&&me?.super_administrateur;}
  async function ouvrir(){
    const n=++generation,auth=token;
    if(!me?.super_administrateur){root().textContent='Cet espace est réservé au super administrateur.';return;}
    if(me.changer_mot_de_passe){motDePasse(true);return;}
    root().innerHTML='<div class="card sys-pad">Chargement des habilitations…</div>';
    const d=await api('/systeme/utilisateurs');if(!courant(n,auth))return;
    root().innerHTML=`<div class="sys-hero"><div><span class="sys-eyebrow">ADMINISTRATION DU SYSTÈME</span><h2>Gardez la maîtrise des accès</h2><p>Gestion des utilisateurs uniquement · Les changements de droits sont tracés.</p></div><button class="btn" id="sys-refresh">Actualiser</button></div>
    <div class="sys-stats"><div><strong>${d.utilisateurs.length}</strong><span>Comptes utilisateurs</span></div><div><strong>${d.utilisateurs.filter(u=>u.actif).length}</strong><span>Comptes actifs</span></div><div><strong>${d.roles}</strong><span>Rôles disponibles</span></div><div><strong>${d.utilisateurs.filter(u=>u.super_administrateur).length}</strong><span>Super administrateurs</span></div></div>
    <div class="sys-links"><button class="btn" data-section="agents">Créer / gérer les comptes</button><button class="btn" data-section="roles">Rôles et héritage</button><button class="btn" id="sys-audit">Journal des utilisateurs</button><button class="btn" id="sys-password">Mon mot de passe</button></div>
    <div class="card sys-pad"><div class="sys-toolbar"><div><h3>Utilisateurs et permissions</h3><p class="muted">Les rôles définissent les droits par société. Les limites par module s’appliquent dans toutes les sociétés de l’utilisateur.</p></div><label>Rechercher<input class="form-input" id="sys-search" type="search" placeholder="Nom, email, société ou rôle"></label></div><div class="sys-scroll"><table><thead><tr><th>Utilisateur</th><th>Statut</th><th>Accès aux sociétés</th><th>Gestion des droits</th></tr></thead><tbody id="sys-users"></tbody></table></div></div>`;
    function afficher(){
      const term=root().querySelector('#sys-search').value.trim().toLocaleLowerCase('fr');
      root().querySelector('#sys-users').innerHTML=d.utilisateurs.filter(u=>[u.nom,u.prenom,u.email,...u.affectations.map(a=>a.societe+' '+a.role)].join(' ').toLocaleLowerCase('fr').includes(term)).map(u=>`<tr><td><b>${esc(u.nom)} ${esc(u.prenom||'')}</b><small>${esc(u.email)}</small></td><td><span class="pill ${u.actif?'st-payee':'st-annule'}">${u.actif?'Actif':'Désactivé'}</span>${u.super_administrateur?'<small class="sys-super">Super administrateur</small>':''}</td><td>${u.super_administrateur?'Gestion des comptes uniquement':u.affectations.map(a=>`<span class="tag">${esc(a.societe)} · ${esc(a.role)}</span>`).join(' ')||'<span class="muted">Aucune affectation</span>'}</td><td><div class="sys-row-actions"><button class="btn btn-sm" data-rights="${u.id}">Permissions</button><button class="btn btn-sm" data-aff="${u.id}">Rôles / sociétés</button></div></td></tr>`).join('')||'<tr><td colspan="4">Aucun utilisateur trouvé.</td></tr>';
      root().querySelectorAll('[data-rights]').forEach(b=>b.onclick=()=>droits(b.dataset.rights,d));
      root().querySelectorAll('[data-aff]').forEach(b=>b.onclick=()=>adminAffectationsModal(b.dataset.aff).catch(e=>toast(e.message,'ko')));
    }
    root().querySelector('#sys-search').oninput=afficher;afficher();
    root().querySelector('#sys-refresh').onclick=()=>go('systeme');
    root().querySelectorAll('[data-section]').forEach(b=>b.onclick=()=>{adminTab=b.dataset.section;go('administration');});
    root().querySelector('#sys-audit').onclick=()=>go('audit');root().querySelector('#sys-password').onclick=()=>motDePasse(false);
  }
  async function droits(id,catalogue){
    const n=generation,auth=token;
    try{
      const u=await api('/systeme/utilisateurs/'+id);if(!courant(n,auth))return;
      modal({title:'Permissions · '+u.nom,wide:true,body:`<p>${esc(u.email)}</p><div class="banner">${u.super_administrateur?'Ce compte gère les utilisateurs, leurs rôles et leurs permissions. Il ne peut ni consulter ni exécuter les opérations des sociétés.':'Les cases cochées conservent les droits permis par les rôles. Elles ne donnent pas, à elles seules, un droit de validation. Décochez une case pour limiter cet utilisateur dans toutes ses sociétés.'}</div>${u.super_administrateur?'':`<div class="sys-links"><button class="btn btn-sm" data-preset="roles">Droits des rôles</button><button class="btn btn-sm" data-preset="lecture">Lecture seule</button><button class="btn btn-sm" data-preset="aucun">Tout restreindre</button></div><div class="sys-scroll"><table class="sys-permissions"><thead><tr><th>Module</th>${catalogue.actions.map(a=>`<th>${labels[a]}</th>`).join('')}</tr></thead><tbody>${Object.entries(catalogue.modules).map(([m,l])=>`<tr><th>${esc(l)}</th>${catalogue.actions.map(a=>catalogue.capacites?.[m]&&!catalogue.capacites[m].includes(a)?'<td aria-label="Non applicable">—</td>':`<td><input type="checkbox" data-module="${m}" data-action="${a}" aria-label="${esc(l+' : '+labels[a])}" ${u.permissions[m]?.[a]!==false?'checked':''}></td>`).join('')}</tr>`).join('')}</tbody></table></div>`}<p id="sys-err" class="err" role="alert"></p>`,footer:`<button class="btn" id="sys-close">Fermer</button>${id!==me.id?`<button class="btn" id="sys-status">${u.super_administrateur?'Retirer le statut global':'Nommer super administrateur'}</button>`:''}${u.super_administrateur?'':'<button class="btn btn-primary" id="sys-save">Enregistrer les permissions</button>'}`});
      const box=document.querySelector('#modal-root').lastElementChild;
      box.querySelector('#sys-close').onclick=closeModal;
      box.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>box.querySelectorAll('[data-module]').forEach(c=>{c.checked=b.dataset.preset==='roles'||b.dataset.preset==='lecture'&&c.dataset.action==='consulter';}));
      const save=box.querySelector('#sys-save');if(save)save.onclick=async()=>{
        save.disabled=true;
        const permissions=Object.keys(catalogue.modules).map(module=>({module,...Object.fromEntries(catalogue.actions.map(a=>[a,box.querySelector(`[data-module="${module}"][data-action="${a}"]`)?.checked??true]))}));
        try{await api('/systeme/utilisateurs/'+id,{method:'PATCH',body:{revision:u.revision,permissions}});closeModal();toast('Permissions enregistrées. Elles s’appliquent dès la prochaine requête.','ok');}
        catch(e){box.querySelector('#sys-err').textContent=e.message;save.disabled=false;}
      };
      const status=box.querySelector('#sys-status');if(status)status.onclick=async()=>{
        if(!confirm(u.super_administrateur?`Retirer l’accès global de ${u.email} ? Ses rôles et limites de module redeviendront applicables.`:`Donner à ${u.email} la gestion des utilisateurs et des permissions, sans accès aux opérations des sociétés ?`))return;
        status.disabled=true;
        try{await api('/systeme/utilisateurs/'+id+'/statut',{method:'POST',body:{revision:u.revision,super_administrateur:!u.super_administrateur}});closeModal();await ouvrir();toast('Statut mis à jour.','ok');}
        catch(e){box.querySelector('#sys-err').textContent=e.message;status.disabled=false;}
      };
    }catch(e){toast(e.message,'ko');}
  }
  function motDePasse(obligatoire){
    root().innerHTML=`<div class="card sys-pad sys-password"><h2>${obligatoire?'Sécurisez votre nouveau compte':'Changer mon mot de passe'}</h2><p>${obligatoire?'Le mot de passe provisoire doit être remplacé avant de gérer le système.':'Choisissez un mot de passe réservé à ce compte.'}</p><form id="sys-password-form"><label>Mot de passe actuel<input type="password" class="form-input" id="sys-old" autocomplete="current-password" required></label><label>Nouveau mot de passe<input type="password" class="form-input" id="sys-new" minlength="12" autocomplete="new-password" required></label><label>Confirmer le nouveau mot de passe<input type="password" class="form-input" id="sys-confirm" minlength="12" autocomplete="new-password" required></label><p class="muted">12 caractères minimum. Utilisez une phrase de passe unique.</p><p class="err" id="sys-password-error" role="alert"></p><button class="btn btn-primary" type="submit">Enregistrer mon mot de passe</button></form></div>`;
    root().querySelector('#sys-password-form').onsubmit=async e=>{
      e.preventDefault();const error=root().querySelector('#sys-password-error'),nouveau=root().querySelector('#sys-new').value;
      if(nouveau!==root().querySelector('#sys-confirm').value){error.textContent='Les deux nouveaux mots de passe sont différents.';return;}
      const button=e.target.querySelector('button');button.disabled=true;
      try{const result=await api('/systeme/mot-de-passe',{method:'POST',body:{ancien:root().querySelector('#sys-old').value,nouveau}});token=result.access_token;localStorage.setItem('kh_token',token);await boot();toast('Mot de passe remplacé.','ok');}
      catch(err){error.textContent=err.message;button.disabled=false;}
    };
  }
  return {init,ouvrir,autorise};
})();
