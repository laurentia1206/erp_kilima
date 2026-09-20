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
    window:{KilimaNext:{owns:view=>['accueil','pilotage','audit','stock','taux','articles','hotel-chambres'].includes(view)},dispatchEvent(event){events.push(event.detail);},addEventListener(){}},
    CustomEvent:class {constructor(type,options){this.detail=options.detail;}},
    me:{id:'dfi',nom:'Test',super_administrateur:false}, societes:[{id:'a'},{id:'b'}],currentSocieteId:'a',
    activeView:'stock',token:'token',NAV:[],TITLES:{stock:['Stock','Quantités']},RENDER:{},
    visibleModules:()=>[{g:'Stocks',items:[{v:'stock',l:'Stock',i:'ti-box'}]}],
    api:async()=>({}),boot:async()=>{},logout(){ctx.me=null;ctx.token=null;},go:async(view)=>{calls.push(view);},
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
  for(const view of ['pilotage','audit','stock','taux','articles','hotel-chambres'])assert.equal(typeof ctx.RENDER[view],'function');
});
test('un export interrompu par un changement de société ne délivre pas le document',async()=>{
  const {ctx,bridge}=setup();ctx.API='/api';ctx.fetch=async()=>({ok:true,status:200,blob:async()=>{ctx.currentSocieteId='b';return {};}});
  await assert.rejects(bridge.download('/audit/export','journal.pdf'),/société modifiée/);
});
