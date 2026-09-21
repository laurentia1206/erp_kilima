const {test}=require('node:test');
const assert=require('node:assert/strict');
const {cents,entryTotals,entryPayload,ledgerRows,partyLabel}=require('../lib/accounting-data.ts');
const accounts=[{numero:'601'},{numero:'401'}];
const parties=[{id:'a',code:'A',nom:'Homonyme',type:'fournisseur',societe_id:'soc',actif:true},{id:'b',code:'B',nom:'Homonyme',type:'fournisseur',societe_id:null,actif:true},{id:'c',societe_id:'autre',actif:true},{id:'d',societe_id:'soc',actif:false}];
const lines=[{key:1,sens:'D',compte:'601',tiers_id:'a',libelle:'Charge',montant:'0.30'},{key:2,sens:'C',compte:'401',tiers_id:'b',libelle:'Dette',montant:'0.30'}];
const payload=(rows=lines)=>entryPayload(rows,accounts,parties,'soc','OD','2026-09-21','Essai','REF');
test('les centimes évitent les faux écarts de virgule flottante',()=>{
 assert.equal(cents('10.01'),1001);
 assert.equal(entryTotals([{...lines[0],montant:'0.10'},{...lines[0],montant:'0.20'},lines[1]]).balanced,true);
 for(const amount of ['','-1','0','0.001','Infinity','NaN','1e2','9007199254740991'])assert.throws(()=>cents(amount));
});
test('les lignes incomplètes et les écritures déséquilibrées ne sont pas ignorées',()=>{
 assert.throws(()=>payload([...lines,{...lines[0],compte:'',montant:''}]));
 assert.throws(()=>payload([lines[0],{...lines[1],montant:'0.29'}]));
 assert.throws(()=>payload([lines[0]]));
 assert.throws(()=>payload([lines[0],{...lines[1],compte:'999'}]));
});
test('les homonymes sont identifiés par ID et les fiches partagées restent sélectionnables',()=>{
 assert.deepEqual(payload().lignes.map(l=>l.tiers_id),['a','b']);
 for(const id of ['c','d','inconnu'])assert.throws(()=>payload([lines[0],{...lines[1],tiers_id:id}]));
 assert.match(partyLabel(parties[1]),/Fiche partagée/);
 assert.equal(payload([lines[0],{...lines[1],tiers_id:''}]).lignes[1].tiers_id,null);
});
test('les lignes du grand livre conservent leur statut et le solde progressif du serveur',()=>{
 const rows=ledgerRows([{compte:'401',intitule:'Fournisseurs',solde:-10,mouvements:[{date:'2026-09-21',journal:'OD',piece:'OD-1',libelle:'Test',tiers:'Tiers',lettrage:null,statut:'en_attente',debit:0,credit:10,solde:-10}]}]);
 assert.equal(rows[0][8],'En attente'); assert.equal(rows[0][11],-10);
});
