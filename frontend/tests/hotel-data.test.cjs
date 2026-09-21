const {test}=require('node:test');
const assert=require('node:assert/strict');
const {shiftDay,validateStay,paymentPieces,paymentAmount,samePayments,clientLabel}=require('../lib/hotel-data.ts');
test('le planning passe les fins de mois et années sans décalage horaire',()=>{
 assert.equal(shiftDay('2026-12-31',1),'2027-01-01');
 assert.equal(shiftDay('2028-02-28',1),'2028-02-29');
 assert.equal(shiftDay('2026-03-01',-1),'2026-02-28');
});
test('le séjour exige une nuit, un nombre entier de personnes et un tarif fini',()=>{
 assert.doesNotThrow(()=>validateStay('2026-09-20','2026-09-21','2','0'));
 assert.throws(()=>validateStay('2026-09-20','2026-09-20','2','100'));
 for(const people of ['0','1.5','Infinity'])assert.throws(()=>validateStay('2026-09-20','2026-09-21',people,'100'));
 for(const rate of ['', '-1','Infinity'])assert.throws(()=>validateStay('2026-09-20','2026-09-21','1',rate));
});
test('un ticket déjà réglé ou lié plusieurs fois ne produit pas un nouvel encaissement',()=>{
 const folio={facture_sejour:{id:'A',numero:'FAC1',solde_du_usd:116},tickets_pos:[{facture_pos_id:'B',designation:'Restaurant',solde_du_usd:10},{facture_pos_id:'B',designation:'Restaurant bis',solde_du_usd:10},{facture_pos_id:'C',designation:'Bar',solde_du_usd:0}]};
 assert.deepEqual(paymentPieces(folio),[{id:'A',label:'Hébergement FAC1',amount:116},{id:'B',label:'Restaurant',amount:10}]);
 assert.deepEqual(paymentPieces({facture_sejour:null,tickets_pos:[]}),[]);
});
test('un solde modifié impose une nouvelle lecture et un taux absent interdit le CDF',()=>{
 assert.equal(samePayments([{id:'A',amount:10}],[{id:'A',amount:9}]),false);
 assert.equal(samePayments([{id:'A',amount:10}],[]),false);
 assert.equal(samePayments([{id:'A',amount:10}],[{id:'A',amount:10}]),true);
 assert.equal(paymentAmount(10.12,'USD'),10.12);
 assert.equal(paymentAmount(10.12,'CDF',2800),28336);
 for(const rate of [null,0,-1,Infinity])assert.throws(()=>paymentAmount(10,'CDF',rate));
});
test('les fiches partagées sont explicitement distinguées des clients de la société',()=>{
 assert.match(clientLabel({code:'C',nom:'Client',societe_id:null,actif:true}),/Fiche partagée/);
 assert.match(clientLabel({code:'C',nom:'Client',societe_id:'societe',actif:true}),/Société active/);
});
