const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const postcss = require('postcss');
const tailwind = require('@tailwindcss/postcss');

test('Tailwind compile les utilitaires préfixés sans remplacer la charte ni injecter Preflight', async () => {
  const from = path.resolve(__dirname, '../app/tailwind.css');
  const result = await postcss([tailwind()]).process(fs.readFileSync(from, 'utf8'), { from });
  const rules = [];
  result.root.walkRules(rule => rules.push(rule));
  const flex = rules.find(rule => rule.selector === '.tw\\:flex');
  assert.ok(flex, 'Les classes utilisées dans les cartes comptables doivent être compilées');
  assert.ok(flex.nodes.some(node => node.prop === 'display' && node.value === 'flex'));
  assert.ok(rules.some(rule => rule.selector === '.tw\\:min-w-0'));
  assert.ok(!rules.some(rule => rule.selector === '.flex' || rule.selector === '.container'));
  assert.ok(!rules.some(rule => /(^|,)\s*(html|body|h1|button|input)(\s|,|$)/.test(rule.selector)), 'Pas de reset des titres, polices ou champs historiques');
});
