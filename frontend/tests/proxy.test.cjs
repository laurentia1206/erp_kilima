const {test}=require('node:test');
const assert=require('node:assert/strict');
const http=require('node:http');
async function server(handler){
  const app=http.createServer(handler);
  await new Promise(resolve=>app.listen(0,'127.0.0.1',resolve));
  return {origin:`http://127.0.0.1:${app.address().port}`,close:()=>new Promise(resolve=>app.close(resolve))};
}
test('le proxy conserve les droits, filtres et octets des exports sans cache',async()=>{
  const {forwardToDjango}=await import('../lib/django-proxy.mjs');
  const payload=Buffer.from('%PDF-test\x00\xff','latin1');
  const app=await server((req,res)=>{
    assert.equal(req.url,'/api/export?societe_id=a&nom=%C3%A9');
    assert.equal(req.headers.authorization,'Bearer essai');
    assert.equal(req.headers.cookie,undefined);
    res.writeHead(200,{'Content-Type':'application/pdf','Content-Disposition':'attachment; filename="test.pdf"'});res.end(payload);
  });
  try{
    const result=await forwardToDjango(new Request('http://frontend/api/export?societe_id=a&nom=%C3%A9',{headers:{Authorization:'Bearer essai',Cookie:'irrelevant=1'}}),app.origin);
    assert.equal(result.status,200);assert.deepEqual(Buffer.from(await result.arrayBuffer()),payload);
    assert.match(result.headers.get('content-disposition'),/attachment/);assert.match(result.headers.get('cache-control'),/no-store/);
  }finally{await app.close();}
});
test('les envois multipart sont transmis intacts et ne sont pas répétés',async()=>{
  const {forwardToDjango}=await import('../lib/django-proxy.mjs');let calls=0;
  const form=new FormData();form.set('file',new Blob(['document de test']), 'test.txt');form.set('document_id','a');
  const request=new Request('http://frontend/api/pieces-jointes',{method:'POST',body:form});
  const expected=Buffer.from(await request.clone().arrayBuffer());
  const app=await server(async(req,res)=>{
    calls++;assert.match(req.headers['content-type'],/multipart\/form-data; boundary=/);
    assert.equal(req.headers['content-length'], String(expected.length));
    const chunks=[];for await(const part of req)chunks.push(part);assert.deepEqual(Buffer.concat(chunks),expected);
    res.writeHead(201,{'Content-Type':'application/json'});res.end('{"ok":true}');
  });
  try{const result=await forwardToDjango(request,app.origin);assert.equal(result.status,201);assert.equal(calls,1);}finally{await app.close();}
});
test('un serveur inaccessible renvoie une erreur explicite sans répétition',async()=>{
  const {forwardToDjango}=await import('../lib/django-proxy.mjs');let calls=0;
  const app=await server((req,res)=>{calls++;req.socket.destroy();});
  try{const result=await forwardToDjango(new Request('http://frontend/api/payer',{method:'POST',body:'{}'}),app.origin);assert.equal(result.status,502);assert.equal(calls,1);}finally{await app.close();}
});
test('la destination ne peut pas être une URL avec secrets ou chemin',async()=>{
  const {apiOrigin}=await import('../lib/django-proxy.mjs');
  for(const invalid of ['file:///etc/passwd','https://user:password@host','https://host/path'])assert.throws(()=>apiOrigin(invalid));
});
test('un corps trop volumineux est refusé avant tout appel Django',async()=>{
  const {forwardToDjango}=await import('../lib/django-proxy.mjs');
  const result=await forwardToDjango(new Request('http://frontend/api/pieces-jointes',{method:'POST',body:'trop grand'}),'http://127.0.0.1:1',3);
  assert.equal(result.status,413);
});
