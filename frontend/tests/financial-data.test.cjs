const {test}=require('node:test');
const assert=require('node:assert/strict');
const {incomeRows,cashFlowRows}=require('../lib/financial-data.ts');
test('les états gardent les sous-totaux, les zéros et le comparatif fournis par Django',()=>{
 const rows=incomeRows({sections:[{titre:'Produits',total:12,total_n1:10,lignes:[{poste:'70',intitule:'Ventes',montant:12,montant_n1:10}]},{solde:'Résultat exploitation',montant:0,montant_n1:-3}],resultat_net:0,resultat_net_n1:-3});
 assert.equal(rows.length,4);assert.equal(rows[0].kind,'section');assert.deepEqual(rows[3].values,[0,-3]);
});
test('les flux affichent les montants du serveur sans additionner deux fois les détails',()=>{
 const rows=cashFlowRows({tresorerie_ouverture:10,flux:[{titre:'Activités',total:5,lignes:[{libelle:'Flux',montant:5}]}],variation:5,tresorerie_cloture:15});
 assert.equal(rows.at(-1).values[0],15);assert.equal(rows[1].values[0],5);assert.equal(rows[2].values[0],5);
});
