const {test}=require('node:test');
const assert=require('node:assert/strict');
const {recipePayload}=require('../lib/kitchen-data.ts');
test('une recette conserve les quantités du lot entier et les fractions de portions',()=>{
 assert.deepEqual(recipePayload('plat','10',[{article_id:'riz',qte:'1.25'},{article_id:'sel',qte:'0.0025'}]),{article_id:'plat',portions:10,lignes:[{article_id:'riz',qte:1.25},{article_id:'sel',qte:0.0025}]});
});
test('une recette incomplète, circulaire ou dupliquée est refusée sans omettre une ligne',()=>{
 assert.throws(()=>recipePayload('plat','1',[]));
 assert.throws(()=>recipePayload('plat','1',[{article_id:'plat',qte:'1'}]));
 assert.throws(()=>recipePayload('plat','1',[{article_id:'riz',qte:'1'},{article_id:'riz',qte:'2'}]));
 for(const qte of ['', '0', '-1', 'Infinity'])assert.throws(()=>recipePayload('plat','1',[{article_id:'riz',qte}]));
 for(const portions of ['', '0', '-1', 'Infinity'])assert.throws(()=>recipePayload('plat',portions,[{article_id:'riz',qte:'1'}]));
});
