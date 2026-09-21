const {test}=require('node:test');
const assert=require('node:assert/strict');
const {countPayload,transferPayload,validCount,quantity,cost}=require('../lib/stock-forms.ts');
test('un comptage vide ne devient jamais zéro et les valeurs non finies sont refusées',()=>{
 for(const value of ['', ' ', '-1','Infinity','NaN']) assert.equal(validCount(value),false);
 assert.equal(validCount('0'),true);
 const rows=[{article_id:'A',qte:12.125}];
 assert.throws(()=>countPayload(rows,{}));
 assert.deepEqual(countPayload(rows,{A:'0'}),[{article_id:'A',qte_reelle:0,qte_theorique:12.125}]);
 assert.throws(()=>countPayload([],{}));
});
test('le comptage conserve la référence théorique pour le contrôle de concurrence du serveur',()=>{
 const rows=[{article_id:'A',qte:12.125},{article_id:'B',qte:0}];
 const result=countPayload(rows,{A:'11.001',B:'2.5'});
 assert.deepEqual(result,[{article_id:'A',qte_theorique:12.125,qte_reelle:11.001},{article_id:'B',qte_theorique:0,qte_reelle:2.5}]);
 assert.equal(rows[0].qte,12.125);
 assert.throws(()=>countPayload([rows[0],rows[0]],{A:'1'}));
});
test('les transferts ne suppriment pas silencieusement les lignes incomplètes ou dupliquées',()=>{
 assert.throws(()=>transferPayload('A','A',[{article_id:'x',qte:'1'}]));
 assert.throws(()=>transferPayload('A','B',[]));
 for(const qte of ['', '0', '-1', 'Infinity', '0.0001']) assert.throws(()=>transferPayload('A','B',[{article_id:'x',qte}]));
 assert.throws(()=>transferPayload('A','B',[{article_id:'x',qte:'1'},{article_id:'x',qte:'2'}]));
 assert.throws(()=>transferPayload('A','B',[{article_id:'',qte:'1'}]));
 assert.deepEqual(transferPayload('A','B',[{article_id:'x',qte:'0.001'}]),[{article_id:'x',qte:0.001}]);
});
test('les quantités et les coûts conservent leur précision métier à l’affichage',()=>{
 assert.equal(quantity(0.001),'0,001');
 assert.equal(cost(1.1234),'1,1234');
});
