const {test}=require('node:test');
const assert=require('node:assert/strict');
const {serverTimestamp}=require('../lib/date-data.ts');
test('les horodatages UTC Django sont indépendants du fuseau du navigateur',()=>{
 assert.equal(serverTimestamp('2026-09-21T10:33:24'),'2026-09-21T10:33:24Z');
 assert.equal(serverTimestamp('2026-09-21T12:33:24+02:00'),'2026-09-21T12:33:24+02:00');
 assert.equal(serverTimestamp('2026-09-21'),'2026-09-21');
});
