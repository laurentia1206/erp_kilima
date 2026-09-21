const {test}=require('node:test');
const assert=require('node:assert/strict');
const {auditQuery,auditActionLabel,attentionActions,assertAuditCapabilities}=require('../lib/audit-data.ts');
test('le journal global ne transporte pas une société résiduelle et préserve les filtres de l’export',()=>{
 const q=auditQuery('societe-a',{portee:'global',action:'ACCES_REFUSE',adresse_ip:'192.0.2.10',attention:'1',du:'2026-09-01'},2,500);
 assert.equal(q.has('societe_id'),false);assert.equal(q.get('borne'),'500');assert.equal(q.get('page'),'2');assert.equal(q.get('adresse_ip'),'192.0.2.10');
 assert.equal(auditQuery('a',{portee:'societe'},1,0).get('societe_id'),'a');
});
test('les événements à examiner restent explicites, sans transformer une réussite en incident',()=>{
 assert.equal(attentionActions.has('CONNEXION_ECHEC'),true);assert.equal(attentionActions.has('CONNEXION_REUSSIE'),false);
 assert.equal(auditActionLabel('FUTURE_ACTION'),'FUTURE_ACTION');
});
test('un ancien serveur est signalé avant le rendu des indicateurs, sans fabriquer de zéros',()=>{
 const old={resultats:[],total:0,modules:[],utilisateurs:[]};
 assert.throws(()=>assertAuditCapabilities(old),/redémarrer le serveur Django/);
 const current={...old,actions:[],indicateurs:{connexions:0,echecs:0,refus:0,erreurs:0,habilitations:0}};
 assert.doesNotThrow(()=>assertAuditCapabilities(current));
 for(const value of [null,{...current,indicateurs:null},{...current,actions:null},{...current,indicateurs:{...current.indicateurs,echecs:NaN}}]) assert.throws(()=>assertAuditCapabilities(value));
});
