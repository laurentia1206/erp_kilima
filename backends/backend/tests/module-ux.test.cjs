const {test} = require('node:test');
const assert = require('node:assert/strict');
const ux = require('../../backend/static/module-ux.js');

test('recherche multi-mots sans accents et filtre de statut exact', () => {
  const rows = [
    {search:ux.normalize('REQ-01 Réparation génératrice'),status:'Validée'},
    {search:ux.normalize('REQ-02 Réparation camion'),status:'Validée'},
    {search:ux.normalize('REQ-03 Réparation génératrice'),status:'Non validée'},
  ];
  assert.deepEqual(ux.selectRows(rows, ' GENERATRICE reparation ', 'Validée'), [rows[0]]);
  assert.equal(ux.selectRows(rows, 'inexistant', '').length, 0);
  assert.equal(ux.selectRows(rows, '', '').length, 3);
});

test('tri des montants français, espaces insécables, négatifs et numéros', () => {
  const values = ['3\u202f000,50 USD', '125,00 USD', '−25,50 USD', '800,00 USD'];
  assert.deepEqual(values.sort((a,b)=>ux.compare(a,b,true)), ['−25,50 USD','125,00 USD','800,00 USD','3\u202f000,50 USD']);
  assert.ok(ux.compare('REQ-2','REQ-10') < 0);
});

test('CSV protège les libellés contre les formules sans altérer les nombres', () => {
  const csv=ux.toCSV(['Libellé','Montant'], [['=HYPERLINK("danger")',-12.5], ['\t+cmd',0], ['@SUM(A1)',25], ['-1+2',3]]);
  assert.ok(csv.startsWith('\uFEFF"Libellé";"Montant"\r\n'));
  assert.ok(csv.includes('"\'=HYPERLINK(""danger"")";"-12.5"'));
  assert.ok(csv.includes('"\'\t+cmd";"0"'));
  assert.ok(csv.includes('"\'@SUM(A1)";"25"'));
  assert.ok(csv.includes('"\'-1+2";"3"'));
});

test('CSV conserve accents, guillemets, séparateurs et retours de ligne', () => {
  assert.equal(ux.toCSV(['Nom'], [['Café; "A"\nB'], [null]]), '\uFEFF"Nom"\r\n"Café; ""A""\nB"\r\n""');
});

test('les outils de liste écartent les journaux à solde progressif et les écritures éditables', () => {
  for (const view of ['caisse','grand-livre','balance','compta','saisie-od','hotel-reception','pos']) assert.equal(ux.managesLists(view),false);
  for (const view of ['requisitions','ordres','stock','ventes','courses','administration']) assert.equal(ux.managesLists(view),true);
});
