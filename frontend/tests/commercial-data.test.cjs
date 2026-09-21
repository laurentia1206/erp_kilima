const {test}=require('node:test');
const assert=require('node:assert/strict');
const {commercialLines,commercialTotals,lineDiscountForEdit}=require('../lib/commercial-data.ts');
const row={article_id:'article-a',designation:'Produit',qte:'2',prix_unitaire:'100',taux_tva:'16',remise_pct:'10'};
test('modifier un devis ne réapplique pas la remise globale à une ligne déjà remisée',()=>{
 assert.equal(lineDiscountForEdit(14.5,5),10);
 assert.equal(commercialTotals([{...row,qte:'1',prix_unitaire:'10',taux_tva:'0',remise_pct:String(lineDiscountForEdit(14.5,5))}],'5').ttc,8.55);
 assert.equal(lineDiscountForEdit(100,100),0);
 assert.equal(lineDiscountForEdit(10,0),10);
});
test('remises successives et TVA par article, y compris exonération et fractions',()=>{
 const t=commercialTotals([row,{...row,article_id:'b',qte:'0.5',prix_unitaire:'20',taux_tva:'0',remise_pct:'0'}],'5');
 assert.deepEqual(t,{ht:180.5,tva:27.36,ttc:207.86,remise:29.5});
 assert.equal(commercialLines([{...row,prix_unitaire:'0',taux_tva:'0'}])[0].prix_unitaire,0);
});
test('une ligne incomplète n’est pas omise et les montants non finis sont refusés',()=>{
 for(const changed of [{qte:'0'},{qte:''},{prix_unitaire:'Infinity'},{designation:' '},{taux_tva:'101'},{remise_pct:'-1'}]) assert.throws(()=>commercialLines([row,{...row,...changed}],true));
 assert.throws(()=>commercialTotals([row],'101'));
 assert.throws(()=>commercialLines([]));
});
