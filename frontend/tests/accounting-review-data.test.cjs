const {test}=require('node:test');
const assert=require('node:assert/strict');
const {reviewPayload}=require('../lib/accounting-review-data.ts');
const entry={revision:'version1',lignes:[{id:'l1',compte:'601',montant_usd:12.34}]};
const accounts=[{numero:'601'},{numero:'602'}];
const part=(compte_numero,montant)=>({compte_numero,montant,libelle:''});
test('les parts incomplètes et écarts de centimes empêchent la validation',()=>{
 for(const parts of [[],[part('601','12.34'),part('','')],[part('601','12.33')],[part('601','NaN')]]) assert.throws(()=>reviewPayload(entry,{l1:{compte:'601',parts,allocation:null}},accounts,[]));
 const payload=reviewPayload(entry,{l1:{compte:'601',parts:[part('601','2.34'),part('602','10')],allocation:null}},accounts,[]);
 assert.equal(payload.body.revision,'version1');assert.equal(payload.body.splits[0].repartition.length,2);
 assert.equal('tiers_id' in payload.body.splits[0].repartition[0],false);
});
test('la ventilation préparée est séparée de la validation et doit être complète',()=>{
 const allocation={axe_id:'a',rows:[{section_id:'s',montant:'2.34'}]}, axes=[{id:'a',sections:[{id:'s'}]}];
 const payload=reviewPayload(entry,{l1:{compte:'602',parts:null,allocation}},accounts,axes);
 assert.equal(payload.body.reclassements[0].compte_numero,'602');assert.equal(payload.ventilations[0].repartition[0].montant,2.34);
 assert.throws(()=>reviewPayload(entry,{l1:{compte:'601',parts:[part('601','12.34')],allocation}},accounts,axes));
 assert.throws(()=>reviewPayload(entry,{l1:{compte:'601',parts:null,allocation:{axe_id:'a',rows:[]}}},accounts,axes));
});
