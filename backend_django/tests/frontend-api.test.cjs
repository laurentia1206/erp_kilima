/* Contrats réseau du frontend partagé servi par Django. Aucun navigateur requis. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../../backend/static/app.js'), 'utf8');
const apiSource = source.slice(source.indexOf('async function api('), source.indexOf('\nfunction toast('));
function setup(fetch) {
  const context = vm.createContext({fetch, URLSearchParams,
    API:'/api', token:'test-token', currentSocieteId:'soc-a', pendingWrites:new Set(),
    logout(){ context.token=null; }, messageErreur(data){ return data.detail; }});
  vm.runInContext(apiSource, context);
  return context;
}
const response = (status=200,data={ok:true}) => ({status,ok:status<400,
  headers:{get:()=> 'application/json'},json:async()=>data});

test('deux clics simultanés ne transmettent qu’une seule écriture', async()=>{
  let release, calls=0;
  const c=setup(()=>{ calls++; return new Promise(resolve=>{release=resolve;}); });
  const first=c.api('/ventes',{method:'POST',body:{montant:50}});
  await assert.rejects(c.api('/ventes',{method:'POST',body:{montant:50}}),/déjà en cours/);
  assert.equal(calls,1);
  release(response()); await first;
  assert.equal(c.pendingWrites.size,0);
});
test('une réponse de l’ancienne société ne remplit pas le nouvel écran',async()=>{
  let release;
  const c=setup(()=>new Promise(resolve=>{release=resolve;}));
  const pending=c.api('/dashboard?societe_id=soc-a');
  c.currentSocieteId='soc-b'; release(response());
  await assert.rejects(pending,/société active a changé/);
});
test('une session expirée est fermée ; un refus de rôle conserve la session',async()=>{
  const expire=setup(async()=>response(401));
  await assert.rejects(expire.api('/auth/me'),/Session expirée/);
  assert.equal(expire.token,null);
  const forbid=setup(async()=>response(403,{detail:'Accès refusé'}));
  await assert.rejects(forbid.api('/stock'),/Accès refusé/);
  assert.equal(forbid.token,'test-token');
});
test('un mauvais mot de passe affiche l’erreur de connexion',async()=>{
  const c=setup(async()=>response(401,{detail:'Email ou mot de passe incorrect.'}));
  await assert.rejects(c.api('/auth/login',{method:'POST',form:true,body:{username:'test'}}),/mot de passe incorrect/);
});
test('une coupure sur un paiement ne déclenche aucune répétition automatique',async()=>{
  let calls=0;
  const c=setup(async()=>{calls++;throw new TypeError('Failed to fetch');});
  await assert.rejects(c.api('/paiement',{method:'POST',body:{montant:50}}),/Vérifiez si l’opération/);
  assert.equal(calls,1);
  assert.equal(c.pendingWrites.size,0);
});
