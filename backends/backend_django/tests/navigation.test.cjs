const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const script=readFileSync(path.join(__dirname,'../../backend/static/navigation.js'),'utf8');
function cls(){const s=new Set();return {contains:x=>s.has(x),toggle:(x,v)=>{if(v)s.add(x);else s.delete(x);}};}
function group(name,views){
 const g={classList:cls()},h={dataset:{toggle:name},textContent:name,expanded:null,setAttribute:(k,v)=>h.expanded=v,closest:()=>g};
 const items=views.map(v=>({dataset:{view:v},textContent:v,classList:cls(),setAttribute(){},removeAttribute(){},closest:()=>g}));
 g.querySelector=q=>q==='[data-toggle]'?h:items.find(n=>!n.classList.contains('hidden'));
 g.querySelectorAll=()=>items;return {g,h,items};
}
function setup(){
 const gs=[group('Pilotage',['accueil']),group('Transport',['courses','carburant']),group('Location d’engins',['engins-parc','carburant']),group('Ressources humaines',['rh-mensuel'])];
 const document={querySelectorAll:q=>q==='.nav-group'?gs.map(x=>x.g):gs.flatMap(x=>x.items),querySelector:q=>q==='#nav-empty'?{classList:cls()}:gs.find(x=>q.includes('"'+x.h.dataset.toggle+'"'))?.h};
 const c=vm.createContext({document,activeView:'accueil',NAV:[],TITLES:{}});vm.runInContext(script+';this.n=Navigation;',c);return {c,gs};
}
test('un seul groupe ouvert après navigation, changement de module et recherche',()=>{
 const {c,gs}=setup(),open=()=>gs.filter(x=>x.h.expanded==='true').map(x=>x.h.dataset.toggle);
 c.n.selectionner('courses');assert.deepEqual(open(),['Transport']);
 c.n.selectionner('rh-mensuel');assert.deepEqual(open(),['Ressources humaines']);
 c.n.rechercher('carburant');assert.equal(open().length,1);
 c.n.ouvrir('Location d’engins');assert.deepEqual(open(),['Location d’engins']);
 c.n.ouvrir('Location d’engins');assert.equal(open().length,0);
});
test('un menu partagé garde le module depuis lequel il a été choisi',()=>{
 const {c,gs}=setup();c.n.selectionner('carburant','Location d’engins');
 assert.equal(gs[2].h.expanded,'true');assert.equal(gs[1].h.expanded,'false');
 assert.equal(gs.flatMap(g=>g.items).filter(n=>n.classList.contains('active')).length,1);
});
test('réorganisation conserve les routes et droits, RH précède les réglages',()=>{
 const source=readFileSync(path.join(__dirname,'../../backend/static/app.js'),'utf8');
 const c=vm.createContext({TITLES:{}});vm.runInContext(source.slice(source.indexOf('const NAV = ['),source.indexOf('function renderSidebar()'))+'\nNAV.push({g:"Ressources humaines",roles:["RH"],items:[{v:"rh",l:"Agents",roles:["RH"]}]});this.groups=NAV;',c);
 const before=c.groups.flatMap(g=>g.items.map(x=>JSON.stringify([x.v,x.roles]))).sort();
 vm.runInContext(script+';Navigation.organiser();',c);
 assert.deepEqual(c.groups.flatMap(g=>g.items.map(x=>JSON.stringify([x.v,x.roles]))).sort(),before);
 const names=c.groups.map(g=>g.g);assert.ok(names.indexOf('Ressources humaines')<names.indexOf('Administration & réglages'));
 assert.equal(names.at(-1),'Administration & réglages');
});
