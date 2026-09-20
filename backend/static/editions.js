/* Une présentation commune aux pièces commerciales, RH, caisse et rapports. */
const Editions=(()=>{
  const plain=html=>{const doc=new DOMParser().parseFromString(String(html||''),'text/html');return doc.body.textContent||'';};
  function convertir(html){
    const doc=new DOMParser().parseFromString(html,'text/html');doc.querySelectorAll('script,style,button,input,select,textarea').forEach(x=>x.remove());
    const blocs=[];
    const text=node=>[...node.childNodes].map(n=>n.nodeType===3?n.textContent:n.nodeName==='BR'?'\n':text(n)).join(' ').replace(/[\t ]+/g,' ').trim();
    const walk=node=>{
      if(node.nodeType===3){if(node.textContent.trim())blocs.push({type:'texte',texte:node.textContent.trim()});return;}
      if(node.tagName==='TABLE'){
        const rows=[...node.rows].map(r=>[...r.cells].flatMap(c=>[text(c),...Array(Math.max(0,c.colSpan-1)).fill('')]));if(!rows.length)return;
        const max=Math.max(...rows.map(r=>r.length));rows.forEach(r=>{while(r.length<max)r.push('');});
        const hasHeader=!!node.querySelector('thead,th');
        blocs.push({type:'table',colonnes:hasHeader?rows.shift():Array.from({length:max},(_,i)=>i===0?'Rubrique':'Détail '+i),lignes:rows});return;
      }
      if(node.matches('.sign,.sigs,.signatures')){blocs.push({type:'signatures',texte:[...node.children].map(text).join('     |     ')});return;}
      if(node.matches('.tot,.total-bar,.montant,.total,.tots')){blocs.push({type:'total',texte:text(node)});return;}
      if(node.matches('h1,h2,h3,h4')){blocs.push({type:'titre',texte:text(node)});return;}
      if(node.matches('p,.sub,.row,.sig,.meta,.pied,li')||!node.querySelector('table,div,p,h1,h2,h3,h4,li')){
        const t=text(node);if(t)blocs.push({type:'texte',texte:t});return;
      }
      [...node.childNodes].forEach(walk);
    };
    [...doc.body.childNodes].forEach(walk);
    return {titre:doc.title||'Document',sous_titre:'',blocs};
  }
  function tableau(titre,sousTitre,colonnes,lignes,pied=''){
    return afficher({titre,sous_titre:sousTitre,blocs:[{type:'table',colonnes,lignes},...(pied?[{type:'texte',texte:plain(pied)}]:[])]});
  }
  function piece({titre,numero,meta=[],client,clientLabel='Client',colonnes,lignes,totaux=[],mentions,signatures=[]}){
    return afficher({titre:titre+' · '+numero,sous_titre:meta.map(([k,v])=>k+' : '+v).join(' · '),blocs:[
      {type:'texte',texte:clientLabel+' : '+(client||'Non renseigné')},
      {type:'table',colonnes:colonnes.map(c=>c.t),lignes:lignes.map(r=>r.map(plain))},
      ...(totaux||[]).map(t=>({type:t.grand?'total':'texte',texte:t.l+' : '+plain(t.v)})),
      ...(mentions?[{type:'texte',texte:plain(mentions)}]:[]),
      ...(signatures?.length?[{type:'signatures',texte:signatures.join(' | ')}]:[])]});
  }
  function fenetre(titre=''){
    let contenu='',ouvert=false;const sid=currentSocieteId;
    return {document:{write:v=>{contenu+=v;},close:()=>{}},focus:()=>{},print:()=>{
      if(ouvert)return;ouvert=true;if(sid!==currentSocieteId){toast('La société a changé. Rouvrez le document.','ko');return;}
      const spec=convertir(contenu);if(titre)spec.titre=titre;afficher(spec,sid);
    }};
  }
  function body(spec){return spec.blocs.map(b=>b.type==='table'?`<div class="edition-table-scroll"><table><thead><tr>${b.colonnes.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${b.lignes.map(r=>`<tr${/^(total|net à payer|résultat|solde)/i.test(String(r[0]))?' class="edition-summary-row"':''}>${r.map(v=>`<td${typeof v==='number'||/^[-+\d\s.,]+(?: USD| CDF| %)?$/.test(String(v))?' class="numeric"':''}>${esc(typeof v==='number'?fmtNum(v):(v??''))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:
    b.type==='titre'?`<h3>${esc(b.texte)}</h3>`:b.type==='signatures'?`<div class="edition-signatures">${b.texte.split('|').map(t=>`<div>${esc(t.trim())}<small>Nom, date et signature</small></div>`).join('')}</div>`:`<p class="${b.type==='total'?'edition-total':''}">${esc(b.texte)}</p>`).join('');}
  async function telecharger(spec,format,sid=currentSocieteId,bouton){
    if(sid!==currentSocieteId){toast('La société a changé. Rouvrez le document.','ko');return;}
    if(bouton)bouton.disabled=true;
    try{
      const r=await fetch(`${API}/editions/telecharger?societe_id=${sid}`,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({...spec,format})});
      if(!r.ok){let d;try{d=await r.json();}catch{}throw new Error(typeof d?.detail==='string'?d.detail:'Le document ne peut pas être exporté. Vérifiez vos accès et le contenu.');}
      if(sid!==currentSocieteId||!token)throw new Error('Session ou société modifiée. Rouvrez le document.');
      const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download=spec.titre.replace(/[<>:"/\\|?*]/g,' ').slice(0,100)+'.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
      toast(format.toUpperCase()+' téléchargé.','ok');
    }catch(e){toast(e.message,'ko');}finally{if(bouton)bouton.disabled=false;}
  }
  async function afficher(original,sid=currentSocieteId){
    try{
      const soc=await api(`/editions/societe?societe_id=${sid}`);if(sid!==currentSocieteId)return;
      const spec={...original,blocs:original.blocs.filter((b,i)=>!(i===0&&b.type==='titre'&&b.texte.trim()===soc.nom.trim()))};
      const landscape=spec.blocs.some(b=>b.type==='table'&&b.colonnes.length>7);
      const content=`<article class="edition-page ${landscape?'edition-landscape':''}"><header class="edition-header"><div><span class="edition-mark"></span><strong>${esc(soc.nom)}</strong>${soc.ville?`<span>${esc(soc.ville)}</span>`:''}</div><span>Édité le ${new Date().toLocaleDateString('fr-FR')}</span></header><h1>${esc(spec.titre)}</h1>${spec.sous_titre?`<p class="edition-sub">${esc(spec.sous_titre)}</p>`:''}${body(spec)}<footer>${esc(soc.references||soc.nom)}</footer></article>`;
      modal({wide:true,title:'Aperçu du document',body:`<p class="edition-tools-note">Contrôlez le document avant diffusion. Le PDF téléchargé est paginé ; le classeur Excel conserve les tableaux et leurs filtres.</p><div class="edition-preview">${content}</div>`,footer:'<button class="btn" data-ed-close>Fermer</button><button class="btn" data-ed-xlsx>Excel (.xlsx)</button><button class="btn" data-ed-print>Imprimer</button><button class="btn btn-primary" data-ed-pdf>Télécharger le PDF</button>'});
      const root=$('#modal-root').lastElementChild;root.classList.add('edition-modal');
      root.querySelector('[data-ed-close]').onclick=closeModal;
      root.querySelector('[data-ed-pdf]').onclick=e=>telecharger(spec,'pdf',sid,e.currentTarget);
      root.querySelector('[data-ed-xlsx]').onclick=e=>telecharger(spec,'xlsx',sid,e.currentTarget);
      root.querySelector('[data-ed-print]').onclick=()=>{
        const w=window.open('','_blank','width=1000,height=900');if(!w){toast('Autorisez la fenêtre d’impression ou téléchargez le PDF.','ko');return;}
        w.document.write(`<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>${esc(spec.titre)}</title><link rel="stylesheet" href="/static/editions.css?v=1"><style>@page{size:A4 ${landscape?'landscape':'portrait'}}</style></head><body>${content}</body></html>`);w.onload=()=>{w.focus();w.print();};w.document.close();
      };
    }catch(e){toast(e.message,'ko');}
  }
  function excel(nom,colonnes,lignes,sousTitre){return telecharger({titre:nom.replace(/\.(csv|xls|xlsx)$/i,'').replace(/_/g,' '),sous_titre:sousTitre??TITLES[activeView]?.[0]??'',blocs:[{type:'table',colonnes,lignes}]},'xlsx');}
  return {fenetre,tableau,excel,convertir,piece};
})();
