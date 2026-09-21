const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');
const source = readFileSync(join(__dirname, '../legacy/next-adapter.js'), 'utf8');
function setup() {
  const events = [], changes = [], calls = [];
  const root = {childElementCount:0};
  const ctx = vm.createContext({location:{pathname:'/espace/stock'},
    history:{pushState(...args){changes.push(args[2]);},replaceState(...args){changes.push(args[2]);}},
    document:{addEventListener(){},title:''},
    window:{KilimaNext:{owns:view=>['accueil','pilotage','audit','stock','taux','articles','hotel-chambres','depots','inventaires','hotel-reception','cuisine','balance','grand-livre','saisie-od','plan-comptable','lettrage','rapprochement','cockpit','etats','analytique','tva','compta','rapports-commercial', 'dashboard', 'config-hotel', 'config-engins', 'config-transport', 'config-maintenance', 'contrats-transport', 'flotte-documents', 'engins-rpe', 'flotte', 'engins-parc', 'engins-heures', 'maintenance-parc', 'maintenance-interventions', 'carburant', 'tarifs-pos', 'transferts', 'caisse-exec', 'intersociete', 'nouvelle-req', 'requisitions', 'approbation', 'ordres', 'avances', 'caisse', 'courses', 'config', 'administration', 'systeme', 'rh', 'rh-simulateur', 'rh-decomptes', 'rh-finances', 'rh-paiements', 'rh-mensuel', 'achats', 'ventes', 'commandes', 'receptions', 'devis', 'pos'].includes(view)},dispatchEvent(event){events.push(event.detail);},addEventListener(){}},
    CustomEvent:class {constructor(type,options){this.detail=options.detail;}},
    me:{id:'dfi',nom:'Test',super_administrateur:false}, societes:[{id:'a'},{id:'b'}],currentSocieteId:'a',
    activeView:'stock',token:'token',NAV:[],TITLES:{stock:['Stock','Quantités']},RENDER:{},
    visibleModules:()=>[{g:'Stocks',items:[{v:'stock',l:'Stock',i:'ti-box'}]}],
    API:'/api',fetch:async()=>({ok:true}),api:async()=>({}),boot:async()=>{},logout(){ctx.me=null;ctx.token=null;},go:async(view)=>{calls.push(view);},
    pendingWrites:new Set(),$:()=>root,Clotures:{confirmLeave:()=>true},toast(message){events.push(message);},
    localStorage:{setItem(){}},renderSidebar(){},refreshBadge(){},refreshComptaBadge(){},Pilotage:{badge(){}},closeModal(){},
  });
  vm.runInContext(source,ctx);
  return {ctx, bridge:ctx.window.KilimaERP, events, changes, calls, root};
}
test('un lien direct reste limité aux modules accessibles',()=>{
  const {ctx}=setup();
  assert.equal(ctx.window.KilimaNext.initialView(),'stock');
  ctx.location.pathname='/espace/systeme';
  assert.equal(ctx.window.KilimaNext.initialView(),null);
});
test('une opération ou une fenêtre ouverte empêche le changement de société',async()=>{
  const {ctx,bridge,root,calls}=setup();
  root.childElementCount=1;await bridge.selectCompany('b');assert.equal(ctx.currentSocieteId,'a');
  root.childElementCount=0;ctx.pendingWrites.add('payment');await bridge.selectCompany('b');assert.equal(ctx.currentSocieteId,'a');
  ctx.pendingWrites.clear();await bridge.selectCompany('inconnue');assert.equal(ctx.currentSocieteId,'a');
  await bridge.selectCompany('b');assert.equal(ctx.currentSocieteId,'b');assert.deepEqual(calls,['accueil']);
});
test('la déconnexion efface la session et revient à la connexion',()=>{
  const {ctx,bridge,changes}=setup();bridge.logout();assert.equal(ctx.token,null);assert.equal(ctx.me,null);assert.deepEqual(changes,['/']);
});
test('les publications React ne contiennent pas le jeton',()=>{
  const {bridge}=setup();const snapshot=bridge.snapshot();
  assert.equal(snapshot.companyId,'a');assert.equal(snapshot.groups[0].items[0].view,'stock');assert.equal('token' in snapshot,false);
});
test('un échec de chargement après authentification nettoie la session',async()=>{
  const {ctx,bridge}=setup();ctx.api=async()=>({access_token:'nouveau'});ctx.boot=async()=>{throw new Error('indisponible');};
  await assert.rejects(bridge.login('test','secret'),/indisponible/);assert.equal(ctx.token,null);
});

