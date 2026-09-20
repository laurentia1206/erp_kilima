const {test}=require('node:test');
const assert=require('node:assert/strict');
const {filterTasks,validateRules}=require('../lib/task-filters.ts');
const blank={q:'',module:'',user:'',niveau:''};
const tasks=[
 {id:'a',reference:'REQ-1',action:'Valider la réquisition',detail:'Hôtel',module:'Achats',niveau:'relance',responsables:[{id:'u1',nom:'Élodie'},{id:'u2',nom:'Paul'}],roles:['DFI']},
 {id:'b',reference:'PAIE-1',action:'Contrôler',detail:'Septembre',module:'RH',niveau:'escalade',responsables:[{id:'u2',nom:'Paul'}],roles:['DRH']},
];
test('les filtres se combinent et conservent les tâches partagées entre validateurs',()=>{
 assert.deepEqual(filterTasks(tasks,{...blank,user:'u2'}).map(t=>t.id),['a','b']);
 assert.deepEqual(filterTasks(tasks,{...blank,q:'elodie',module:'Achats',niveau:'relance',user:'u2'}).map(t=>t.id),['a']);
 assert.equal(filterTasks(tasks,{...blank,module:'RH',user:'u1'}).length,0);
 assert.equal(tasks.length,2);
});
test('les délais doivent être entiers et la remontée doit suivre la relance',()=>{
 assert.ok(validateRules({a:{relance_h:24,escalade_h:48},b:null}));
 for(const pair of [[0,48],[48,24],[24,24],[1,8761],[1.5,48],[NaN,48]])assert.equal(validateRules({a:{relance_h:pair[0],escalade_h:pair[1]}}),false);
 assert.ok(validateRules({a:{relance_h:8759,escalade_h:8760}}));
});
