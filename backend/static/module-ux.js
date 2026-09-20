/* Outils de consultation uniquement : aucun changement aux circuits/API métier. */
"use strict";
const ModuleUX = (() => {
  const normalize = (value) => String(value ?? "").normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
  const collator = new Intl.Collator("fr", {numeric:true, sensitivity:"base"});
  const text = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function csvCell(value) {
    let s = String(value ?? "");
    // Un libellé exporté ne doit pas être interprété comme une formule Excel.
    if (/^[\s\uFEFF]*[=+@-]/.test(s) && !/^-?\d+(?:[.,]\d+)?$/.test(s.trim())) s = "'" + s;
    return '"' + s.replace(/"/g, '""') + '"';
  }
  function toCSV(headers, rows) {
    return "\uFEFF" + [headers, ...rows].map(row => row.map(csvCell).join(";")).join("\r\n");
  }
  function compare(a, b, numeric = false) {
    if (numeric) {
      const number = v => {
        const s = String(v).replace(/[\s\u00a0\u202f]/g, "").replace(",", ".");
        const match = s.match(/^[−-]?\d+(?:\.\d+)?/);
        return match ? Number(match[0].replace("−", "-")) : null;
      };
      const x = number(a), y = number(b);
      if (x !== null && y !== null) return x - y;
    }
    return collator.compare(String(a), String(b));
  }
  function selectRows(rows, query, status) {
    const words = normalize(query).split(/\s+/).filter(Boolean);
    return rows.filter(r => (!status || r.status === status) && words.every(w => r.search.includes(w)));
  }
  const groups = [
    {name:"Demandes & validations", views:["requisitions","nouvelle-req","approbation"],
      purpose:"Retrouvez la demande, son avancement et les échanges avant d'agir.",
      tip:"Une demande validée passe ensuite à l'ordre de dépense. Les précisions demandées se répondent depuis la réquisition.", links:["requisitions","approbation","ordres"]},
    {name:"Décaissements & avances", views:["ordres","avances","caisse-exec"],
      purpose:"Suivez les autorisations de paiement et les avances restant à justifier.",
      tip:"Un ordre autorise la sortie de fonds ; une avance conserve son échéance de justification. Le paiement direct suit son circuit existant.", links:["ordres","avances","caisse"]},
    {name:"Trésorerie", views:["caisse","transferts"],
      purpose:"Gardez le lien entre les sessions de caisse, leurs mouvements et les transferts.",
      tip:"Vérifiez la caisse et la devise sélectionnées. Les soldes du journal suivent l'ordre chronologique des mouvements.", links:["caisse","transferts","rapprochement"]},
    {name:"Point de vente", views:["pos","tarifs-pos"],
      purpose:"Préparez les articles et les tarifs du point de vente avant l'encaissement.",
      tip:"Contrôlez le point de vente, le client et les modes de règlement dans le panier. Les tarifs et les dépôts restent définis par vos réglages.", links:["pos","tarifs-pos","articles"]},
    {name:"Achats", views:["commandes","receptions","achats"],
      purpose:"Suivez la commande fournisseur, la réception physique et la facture.",
      tip:"La commande, les quantités reçues et la facture sont des étapes distinctes. Utilisez le document d'origine pour poursuivre le circuit.", links:["commandes","receptions","achats","stock"]},
    {name:"Ventes", views:["devis","ventes","rapports-commercial"],
      purpose:"Retrouvez le client, l'avancement de la livraison et les règlements.",
      tip:"Passez du devis à la commande, puis aux livraisons et à la facture selon le circuit existant. Les ventes et les encaissements ne représentent pas le même indicateur.", links:["devis","ventes","rapports-commercial"]},
    {name:"Stocks & dépôts", views:["stock","depots","articles"],
      purpose:"Consultez les quantités, leur valeur et les mouvements par dépôt.",
      tip:"Le coût moyen pondéré valorise le stock. Un transfert déplace des quantités entre dépôts ; l'inventaire compare le physique au théorique.", links:["stock","depots","articles"]},
    {name:"Transport", views:["courses","flotte","contrats-transport","config-transport"],
      purpose:"Gardez le fil entre les courses, les camions et les contrats.",
      tip:"La fiche de course rassemble les étapes de validation, départ, arrivée et retour. Les coûts et la facturation restent associés au circuit existant.", links:["courses","flotte","contrats-transport","carburant"]},
    {name:"Location d'engins", views:["engins-parc","engins-heures","engins-rpe","config-engins"],
      purpose:"Passez du parc aux heures prestées, puis au relevé mensuel.",
      tip:"Vérifiez la période et l'engin avant de saisir des heures ou d'examiner le RPE. Les forfaits et tarifs restent ceux de votre configuration.", links:["engins-parc","engins-heures","engins-rpe"]},
    {name:"Maintenance & documents", views:["maintenance-parc","maintenance-interventions","flotte-documents","config-maintenance"],
      purpose:"Repérez les échéances et retrouvez l'intervention du véhicule concerné.",
      tip:"Les états et seuils affichés proviennent des plans existants. Une intervention et un document administratif ont des échéances distinctes.", links:["maintenance-parc","maintenance-interventions","flotte-documents"]},
    {name:"Carburant", views:["carburant"],
      purpose:"Comparez les pleins, l'usage et la consommation de chaque véhicule.",
      tip:"Vérifiez la période et l'unité : litres aux 100 km pour les camions, litres à l'heure pour les engins. L'écart dépend des relevés enregistrés.", links:["carburant","courses","engins-heures"]},
    {name:"Hôtel", views:["hotel-reception","hotel-chambres","config-hotel"],
      purpose:"Visualisez les séjours et préparez les chambres pour les prochaines arrivées.",
      tip:"Le planning affiche les réservations de la période choisie. Les indicateurs du jour et du mois gardent leur période propre. Ouvrez un séjour pour consulter sa note.", links:["hotel-reception","hotel-chambres","cuisine"]},
    {name:"Cuisine", views:["cuisine"],
      purpose:"Lisez les fiches recettes, leurs coûts et les consommations théoriques.",
      tip:"Le coût théorique repose sur les fiches et les ventes enregistrées. Comparez-le au comptage physique des dépôts pour examiner les écarts.", links:["cuisine","depots","pos"]},
    {name:"Opérations intersociétés", views:["intersociete"],
      purpose:"Rapprochez les deux côtés d'une opération et suivez ses documents liés.",
      tip:"Les positions concernent des sociétés distinctes. Vérifiez les documents d'origine et les réceptions avant d'interpréter un écart.", links:["intersociete","commandes","devis","courses"]},
    {name:"Comptabilité & pilotage", views:["dashboard","compta","balance","grand-livre","saisie-od","plan-comptable","lettrage","rapprochement","analytique","cockpit","etats"],
      purpose:"Retrouvez la pièce d'origine et vérifiez la société, la période et les comptes.",
      tip:"Les pièces en attente suivent la validation comptable existante. Les états et leurs totaux portent sur les critères propres à chaque rapport.", links:["compta","grand-livre","balance","cockpit"]},
    {name:"Administration & paramètres", views:["administration","config","taux"],
      purpose:"Consultez les sociétés, les agents, les rôles et les réglages de gestion.",
      tip:"Une modification des paliers, comptes ou affectations agit sur les opérations futures. Vérifiez la société et la portée du réglage avant de l'enregistrer.", links:["administration","config","taux"]},
  ];
  const tableViews = new Set(["requisitions","ordres","avances","transferts","commandes","receptions","achats","devis","ventes","stock","depots","articles","courses","flotte","contrats-transport","engins-parc","maintenance-interventions","flotte-documents","carburant","hotel-chambres","cuisine","administration"]);
  const cardsViews = new Set(["caisse","flotte","engins-parc","maintenance-parc","depots","hotel-chambres"]);
  let sequence = 0, observer;

  function cellText(cell) {
    const copy = cell.cloneNode(true);
    copy.querySelectorAll("input,select,textarea,.ti").forEach(n => n.remove());
    return copy.textContent.replace(/\s+/g, " ").trim();
  }
  function enhanceTable(table, view) {
    if (table.dataset.uxReady || table.closest(".modal") || table.querySelector("input,select,textarea,table,tfoot,tr.tot,[colspan],[rowspan]")) return;
    const headers = [...(table.tHead?.rows[0]?.cells || [])];
    const body = table.tBodies[0], rows = [...(body?.rows || [])];
    if (headers.length < 2 || !rows.length || rows.some(r => r.cells.length !== headers.length)) return;
    table.dataset.uxReady = "true";
    const id = "list-tools-" + (++sequence);
    const titles = headers.map(h => h.textContent.trim());
    const searchable = titles.map((title,i) => title ? i : -1).filter(i => i >= 0);
    const statusIndex = titles.findIndex(h => /^(statut|avancement|etat|sens|reglement)$/i.test(normalize(h)));
    const records = rows.map((row,index) => {
      const cells = [...row.cells].map(cellText);
      const status = statusIndex < 0 ? "" : (row.cells[statusIndex].querySelector(".pill")?.textContent.trim() || cells[statusIndex]);
      return {row,index,cells,status,search:normalize(searchable.map(i => cells[i]).join(" "))};
    });
    const statuses = [...new Set(records.map(r => r.status).filter(Boolean))].sort(collator.compare);
    const card = table.closest(".card");
    const label = card?.querySelector(".card-hdr-title")?.textContent.trim() || TITLES[view]?.[0] || "Liste";
    const toolbar = document.createElement("div");
    toolbar.className = "list-tools";
    toolbar.innerHTML = `<div class="list-tools-controls"><label class="list-search"><span class="sr-only">Rechercher dans ${text(label)}</span><input type="search" class="form-input" placeholder="Rechercher dans cette liste…" /></label>
      ${statuses.length ? `<label><span class="sr-only">Filtrer par ${text(titles[statusIndex])}</span><select class="form-select list-status"><option value="">Tous les ${normalize(titles[statusIndex]) === "sens" ? "sens" : "statuts"}</option>${statuses.map(s=>`<option>${text(s)}</option>`).join("")}</select></label>` : ""}
      <button type="button" class="btn btn-sm list-reset">Réinitialiser</button><button type="button" class="btn btn-sm list-xlsx">Excel</button><button type="button" class="btn btn-sm list-pdf">PDF</button><button type="button" class="btn btn-sm list-csv" title="Exporter les lignes trouvées dans cette liste, toutes pages confondues">Exporter la sélection (CSV)</button></div>
      <div class="list-tools-caption"><span id="${id}-count" role="status" aria-live="polite"></span><span>Recherche dans la liste chargée · indicateurs inchangés</span></div>`;
    table.before(toolbar);
    const wrap = document.createElement("div"); wrap.className = "list-table-scroll";
    table.before(wrap); wrap.append(table);
    table.classList.add("managed-list");
    table.setAttribute("aria-describedby", id + "-count");
    const empty = document.createElement("div"); empty.className="list-no-result hidden";
    empty.textContent="Aucun résultat. Modifiez votre recherche ou réinitialisez les filtres.";
    wrap.after(empty);
    const pager = document.createElement("div"); pager.className="list-pagination";
    pager.innerHTML=`<label>Lignes par page <select class="form-select list-size"><option>25</option><option>50</option><option>100</option><option value="all">Toutes</option></select></label><div><button type="button" class="btn btn-sm list-prev" aria-label="Page précédente">←</button><span class="list-page"></span><button type="button" class="btn btn-sm list-next" aria-label="Page suivante">→</button></div>`;
    empty.after(pager);
    let page=1, sortIndex=-1, direction=1, filtered=records;
    const query=toolbar.querySelector("input"), status=toolbar.querySelector(".list-status"), size=pager.querySelector("select");
    function draw() {
      filtered=selectRows(records, query.value, status?.value || "");
      if(sortIndex>=0) {
        const numeric=/montant|valeur|prix|quantite|qte|cout|total|marge|^ht$|^ttc$|tva|litres|tonnage|reste|stock/.test(normalize(titles[sortIndex]));
        filtered.sort((a,b)=>direction*compare(a.cells[sortIndex],b.cells[sortIndex],numeric)||a.index-b.index);
      }
      const per=size.value==="all" ? Math.max(1,filtered.length) : Number(size.value);
      const pages=Math.max(1,Math.ceil(filtered.length/per)); page=Math.min(page,pages);
      const shown=filtered.slice((page-1)*per,page*per), visible=new Set(shown);
      records.forEach(r=>r.row.classList.toggle("ux-row-hidden",!visible.has(r)));
      // Déplacer les nœuds conserve les boutons et leurs gestionnaires métier.
      const fragment=document.createDocumentFragment();
      const matches = new Set(filtered);
      [...filtered,...records.filter(r=>!matches.has(r))].forEach(r=>fragment.append(r.row));
      body.append(fragment);
      headers.forEach((h,i)=>{h.removeAttribute("aria-sort"); if(i===sortIndex)h.setAttribute("aria-sort",direction===1?"ascending":"descending");});
      const from=filtered.length?(page-1)*per+1:0, to=Math.min(page*per,filtered.length);
      toolbar.querySelector('[role="status"]').textContent=`${from}–${to} sur ${filtered.length} résultat(s) · ${records.length} ligne(s) chargée(s)`;
      pager.querySelector(".list-page").textContent=`${page} / ${pages}`;
      pager.querySelector(".list-prev").disabled=page===1;
      pager.querySelector(".list-next").disabled=page===pages;
      toolbar.querySelector(".list-csv").disabled=!filtered.length;
      empty.classList.toggle("hidden",!!filtered.length);
      pager.classList.toggle("hidden",records.length<=25);
    }
    headers.forEach((h,i)=>{
      if(!titles[i] || h.querySelector("button,a,input")) return;
      const b=document.createElement("button"); b.type="button"; b.className="list-sort";
      b.textContent=titles[i]; b.title="Trier par " + titles[i];
      h.replaceChildren(b); b.onclick=()=>{direction=sortIndex===i?-direction:1;sortIndex=i;page=1;draw();};
    });
    query.oninput=()=>{page=1;draw();}; if(status)status.onchange=()=>{page=1;draw();};
    size.onchange=()=>{page=1;draw();};
    pager.querySelector(".list-prev").onclick=()=>{page--;draw();};
    pager.querySelector(".list-next").onclick=()=>{page++;draw();};
    toolbar.querySelector(".list-reset").onclick=()=>{query.value="";if(status)status.value="";page=1;sortIndex=-1;draw();query.focus();};
    toolbar.querySelector(".list-xlsx").onclick=()=>Editions.excel(label,searchable.map(i=>titles[i]),filtered.map(r=>searchable.map(i=>r.cells[i])));
    toolbar.querySelector(".list-pdf").onclick=()=>Editions.tableau(label,`${filtered.length} ligne(s) · filtre : ${query.value || 'aucun'}${status?.value?' · '+status.value:''}`,searchable.map(i=>titles[i]),filtered.map(r=>searchable.map(i=>r.cells[i])));
    toolbar.querySelector(".list-csv").onclick=()=>{
      const csv=toCSV(searchable.map(i=>titles[i]),filtered.map(r=>searchable.map(i=>r.cells[i])));
      const a=document.createElement("a"), url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));
      a.href=url; a.download=`kilima-${view}-${currentSocieteId}-${new Date().toISOString().slice(0,10)}.csv`; a.click();
      setTimeout(()=>URL.revokeObjectURL(url),2000);
      toast(`${filtered.length} ligne(s) exportée(s). Les boutons d'action sont exclus.`,"ok");
    };
    draw();
  }

  function enhanceCards(container) {
    if(container.dataset.uxReady)return;
    const cards=[...container.children].filter(c=>c.classList.contains("caisse-card"));
    if(cards.length<2)return;
    container.dataset.uxReady="true";
    const bar=document.createElement("div");bar.className="card-search-tools";
    bar.innerHTML='<label><span class="sr-only">Rechercher dans les fiches</span><input class="form-input" type="search" placeholder="Rechercher un nom, un véhicule, un état…" /></label><span role="status" aria-live="polite"></span>';
    container.before(bar);
    const input=bar.querySelector("input"), count=bar.querySelector("span[role]");
    const update=()=>{let visible=0;cards.forEach(c=>{const match=normalize(c.textContent).includes(normalize(input.value));c.classList.toggle("hidden",!match);if(match)visible++;});count.textContent=`${visible} / ${cards.length} fiche(s)`;};
    input.oninput=update;update();
  }

  function enhanceView(view) {
    const root=document.querySelector("#view-"+view);
    if(!root || !root.classList.contains("active") || root.querySelector(":scope > .load-error"))return;
    const group=groups.find(g=>g.views.includes(view));
    if(group && root.children.length && !root.querySelector(":scope > .module-guide") && !/^Chargement/.test(root.textContent.trim())) {
      const guide=document.createElement("details");guide.className="module-guide";
      const allowed=new Set(visibleModules().flatMap(g=>g.items.map(i=>i.v)));
      guide.innerHTML=`<summary><span class="module-guide-category">${text(group.name)}</span><span>${text(group.purpose)}</span><span class="module-guide-toggle">Repères du module</span></summary><div class="module-guide-body"><p>${text(group.tip)}</p><div>${group.links.filter(v=>allowed.has(v)&&v!==view).map(v=>`<button class="btn btn-sm" type="button" data-module-go="${v}">${text(TITLES[v]?.[0]||v)} →</button>`).join("")}</div></div>`;
      root.prepend(guide);
      guide.querySelectorAll("[data-module-go]").forEach(b=>b.onclick=()=>go(b.dataset.moduleGo));
    }
    if(tableViews.has(view))root.querySelectorAll("table").forEach(t=>enhanceTable(t,view));
    if(cardsViews.has(view))root.querySelectorAll(".caisse-cards").forEach(enhanceCards);
  }
  function labelFields(root) {
    root.querySelectorAll(".form-group").forEach(group=>{
      const label=group.querySelector("label.form-label"), control=group.querySelector("input,select,textarea");
      if(label&&!label.htmlFor&&control){if(!control.id)control.id="labelled-field-"+(++sequence);label.htmlFor=control.id;}
    });
  }
  function init() {
    let queued=false;
    const observe=()=>observer.observe(document.querySelector(".content"),{childList:true,subtree:true});
    observer=new MutationObserver(()=>{
      if(queued)return;queued=true;
      requestAnimationFrame(()=>{queued=false;observer.disconnect();try{enhanceView(activeView);labelFields(document.querySelector(".content"));}finally{observe();}});
    });
    observe();
  }
  return {init,enhanceView,labelFields,normalize,toCSV,compare,selectRows,managesLists:view=>tableViews.has(view)};
})();
if(typeof module!=="undefined" && module.exports)module.exports=ModuleUX;
