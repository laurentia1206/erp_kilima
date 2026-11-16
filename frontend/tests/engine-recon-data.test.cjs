const {test}=require('node:test');
const assert=require('node:assert/strict');
const {parseDuree,arrondir5,fmtHM,minutesSaisies}=require('../lib/engine-recon-data.ts');
test('les formats libres du desktop sont compris et arrondis à 5 minutes',()=>{
 assert.equal(parseDuree('8h30'),510);
 assert.equal(parseDuree('8:30'),510);
 assert.equal(parseDuree('8,5'),510);
 assert.equal(parseDuree('8.25'),495);
 assert.equal(parseDuree('0'),0);
 assert.equal(parseDuree('16h45'),1005);
 assert.equal(parseDuree(''),null);
 assert.equal(parseDuree('abc'),null);
 assert.equal(parseDuree('8h75'),null);
 assert.equal(arrondir5(508),510);
 assert.equal(arrondir5(507),505);
 assert.equal(fmtHM(510),'8h30');
 assert.equal(fmtHM(-60),'-1h00');
});
test('une saisie invalide est signalée, une saisie vide reprend nos valeurs',()=>{
 assert.equal(minutesSaisies('  ','x'),null);
 assert.equal(minutesSaisies('8h33','x'),515);
 assert.throws(()=>minutesSaisies('n/a','Client jour'),/Client jour/);
});