test('une saisie React bloque changement de société et déconnexion jusqu’à sa fermeture',async()=>{
  const {ctx,bridge}=setup();const release=bridge.holdNavigation();
  assert.equal(ctx.window.KilimaNext.canLeave(),false);
  await bridge.selectCompany('b');assert.equal(ctx.currentSocieteId,'a');
  bridge.logout();assert.ok(ctx.me);
  release();release();assert.equal(ctx.window.KilimaNext.canLeave(),true);
  await bridge.selectCompany('b');assert.equal(ctx.currentSocieteId,'b');
});
test('fermer une fenêtre ne libère pas les autres saisies actives',()=>{
  const {ctx,bridge}=setup();const a=bridge.holdNavigation(),b=bridge.holdNavigation();
  a();assert.equal(ctx.window.KilimaNext.canLeave(),false);b();assert.equal(ctx.window.KilimaNext.canLeave(),true);
});
test('les écrans convertis ne restaurent plus de rendu impératif',async()=>{
  const {ctx,bridge,calls}=setup();ctx.window.KilimaNext.owns=view=>view==='stock';
  await bridge.restore();assert.deepEqual(calls,[]);
  for(const view of ['pilotage','audit','stock','taux','articles','hotel-chambres','depots','inventaires','hotel-reception','cuisine','balance','grand-livre','saisie-od','plan-comptable','lettrage','rapprochement','cockpit','etats','analytique','tva','compta','rapports-commercial'])assert.equal(typeof ctx.RENDER[view],'function');
});
test('un export interrompu par un changement de société ne délivre pas le document',async()=>{
  const {ctx,bridge}=setup();ctx.API='/api';ctx.fetch=async()=>({ok:true,status:200,blob:async()=>{ctx.currentSocieteId='b';return {};}});
  await assert.rejects(bridge.download('/audit/export','journal.pdf'),/société modifiée/);
});
test('changer le mot de passe renouvelle le jeton sans le publier',async()=>{
 const {ctx,bridge}=setup();let payload;ctx.api=async(path,options)=>{assert.equal(path,'/systeme/mot-de-passe');payload=options.body;return {access_token:'rotation'};};
 await bridge.changePassword('ancien','nouveau');assert.equal(payload.ancien,'ancien');assert.equal(ctx.token,'rotation');assert.equal(JSON.stringify(bridge.snapshot()).includes('rotation'),false);
 ctx.boot=async()=>{throw new Error('connexion interrompue');};await assert.rejects(bridge.changePassword('ancien','nouveau'));assert.equal(ctx.token,null);
});
test('ouvrir une tâche confie le dossier à React puis efface la cible à la fermeture',async()=>{
 const {ctx,bridge}=setup();ctx.activeView='requisitions';
 await bridge.openTask('requisitions','req_validation','demande-a');assert.equal(bridge.snapshot().taskTarget.documentId,'demande-a');
 bridge.clearTask();assert.equal(bridge.snapshot().taskTarget,null);
});

test('une cible de tâche ne traverse pas un changement de société ou de session',async()=>{
 const {ctx,bridge}=setup();ctx.activeView='requisitions';
 await bridge.openTask('requisitions','req_validation','demande-a');
 await bridge.selectCompany('b');assert.equal(bridge.snapshot().taskTarget,null);
 await bridge.openTask('requisitions','req_validation','demande-b');
 bridge.logout();assert.equal(bridge.snapshot().taskTarget,null);
 ctx.me={id:'autre'};assert.equal(bridge.snapshot().taskTarget,null);
});

test('la déconnexion envoie sa trace avec le jeton capturé et libère la session même hors ligne',async()=>{
 const {ctx,bridge}=setup();let captured;
 ctx.fetch=async(path,options)=>{captured={path,options};throw new Error('hors ligne');};
 bridge.logout();assert.equal(ctx.me,null);assert.equal(ctx.token,null);
 assert.equal(captured.path,'/api/auth/logout');assert.equal(captured.options.headers.Authorization,'Bearer token');
 ctx.me={id:'nouvelle-session'};ctx.token='nouveau';await Promise.resolve();assert.equal(ctx.token,'nouveau');
});
