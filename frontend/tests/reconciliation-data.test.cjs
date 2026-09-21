const {test}=require('node:test');
const assert=require('node:assert/strict');
const {selectionTotals,verifyMatchingSelection,statementAmount}=require('../lib/reconciliation-data.ts');
const {selectTableRows}=require('../lib/table-data.ts');
const debit={id:'D',debit:12.34,credit:0,statut:'valide',tiers:'Fournisseur'};
const credit={id:'C',debit:0,credit:12.34,statut:'valide',tiers:'Fournisseur'};
test('le lettrage exige deux lignes équilibrées et préserve les centimes',()=>{
 assert.equal(selectionTotals([debit,credit]).balanced,true);
 assert.equal(selectionTotals([debit,{...credit,credit:12.33}]).balanced,false);
 assert.equal(selectionTotals([debit]).balanced,false);
 assert.equal(selectionTotals([{...debit,debit:.1},{...debit,debit:.2},{...credit,credit:.3}]).balanced,true);
});
test('une sélection devenue lettrée, modifiée ou absente est refusée avant envoi',()=>{
 assert.deepEqual(verifyMatchingSelection([debit,credit],[debit,credit]),['D','C']);
 for(const fresh of [[debit],[debit,{...credit,lettrage:'A'}],[debit,{...credit,credit:10}],[debit,{...credit,statut:'en_attente'}]])assert.throws(()=>verifyMatchingSelection([debit,credit],fresh));
 assert.throws(()=>verifyMatchingSelection([debit,debit],[debit]));
});
test('le relevé accepte explicitement zéro et le découvert sans convertir un vide en zéro',()=>{
 assert.equal(statementAmount('0'),0);assert.equal(statementAmount('-120.34'),-120.34);
 for(const value of ['', ' ', 'Infinity', 'NaN', '1.001', '1e3'])assert.throws(()=>statementAmount(value));
});
test('le tri conserve l’identité des lignes même avec des valeurs visibles identiques',()=>{
 const rows=[['B',12],['A',1],['A',1]];
 const selected=selectTableRows(rows,'A',1,1);
 assert.deepEqual(selected.map(row=>rows.indexOf(row)),[1,2]);
});
