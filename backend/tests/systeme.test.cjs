const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function contexte(me){
  const ctx={me,NAV:[{g:'Stocks & inventaires',items:[{v:'articles'}]},{g:'Ressources humaines',items:[{v:'rh'}]}]};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../../frontend/legacy/systeme.js'),'utf8')+'\nthis.systeme=Systeme;',ctx);
  return ctx;
}
test('les limites masquent le module sans masquer les modules autorisés',()=>{
  const c=contexte({permissions:{stocks:{consulter:false}}});
  assert.equal(c.systeme.autorise('articles'),false);
  assert.equal(c.systeme.autorise('rh'),true);
  assert.equal(c.systeme.autorise('accueil'),true);
  assert.equal(c.systeme.autorise('systeme'),false);
});
test('la super administration est limitée aux utilisateurs même avec des permissions métier',()=>{
  const c=contexte({super_administrateur:true,permissions:{stocks:{consulter:false}}});
  assert.equal(c.systeme.autorise('articles'),false);
  assert.equal(c.systeme.autorise('rh'),false);
  assert.equal(c.systeme.autorise('administration'),true);
  assert.equal(c.systeme.autorise('audit'),true);
  assert.equal(c.systeme.autorise('systeme'),true);
  c.me={super_administrateur:false,permissions:{}};
  assert.equal(c.systeme.autorise('systeme'),false);
});
