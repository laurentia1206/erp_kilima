const {test}=require('node:test');
const assert=require('node:assert/strict');
const {selectTableRows,tableCSV}=require('../lib/table-data.ts');
test('le tri des quantités est numérique et la recherche accepte plusieurs mots sans accents',()=>{
 const rows=[['C2','Ciment spécial',100],['C10','Ciment spécial',9],['A','Huile',20]];
 assert.deepEqual(selectTableRows(rows,'special ciment',2,1),[rows[1],rows[0]]);
 assert.deepEqual(selectTableRows(rows,'',0,1),[rows[2],rows[0],rows[1]]);
 assert.equal(rows[0][0],'C2');
});
test('le CSV protège les formules et conserve les nombres négatifs et les accents',()=>{
 const text=tableCSV(['Libellé','Valeur'],[['=CMD()',-20],['État "neuf"',1]]);
 assert.ok(text.startsWith('\uFEFF'));
 assert.ok(text.includes('"\'=CMD()";"-20"'));
 assert.ok(text.includes('"État ""neuf""";"1"'));
});
