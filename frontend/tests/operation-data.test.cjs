const { test } = require('node:test');
const assert = require('node:assert/strict');
const { amount, countedCash } = require('../lib/operation-data.ts');
test('les montants vides, non finis et négatifs sont refusés sans remplacer par zéro', () => {
  for (const v of ['', '  ', 'NaN', 'Infinity', '-0.01']) assert.throws(() => amount(v, 'Montant'));
  assert.equal(amount('0', 'Solde'), 0);
  assert.equal(amount('0.005', 'Prix'), 0.005);
  assert.throws(() => amount('0', 'Paiement', 0.01));
});
test('le billetage ne retient que les coupures de la devise et impose un nombre entier', () => {
  assert.deepEqual(countedCash('USD', { '100': '2', '5': '3', '20000': '8' }), { montant: 215, billetage: { '5': 3, '100': 2 } });
  assert.deepEqual(countedCash('CDF', { '20000': '2', '500': '3' }), { montant: 41500, billetage: { '500': 3, '20000': 2 } });
  for (const v of ['1.5', '-1', 'NaN']) assert.throws(() => countedCash('USD', { '100': v }));
  assert.deepEqual(countedCash('USD', {}), { montant: 0, billetage: {} });
});
