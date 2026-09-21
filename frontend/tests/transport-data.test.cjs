const {test}=require('node:test');
const assert=require('node:assert/strict');
const {contractPayload,documentPayload}=require('../lib/transport-data.ts');
const values={libelle:' Contrat test ',client:'client1',debut:'2026-09-01',fin:'2026-09-30',note:''};
test('les tarifs incomplets, négatifs et dupliqués ne disparaissent pas silencieusement',()=>{
 const tariff={trajet:'Likasi — Kolwezi',mode:'tonne',prix:'12.50'};
 assert.equal(contractPayload(values,[tariff]).tarifs[0].prix,12.5);
 for (const row of [{...tariff,trajet:''},{...tariff,prix:''},{...tariff,prix:'NaN'},{...tariff,prix:'-1'},{...tariff,mode:'autre'}]) assert.throws(()=>contractPayload(values,[tariff,row]));
 assert.throws(()=>contractPayload(values,[tariff,{...tariff,trajet:'  LIKASI — KOLWEZI '} ]));
 assert.equal(contractPayload(values,[]).tarifs.length,0);
 assert.throws(()=>contractPayload({...values,fin:'2026-08-31'},[]));
});
test('un renouvellement conserve le porteur, une création en requiert exactement un',()=>{
 const doc={porteur:'engin_id:engin1',type_document:'assurance',libelle:' Assurance ',numero:'',date_emission:'2026-09-01',date_expiration:'2027-09-01',note:''};
 const created=documentPayload(doc,false);assert.equal(created.engin_id,'engin1');assert.equal(created.numero,null);
 const renewed=documentPayload({...doc,porteur:'camion_id:autre'},true);assert.equal('camion_id' in renewed,false);assert.equal('engin_id' in renewed,false);
 assert.throws(()=>documentPayload({...doc,porteur:'societe_id:autre'},false));
 assert.throws(()=>documentPayload({...doc,date_expiration:'2026-08-31'},false));
 assert.equal(documentPayload({...doc,date_expiration:''},true).date_expiration,null);
});
test('les écrans migrés sont possédés par React et neutralisés côté historique',()=>{
 const fs=require('node:fs');
 const index=fs.readFileSync('components/business/index.tsx','utf8');
 const views=[...index.match(/BUSINESS_VIEWS = \[(.*?)\]/)[1].matchAll(/'([^']+)'/g)].map(m=>m[1]);
 assert.equal(views.length,62);assert.equal(new Set(views).size,62);
 for(const file of ['lib/runtime.ts','legacy/next-adapter.js']) {
  const source=fs.readFileSync(file,'utf8');for(const view of views) assert.ok(source.includes(`'${view}'`),`${view} absent de ${file}`);
 }
});
