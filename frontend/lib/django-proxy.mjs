// Relais vers une seule API configurée ; aucun accès direct à la base.
const hopHeaders = ['connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'content-length'];
export function apiOrigin(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error('DJANGO_API_URL invalide.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('DJANGO_API_URL doit être une origine HTTP(S), sans chemin ni identifiants.');
  return url.origin;
}
export async function forwardToDjango(request, origin, maxBodyBytes = 16 * 1024 * 1024) {
  const incoming = new URL(request.url);
  if (!incoming.pathname.startsWith('/api/')) return Response.json({detail:'Route API invalide.'},{status:400});
  const target = new URL(incoming.pathname + incoming.search, apiOrigin(origin));
  const headers = new Headers(request.headers);
  // Supprime aussi les champs désignés comme propres à cette connexion.
  for (const name of (headers.get('connection') || '').split(',')) if (name.trim()) headers.delete(name.trim());
  for (const name of hopHeaders) headers.delete(name);
  headers.delete('cookie');
  headers.set('connection', 'close'); // Django runserver ferme ses connexions HTTP.
  headers.set('accept-encoding', 'identity');
  // WSGI/runserver exige une longueur connue pour lire les formulaires.
  // Borne la lecture avant de remettre le corps à fetch, qui calcule Content-Length.
  let body;
  if (!['GET', 'HEAD'].includes(request.method) && request.body) {
    const reader = request.body.getReader();
    const chunks = []; let size = 0;
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBodyBytes) {
        await reader.cancel();
        return Response.json({detail:'Envoi trop volumineux pour le serveur web.'},{status:413});
      }
      chunks.push(value);
    }
    body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  }
  try {
    const upstream = await fetch(target, {
      method: request.method, headers,
      body, redirect: 'manual', cache: 'no-store',
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(120000)]),
    });
    const resultHeaders = new Headers(upstream.headers);
    for (const name of hopHeaders) resultHeaders.delete(name);
    resultHeaders.delete('content-encoding');
    resultHeaders.set('cache-control', 'private, no-store');
    return new Response(upstream.body, {status:upstream.status, headers:resultHeaders});
  } catch {
    // Aucune réémission automatique : une écriture peut avoir abouti côté Django.
    return Response.json({detail:'Le serveur de gestion est indisponible. Vérifiez si l’opération a été enregistrée avant de réessayer.'},{status:502,headers:{'Cache-Control':'no-store'}});
  }
}
