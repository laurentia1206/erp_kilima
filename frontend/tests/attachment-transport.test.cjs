const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const source=readFileSync(require('node:path').join(__dirname,'../legacy/app.js'),'utf8');
const api=source.slice(source.indexOf('async function api('),source.indexOf('\nfunction toast('));
function setup(fetch){const context=vm.createContext({FormData,URLSearchParams,token:'test',API:'/api',pendingWrites:new Set(),currentSocieteId:'a',fetch,messageErreur:()=> 'Refus',logout(){}});vm.runInContext(api,context);return context;}
test('le justificatif multipart est transmis intact sans Content-Type JSON ni répétition',async()=>{
 const body=new FormData();body.append('document_id','doc');let calls=0;
 const ctx=setup(async(path,options)=>{calls++;assert.equal(options.body,body);assert.equal(options.headers['Content-Type'],undefined);assert.equal(options.headers.Authorization,'Bearer test');return {ok:true,status:201,headers:new Headers({'Content-Type':'application/json'}),json:async()=>({id:'piece'})};});
 assert.equal((await ctx.api('/pieces-jointes',{method:'POST',body})).id,'piece');assert.equal(calls,1);assert.equal(ctx.pendingWrites.size,0);
});
test('un échec réseau ne répète pas l’envoi de justificatif',async()=>{
 let calls=0;const ctx=setup(async()=>{calls++;throw new Error('offline');});
 await assert.rejects(ctx.api('/pieces-jointes',{method:'POST',body:new FormData()}),error=>error.uncertain === true && /Vérifiez si/.test(error.message));assert.equal(calls,1);assert.equal(ctx.pendingWrites.size,0);
});
