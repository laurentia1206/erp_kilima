/* Inventaires et préparation mensuelle TVA. Les écritures restent côté Django. */
const Clotures = (() => {
  let moisInv='', depotFiltre='', socInv='', moisTva='', tvaDirty=false;
  const moisCourant=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;};
  const statut=i=>i.statut==='brouillon'?'À valider':i.statut==='annule'?'Annulé':'Validé';
  const euros=n=>`${fmtNum(n)} $`;
  const compteur=(titre,valeur,sous='')=>`<div class="kpi-card"><div class="kpi-label">${titre}</div><div class="kpi-val">${valeur}</div><div class="kpi-sub">${sous}</div></div>`;
  function confirmLeave(){if(!tvaDirty)return true;if(!confirm('Le dossier TVA contient des changements non enregistrés. Les abandonner ?'))return false;tvaDirty=false;return true;}
  function init(){
    NAV.find(g=>g.g==='Stock').items.splice(2,0,{v:'inventaires',l:'Inventaires & écarts',i:'ti-clipboard-check'});
    NAV.find(g=>g.g==='Comptabilité').items.splice(3,0,{v:'tva',l:'Déclarations TVA',i:'ti-percentage'});
    TITLES.inventaires=['Inventaires & écarts','Comptage physique, validation et suivi des ajustements'];
    TITLES.tva=['Déclarations TVA','Dossier mensuel par société · préparation et suivi du dépôt'];
    RENDER.inventaires=inventaires; RENDER.tva=tva;
  }
  async function inventaires(){
    moisInv ||= moisCourant();
    if(socInv!==currentSocieteId){depotFiltre='';socInv=currentSocieteId;}
    const el=$('#view-inventaires');el.innerHTML='<p class="muted">Chargement…</p>';
    const [depots,rows]=await Promise.all([api(`/stock/depots?societe_id=${currentSocieteId}`),api(`/stock/inventaires?societe_id=${currentSocieteId}&mois=${moisInv}`)]);
    const visibles=rows.filter(i=>!depotFiltre||i.depot_id===depotFiltre),valides=visibles.filter(i=>i.statut==='valide');
    const lignes=valides.flatMap(i=>i.lignes),manquants=lignes.reduce((n,l)=>n+Math.max(0,-l.ecart_valeur),0),excedents=lignes.reduce((n,l)=>n+Math.max(0,l.ecart_valeur),0);
    el.innerHTML=`<div class="banner">1. Saisir le comptage physique · 2. Vérifier les écarts · 3. Faire valider par le comptable ou le DFI.<br>Le stock change uniquement à la validation. En cuisine, générez les consommations théoriques de la période avant le comptage.</div>
      <div class="period-toolbar"><div class="form-group"><label class="form-label" for="inv-mois">Mois</label><input class="form-input" id="inv-mois" type="month" value="${moisInv}"></div>
      <div class="form-group"><label class="form-label" for="inv-depot">Dépôt</label><select class="form-select" id="inv-depot"><option value="">Tous les dépôts</option>${depots.map(d=>`<option value="${d.id}" ${d.id===depotFiltre?'selected':''}>${esc(d.libelle)}</option>`).join('')}</select></div><div class="form-group"><label class="form-label">Comptage physique</label><button class="btn btn-primary" id="inv-nouveau">Nouveau comptage</button></div></div>
      <div class="kpi-row">${compteur('À valider',visibles.filter(i=>i.statut==='brouillon').length)}${compteur('Manquants validés',euros(manquants))}${compteur('Excédents validés',euros(excedents))}${compteur('Inventaires validés',valides.length,'Périmètre : articles effectivement comptés')}</div>
      <div class="card" style="margin-top:16px"><div class="card-body">${!visibles.length?'<p class="muted">Aucun inventaire pour cette période et ce dépôt.</p>':`<div style="overflow:auto"><table><thead><tr><th>N°</th><th>Date</th><th>Dépôt</th><th>État</th><th>Écart $</th><th>Pièce comptable</th><th></th></tr></thead><tbody>${visibles.map(i=>`<tr><td>${esc(i.numero)}</td><td>${i.date}</td><td>${esc(i.depot)}</td><td>${statut(i)}</td><td>${fmtNum(i.ecart_valeur)}</td><td>${i.ecriture?`${esc(i.ecriture)} · ${esc(i.statut_comptable)}`:i.statut==='brouillon'?'Après validation':'—'}</td><td><button class="btn btn-sm" data-inv="${i.id}">Voir / contrôler</button></td></tr>`).join('')}</tbody></table></div>`}</div></div>`;
    $('#inv-mois').onchange=e=>{if(e.target.value){moisInv=e.target.value;inventaires();}};
    $('#inv-depot').onchange=e=>{depotFiltre=e.target.value;inventaires();};
    $('#inv-nouveau').onclick=()=>{
      if(!depots.length){toast('Créez un dépôt avant le comptage.','ko');return;}
      if(depotFiltre){comptage(depots.find(d=>d.id===depotFiltre),inventaires);return;}
      modal({title:'Choisir le dépôt à compter',body:`<select class="form-select" id="inv-choix">${depots.map(d=>`<option value="${d.id}">${esc(d.libelle)}</option>`).join('')}</select>`,footer:'<button class="btn btn-primary" id="inv-ouvrir">Commencer</button>'});
      $('#inv-ouvrir').onclick=()=>{const d=depots.find(d=>d.id===$('#inv-choix').value);closeModal();comptage(d,inventaires);};
    };
    el.querySelectorAll('[data-inv]').forEach(b=>b.onclick=()=>detail(visibles.find(i=>i.id===b.dataset.inv)));
  }
  function detail(i){
    const approbateur=has('DFI','COMPTABLE'),annulable=approbateur||i.created_by===me.id;
    modal({wide:true,title:`${i.numero} — ${statut(i)}`,body:`<p>${esc(i.depot)} · ${i.date} · ${i.lignes.length} article(s) compté(s)</p><div class="banner">${i.statut==='brouillon'?'Comptage préparé : aucun ajustement du stock ni écriture comptable pour le moment.':i.statut==='annule'?'Comptage annulé : aucun ajustement.':`Stock ajusté. ${i.ecriture?'Pièce '+esc(i.ecriture)+' · '+esc(i.statut_comptable):'Aucune écriture monétaire nécessaire.'}`}</div>
      ${i.lignes.some(l=>Number(l.cump)===0&&Number(l.ecart_qte)!==0)?'<p class="err">Attention : un écart est valorisé à coût moyen nul. Vérifiez sa valorisation avant de valider.</p>':''}<div style="overflow:auto"><table><thead><tr><th>Article</th><th>Théorique</th><th>Compté</th><th>Écart qté</th><th>Coût moyen $</th><th>Écart $</th></tr></thead><tbody>${i.lignes.map(l=>`<tr><td>${esc(l.code)} — ${esc(l.designation)} (${esc(l.unite||'')})</td><td>${fmtNum(l.qte_theorique)}</td><td>${fmtNum(l.qte_reelle)}</td><td>${fmtNum(l.ecart_qte)}</td><td>${fmtNum(l.cump)}</td><td>${fmtNum(l.ecart_valeur)}</td></tr>`).join('')}</tbody></table></div><p>${esc(i.note||'')}</p><p class="err" id="inv-erreur" role="alert"></p>`,footer:`<button class="btn" id="inv-imprimer">Imprimer</button>${i.statut==='brouillon'&&annulable?'<button class="btn" id="inv-annuler">Annuler ce comptage</button>':''}${i.statut==='brouillon'&&approbateur?'<button class="btn btn-primary" id="inv-valider">Valider et ajuster le stock</button>':''}`});
    $('#inv-imprimer').onclick=()=>imprimerRapport(`Inventaire ${i.numero} — ${statut(i)}`,`${esc(i.depot)} · ${i.date}`,
      ['Article','Théorique','Compté','Écart qté','Coût moyen $','Écart $'],i.lignes.map(l=>[esc(l.code+' — '+l.designation),fmtNum(l.qte_theorique),fmtNum(l.qte_reelle),fmtNum(l.ecart_qte),fmtNum(l.cump),fmtNum(l.ecart_valeur)]),`Écart : ${fmtNum(i.ecart_valeur)} USD · ${esc(i.note||'')}`);
    const decider=async action=>{
      if(!confirm(action==='valider'?'Valider ce comptage ? Les écarts ajusteront le stock et généreront la pièce comptable correspondante.':'Annuler ce comptage préparé sans modifier le stock ?'))return;
      const buttons=[...document.querySelectorAll('#inv-valider,#inv-annuler')];buttons.forEach(b=>b.disabled=true);
      try{await api(`/stock/inventaires/${i.id}/decision`,{method:'POST',body:{action}});closeModal();toast(action==='valider'?'Inventaire validé et stock ajusté.':'Comptage annulé.','ok');inventaires();}
      catch(e){$('#inv-erreur').textContent=e.message;buttons.forEach(b=>b.disabled=false);}
    };
    if($('#inv-valider'))$('#inv-valider').onclick=()=>decider('valider');
    if($('#inv-annuler'))$('#inv-annuler').onclick=()=>decider('annuler');
  }
  async function comptage(depot,refresh){
    const sid=currentSocieteId;
    const etat=await api(`/stock/depots-etat?societe_id=${sid}&depot_id=${depot.id}&inventaire=1`);
    const rows=[...etat.articles],catalogue=etat.catalogue||[];
    modal({wide:true,title:`Comptage — ${depot.libelle}`,body:`<div class="banner">Saisissez les quantités réellement comptées. Zéro signifie qu’aucune unité n’a été trouvée ; un champ vide n’est pas un comptage.<br>Ce document sera soumis au comptable/DFI. Il ne modifie pas encore le stock.</div>
      <div style="overflow:auto"><table><thead><tr><th>Article</th><th>Théorique</th><th>Coût moyen $</th><th>Compté</th><th>Écart $</th></tr></thead><tbody id="iv-lignes"></tbody></table></div>
      <div class="form-row"><select class="form-select" id="iv-ajout" aria-label="Ajouter un article trouvé hors du stock théorique"><option value="">Article trouvé non présent ci-dessus…</option>${catalogue.map(a=>`<option value="${a.article_id}">${esc(a.code)} — ${esc(a.designation)}</option>`).join('')}</select><button class="btn" id="iv-ajouter">Ajouter au comptage</button></div>
      <p id="iv-total" class="catalogue-scope" aria-live="polite"></p><div class="form-group"><label class="form-label">Note du compteur / explications des écarts</label><textarea class="form-input" id="iv-note" maxlength="255"></textarea></div><div class="err" id="iv-erreur" role="alert"></div>`,footer:'<button class="btn" onclick="closeModal()">Fermer</button><button class="btn btn-primary" id="iv-ok">Enregistrer le comptage à valider</button>'});
    const root=document.querySelector('#modal-root').lastElementChild;
    const ajouter=a=>{const tr=document.createElement('tr');tr.innerHTML=`<td>${esc(a.code)} — ${esc(a.designation)}<div class="muted">${esc(a.unite||'')}</div></td><td>${fmtNum(a.qte)}</td><td>${fmtNum(a.cump)}</td><td><input class="form-input iv-reel" style="min-width:110px" aria-label="Quantité comptée ${esc(a.code)}" data-art="${a.article_id}" type="number" min="0" step="0.001" placeholder="À compter"></td><td class="iv-ecart">—</td>`;root.querySelector('#iv-lignes').append(tr);};
    rows.forEach(ajouter);
    const totals=()=>{let manquants=0,excedents=0,n=0;root.querySelectorAll('.iv-reel').forEach(input=>{const a=rows.find(a=>a.article_id===input.dataset.art),reel=Number(input.value),ok=input.value.trim()!==''&&Number.isFinite(reel)&&reel>=0;const ecart=(reel-a.qte)*a.cump;input.closest('tr').querySelector('.iv-ecart').textContent=ok?fmtNum(ecart):'—';if(ok){n++;manquants+=Math.max(0,-ecart);excedents+=Math.max(0,ecart);}});root.querySelector('#iv-total').textContent=`${n}/${rows.length} article(s) compté(s) · Manquants estimés ${fmtNum(manquants)} $ · Excédents estimés ${fmtNum(excedents)} $`;
      root.querySelector('#iv-ok').disabled=!rows.length||n!==rows.length;};
    root.querySelector('#iv-lignes').addEventListener('input',totals);totals();
    root.querySelector('#iv-ajouter').onclick=()=>{const a=catalogue.find(a=>a.article_id===root.querySelector('#iv-ajout').value);if(!a)return;if(rows.some(r=>r.article_id===a.article_id)){root.querySelector('#iv-erreur').textContent='Cet article figure déjà dans le comptage.';return;}rows.push(a);ajouter(a);totals();};
    root.querySelector('#iv-ok').onclick=async()=>{
      const b=root.querySelector('#iv-ok');if(b.disabled)return;b.disabled=true;
      try{const lignes=[...root.querySelectorAll('.iv-reel')].map(input=>({article_id:input.dataset.art,qte_reelle:Number(input.value),qte_theorique:rows.find(a=>a.article_id===input.dataset.art).qte}));await api(`/stock/inventaires?societe_id=${sid}`,{method:'POST',body:{depot_id:depot.id,lignes,note:root.querySelector('#iv-note').value}});closeModal();toast('Comptage enregistré : stock inchangé, validation comptable/DFI requise.','ok');refresh();}
      catch(e){root.querySelector('#iv-erreur').textContent=e.message;b.disabled=false;}
    };
  }
  async function tva(){
    moisTva ||= moisCourant();const el=$('#view-tva');el.innerHTML='<p class="muted">Chargement…</p>';
    const endpoint=`/comptabilite/tva-mensuelle`,query=`?societe_id=${currentSocieteId}&mois=${moisTva}`;
    const [r,dossier]=await Promise.all([api(endpoint+query),api(endpoint+'/dossier'+query)]);const d=dossier.donnees;
    const tot=r.totaux.valide,att=r.totaux.en_attente;tvaDirty=false;
    el.innerHTML=`<div class="banner"><b>RDC · dossier préparatoire mensuel</b><br>${esc(r.note)}<br>Le dossier est conservé dans l’ERP ; le dépôt officiel s’effectue auprès de la DGI.</div>
      <div class="period-toolbar"><div class="form-group"><label class="form-label" for="tva-mois">Mois de déclaration</label><input id="tva-mois" class="form-input" type="month" value="${moisTva}"></div><div class="form-group"><label class="form-label">État du dossier</label><p id="tva-etat">${dossier.revision?`Enregistré · version ${dossier.revision}${d.reference_depot?' · dépôt renseigné':''}`:'À préparer'}</p></div><button class="btn" id="tva-print">Imprimer l’état courant</button><button class="btn" id="tva-csv">Exporter les lignes (CSV)</button><button class="btn" id="tva-snapshot" ${d.etat?'':'disabled'}>Imprimer l’état enregistré</button></div>
      <div class="kpi-row">${compteur('TVA collectée · écritures validées',euros(tot.collectee))}${compteur('TVA déductible comptabilisée',euros(tot.deductible),'Droit à déduction à vérifier')}${compteur('Solde des mouvements TVA',euros(r.solde_mouvements_usd),'Hors qualification fiscale et crédit antérieur')}</div>
      <p class="catalogue-scope">Pièces non validées, exclues des indicateurs : collectée ${euros(att.collectee)} · déductible ${euros(att.deductible)}. Comptes suivis : ${esc(r.comptes.collectee)} / ${esc(r.comptes.deductible)} et leurs subdivisions.</p>
      <div class="card"><div class="card-hdr"><b>Factures commerciales et frais — ventilation par taux enregistré</b></div><div class="card-body"><p class="muted">Les avoirs diminuent les montants. Les opérations sans TVA restent à qualifier (exonération, taux zéro…). Cette ventilation ne remplace pas le contrôle de toutes les écritures, notamment les autres modules et régularisations.</p><table><thead><tr><th>Opérations</th><th>Taux</th><th>Base HT $</th><th>TVA $</th></tr></thead><tbody>${r.ventilation_taux.map(v=>`<tr><td>${v.sens==='achats'?'Achats':'Ventes'}</td><td>${Number(v.taux)===0?'Sans TVA — à qualifier':fmtNum(v.taux)+' %'}</td><td>${fmtNum(v.ht_usd)}</td><td>${fmtNum(v.tva_usd)}</td></tr>`).join('')||'<tr><td colspan="4">Aucune ligne commerciale pour ce mois.</td></tr>'}</tbody></table></div></div>
      <div class="card" style="margin-top:16px"><div class="card-hdr"><b>Notes, contrôles et suivi du dépôt</b></div><div class="card-body"><p class="muted">Renseignez les montants de la déclaration vérifiée en CDF. Aucune conversion USD/CDF ni déductibilité n’est présumée par le logiciel.</p><div class="form-row"><div class="form-group"><label class="form-label">Crédit antérieur vérifié (CDF)</label><input class="form-input" type="number" min="0" step="0.01" id="tva-credit" value="${esc(d.credit_anterieur_cdf||'')}"></div><div class="form-group"><label class="form-label">Montant déclaré à payer (CDF)</label><input class="form-input" type="number" min="0" step="0.01" id="tva-montant" value="${esc(d.montant_declare_cdf||'')}"></div></div><div class="form-row"><div class="form-group"><label class="form-label">Référence du dépôt déjà effectué</label><input class="form-input" id="tva-ref" value="${esc(d.reference_depot||'')}"></div><div class="form-group"><label class="form-label">Date du dépôt</label><input class="form-input" type="date" id="tva-date" value="${esc(d.date_depot||'')}"></div></div><div class="form-group"><label class="form-label">Justificatifs contrôlés, exonérations, régularisations et conversion retenue</label><textarea class="form-input" id="tva-notes" rows="4" maxlength="10000">${esc(d.notes||'')}</textarea></div><p class="err" id="tva-erreur" role="alert"></p><button class="btn btn-primary" id="tva-save">Enregistrer le dossier et l’état courant</button><p class="muted" id="tva-save-info">${dossier.updated_at?'Dernière sauvegarde : '+esc(dossier.updated_at):'Aucun dossier enregistré pour ce mois.'}</p></div></div>
      <details class="card" style="margin-top:16px"><summary class="card-hdr">Écritures TVA du mois (${r.lignes.length})</summary><div class="card-body" style="overflow:auto"><table><thead><tr><th>Date</th><th>Pièce</th><th>Référence</th><th>Compte</th><th>Sens</th><th>Montant $</th><th>État</th></tr></thead><tbody>${r.lignes.map(l=>`<tr><td>${l.date}</td><td>${esc(l.piece)}</td><td>${esc(l.reference)}</td><td>${esc(l.compte)}</td><td>${l.sens}</td><td>${fmtNum(l.montant_usd)}</td><td>${esc(l.statut)}</td></tr>`).join('')}</tbody></table></div></details>`;
    let revision=dossier.revision,etatSauve=d.etat;
    el.querySelectorAll('#tva-credit,#tva-montant,#tva-ref,#tva-date,#tva-notes').forEach(input=>input.addEventListener('input',()=>{tvaDirty=true;}));
    $('#tva-mois').onchange=e=>{if(e.target.value){if(!confirmLeave()){e.target.value=moisTva;return;}moisTva=e.target.value;tva();}};
    const imprimer=(etat,titre)=>imprimerRapport(`TVA ${etat.mois} — ${titre}`,esc(etat.note),['Date','Pièce','Compte','Sens','Montant USD','État'],etat.lignes.map(l=>[l.date,esc(l.piece),esc(l.compte),l.sens,fmtNum(l.montant_usd),esc(l.statut)]),`Collectée validée : ${fmtNum(etat.totaux.valide.collectee)} USD · Déductible comptabilisée : ${fmtNum(etat.totaux.valide.deductible)} USD. Document de préparation, pas un récépissé DGI.`);
    $('#tva-print').onclick=()=>imprimer(r,'état courant');if($('#tva-snapshot'))$('#tva-snapshot').onclick=()=>imprimer(etatSauve,'état enregistré');
    $('#tva-csv').onclick=()=>{const csv=ModuleUX.toCSV(['Date','Pièce','Référence','Compte','Sens','Montant USD','État'],r.lignes.map(l=>[l.date,l.piece,l.reference,l.compte,l.sens,l.montant_usd,l.statut]));const u=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download=`TVA-${moisTva}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
    $('#tva-save').onclick=async()=>{const b=$('#tva-save');if(b.disabled)return;b.disabled=true;try{const saved=await api(endpoint+'/dossier'+query,{method:'POST',body:{revision,notes:$('#tva-notes').value,credit_anterieur_cdf:$('#tva-credit').value,montant_declare_cdf:$('#tva-montant').value,reference_depot:$('#tva-ref').value,date_depot:$('#tva-date').value}});revision=saved.revision;etatSauve=saved.donnees.etat;tvaDirty=false;$('#tva-snapshot').disabled=false;$('#tva-etat').textContent=`Enregistré · version ${revision}${saved.donnees.reference_depot?' · dépôt renseigné':''}`;$('#tva-save-info').textContent=`Dossier enregistré — version ${revision}. Aucun dépôt ni paiement transmis à la DGI.`;toast('Dossier TVA enregistré.','ok');}catch(e){$('#tva-erreur').textContent=e.message;}finally{b.disabled=false;}};
  }
  return {init,comptage,confirmLeave};
})();
