const {test}=require('node:test');
const assert=require('node:assert/strict');
const {duration,roundMinutes,hoursPreview,hoursPayload}=require('../lib/engine-hours-data.ts');
test('les heures de nuit traversent minuit et suivent les arrondis configurés',()=>{
 assert.equal(duration('22:00','06:00'),480); assert.equal(duration('08:00','08:00'),1440);
 assert.equal(duration('24:00','06:00'),0);
 assert.equal(roundMinutes(482,'nearest'),480);assert.equal(roundMinutes(482,'up'),485);assert.equal(roundMinutes(482,'down'),480);
 assert.deepEqual(hoursPreview('22:00','06:00',[{nature:'pause',debut:'23:45',fin:'00:15'}],'nearest'),{gross:480,paused:30,net:450});
});
test('les index zéro sont conservés et un arrêt incomplet ne disparaît pas',()=>{
 const v={engin_id:'engin1',date:'2026-10-01',heure_debut:'08:00',heure_fin:'16:00',poste:'jour',operateur:' Agent ',index_debut:'0',index_fin:'',affectation:''};
 assert.equal(hoursPayload(v,[]).index_debut,0);assert.equal(hoursPayload(v,[]).index_fin,null);
 assert.throws(()=>hoursPayload(v,[{nature:'pause',debut:'12:00',fin:''}]));
 assert.throws(()=>hoursPayload({...v,index_fin:'-1'},[]));
 assert.throws(()=>hoursPayload({...v,index_fin:'NaN'},[]));
});
