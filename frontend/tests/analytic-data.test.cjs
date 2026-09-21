const {test}=require('node:test');
const assert=require('node:assert/strict');
const {allocationPayload,sameAllocation,analyticReportRows}=require('../lib/analytic-data.ts');
const axis={sections:[{id:'a'},{id:'b'}]}, line={id:'line',montant:12.34,ventilation:[{section_id:'a',montant:2}]};
test('une ventilation partielle conserve les centimes et refuse les lignes incomplètes ou hors axe',()=>{
 assert.deepEqual(allocationPayload([{section_id:'a',montant:'2.34'}],line,axis,false),[{section_id:'a',montant:2.34}]);
 for(const row of [{section_id:'x',montant:'2'},{section_id:'a',montant:''},{section_id:'a',montant:'NaN'},{section_id:'a',montant:'0.001'},{section_id:'a',montant:'12.36'}]) assert.throws(()=>allocationPayload([row],line,axis,false));
});
test('effacer nécessite une confirmation et une réponse périmée est détectée',()=>{
 assert.throws(()=>allocationPayload([],line,axis,false));assert.deepEqual(allocationPayload([],line,axis,true),[]);
 assert.equal(sameAllocation(line,{...line,ventilation:[{section_id:'a',montant:3}]}),false);
 assert.equal(sameAllocation(line,{...line}),true);
});
test('le rapport inclut le non ventilé sans le doubler dans le total serveur',()=>{
 const rows=analyticReportRows({lignes:[{code:'A',section:'Cuisine',charges:2,produits:0,resultat:-2}],non_ventile:{charges:10.34,produits:20},total_charges:12.34,total_produits:20,resultat:7.66});
 assert.deepEqual(rows.at(-1),['','TOTAL',12.34,20,7.66]);assert.equal(rows[1][4],9.66);
});
