const {test}=require('node:test');
const assert=require('node:assert/strict');
const {vatRows,vatDraft,validateVatDraft}=require('../lib/vat-data.ts');
test('le dossier TVA distingue montant absent et zéro sans conversion implicite',()=>{
 const draft=vatDraft({donnees:{credit_anterieur_cdf:'0',montant_declare_cdf:''}});
 assert.equal(draft.credit_anterieur_cdf,'0');assert.equal(draft.montant_declare_cdf,'');
 assert.equal(validateVatDraft(draft,'2026-09-21').montant_declare_cdf,'');
 for(const amount of ['-1','Infinity','1.234']) assert.throws(()=>validateVatDraft({...draft,montant_declare_cdf:amount},'2026-09-21'));
});
test('un dépôt requiert référence et date passée valide',()=>{
 const draft=vatDraft({donnees:{}});
 assert.throws(()=>validateVatDraft({...draft,reference_depot:'REC'},'2026-09-21'));
 for(const date of ['2026-09-22','2026-02-31']) assert.throws(()=>validateVatDraft({...draft,reference_depot:'REC',date_depot:date},'2026-09-21'));
 assert.equal(validateVatDraft({...draft,reference_depot:' REC ',date_depot:'2026-09-20'},'2026-09-21').reference_depot,'REC');
});
test('les exports TVA conservent les avoirs signés et le statut en attente',()=>{
 const rows=vatRows({lignes:[{date:'2026-09-21',piece:'AV1',reference:'F1',compte:'4431',nature:'collectee',sens:'D',montant_usd:'16',net_usd:'-16',statut:'en_attente',libelle:'Avoir'}]});
 assert.equal(rows[0][6],16);assert.equal(rows[0][7],-16);assert.equal(rows[0][8],'En attente');
});
