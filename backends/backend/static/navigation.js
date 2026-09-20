/* Organisation visuelle uniquement : les droits et les routes restent ceux des modules. */
const Navigation=(()=>{
  let ouvert='Pilotage';
  const ordre=['Pilotage','Réquisitions & validations','Trésorerie','Comptabilité','Achats','Ventes','Point de vente','Stocks & inventaires','Ressources humaines','Hôtel & restauration','Transport','Location d’engins','Parc & maintenance','Gestion du groupe','Administration & réglages'];
  function organiser(){
    const caisse=NAV.find(g=>g.g==='Caisses (trésorerie)'),depense=NAV.find(g=>g.g==='Décaissement');
    if(caisse&&depense){depense.items.push(...caisse.items);NAV.splice(NAV.indexOf(caisse),1);}
    const noms={'Approbations':'Réquisitions & validations','Décaissement':'Trésorerie','Stock':'Stocks & inventaires','Hôtel':'Hôtel & restauration',"Location d'engins":'Location d’engins','Maintenance':'Parc & maintenance','Groupe':'Gestion du groupe','Paramètres':'Administration & réglages'};
    const libelles={'approbation':'Validations en attente','requisitions':'Suivi des réquisitions','caisse':'Caisses & mouvements','caisse-exec':'Paiements à exécuter','transferts':'Transferts de trésorerie','receptions':'Réceptions fournisseurs','devis':'Devis & commandes clients','rapports-commercial':'Analyse des achats & ventes','stock':'Stocks disponibles & valorisation','articles':'Catalogue des articles','cuisine':'Cuisine & coûts des plats','flotte':'Véhicules & entretien','engins-rpe':'Prestations & facturation','cockpit':'Synthèse financière','compta':'Pièces à comptabiliser','config':'Circuits de validation','administration':'Sociétés, utilisateurs & tiers','rh-paiements':'Versement des avances & prêts'};
    NAV.forEach(g=>{g.g=noms[g.g]||g.g;g.items.forEach(it=>{if(it.l==='Configuration')it.l='Paramètres du module';if(libelles[it.v]){it.l=libelles[it.v];if(TITLES[it.v])TITLES[it.v][0]=it.l;}});});
    NAV.sort((a,b)=>ordre.indexOf(a.g)-ordre.indexOf(b.g));
  }
  function appliquer(){
    document.querySelectorAll('.nav-group').forEach(g=>{const h=g.querySelector('[data-toggle]'),on=h.dataset.toggle===ouvert&&!g.classList.contains('hidden');g.classList.toggle('collapsed',!on);h.setAttribute('aria-expanded',String(on));});
  }
  function ouvrir(nom){ouvert=nom===ouvert?null:nom;appliquer();}
  function selectionner(view,preferer){
    const groupes=[...document.querySelectorAll('.nav-group')];
    const contient=g=>[...g.querySelectorAll('[data-view]')].some(n=>n.dataset.view===view);
    const cible=groupes.find(g=>g.querySelector('[data-toggle]').dataset.toggle===(preferer||ouvert)&&contient(g))||groupes.find(contient);
    if(cible)ouvert=cible.querySelector('[data-toggle]').dataset.toggle;
    document.querySelectorAll('.nav-item').forEach(n=>{const actif=n.dataset.view===view&&n.closest('.nav-group')===cible;n.classList.toggle('active',actif);if(actif)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});
    appliquer();
  }
  function rechercher(valeur){
    const norm=s=>s.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();const termes=norm(valeur).trim().split(/\s+/).filter(Boolean);let premier=null,total=0;
    document.querySelectorAll('.nav-group').forEach(g=>{const h=g.querySelector('[data-toggle]');let count=0;g.querySelectorAll('[data-view]').forEach(n=>{const texte=norm(h.textContent+' '+n.textContent),match=termes.every(t=>texte.includes(t));n.classList.toggle('hidden',!match);if(match)count++;});g.classList.toggle('hidden',!count);if(count&&!premier)premier=h.dataset.toggle;total+=count;});
    if(termes.length&&!document.querySelector(`[data-toggle="${ouvert}"]`)?.closest('.nav-group')?.querySelector('.nav-item:not(.hidden)'))ouvert=premier;
    if(!termes.length)selectionner(activeView);else appliquer();
    document.querySelector('#nav-empty').classList.toggle('hidden',total>0);
  }
  return {organiser,ouvrir,selectionner,rechercher,appliquer};
})();
