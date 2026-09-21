const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../../frontend/legacy/pilotage.js'),'utf8');
const c=vm.createContext({});vm.runInContext(code+';globalThis.filtrer=Pilotage.filtrer',c);
test('Les filtres de suivi croisent responsable, module et priorité sans doubler les équipes',()=>{
 const rows=[{reference:'REQ-1',action:'Valider',detail:'',module:'Réquisitions',niveau:'relance',roles:['DFI'],responsables:[{id:'a',nom:'André'},{id:'b',nom:'Béatrice'}]},
 {reference:'INV-2',action:'Contrôler',detail:'',module:'Stocks',niveau:'a_traiter',roles:['DFI'],responsables:[{id:'a',nom:'André'}]}];
 assert.equal(c.filtrer(rows,{q:'andre',user:'a',niveau:'relance'}).length,1);
 assert.equal(c.filtrer(rows,{q:'',user:'b',module:'Stocks'}).length,0);
 assert.equal(c.filtrer(rows,{q:'INV-2'}).length,1);
 assert.equal(c.filtrer(rows,{q:''}).length,2);
});
