const MAX_BODY = 32768;
const HOP = new Set(['connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length']);

function error(status, detail) {
  return Response.json({ detail }, { status, headers: { 'Cache-Control': 'no-store' } });
}

function backendOrigin(env) {
  const target = new URL(env.RENDER_BACKEND_ORIGIN);
  const local = env.ALLOW_LOCAL_BACKEND === '1' && target.protocol === 'http:' &&
    ['localhost', '127.0.0.1'].includes(target.hostname);
  if ((!local && (target.protocol !== 'https:' || !target.hostname.endsWith('.onrender.com'))) ||
      target.username || target.password || target.pathname !== '/' || target.search || target.hash ||
      (!local && target.port)) throw new Error('Invalid backend origin');
  if (!local && (!env.SOMAS_PROXY_SECRET || env.SOMAS_PROXY_SECRET.length < 32))
    throw new Error('Missing proxy secret');
  return target.origin;
}

export async function onRequest(context) {
  const { request, env } = context;
  const source = new URL(request.url);
  if (!source.pathname.startsWith('/api/')) return error(404, 'Not found');
  let origin;
  try { origin = backendOrigin(env); }
  catch { return error(503, 'API gateway is not configured'); }
  const unsafe = !['GET', 'HEAD', 'OPTIONS'].includes(request.method);
  const suppliedOrigin = request.headers.get('Origin');
  if ((suppliedOrigin && suppliedOrigin !== source.origin) || (unsafe && !suppliedOrigin) ||
      request.headers.get('Sec-Fetch-Site') === 'cross-site') return error(403, 'Origin is not allowed');
  if (Number(request.headers.get('Content-Length') || 0) > MAX_BODY) return error(413, 'Request body too large');
  // Construct the path on a fixed origin; neither a path nor query can select another host.
  const destination = new URL(origin);
  destination.pathname = source.pathname;
  destination.search = source.search;
  const headers = new Headers();
  for (const name of ['accept', 'content-type', 'cookie', 'authorization', 'origin', 'x-csrf-token', 'sec-fetch-site']) {
    if (request.headers.has(name)) headers.set(name, request.headers.get(name));
  }
  if (env.SOMAS_PROXY_SECRET) headers.set('X-Somas-Proxy-Secret', env.SOMAS_PROXY_SECRET);
  headers.set('X-Somas-Client-IP', request.headers.get('CF-Connecting-IP') || 'unknown');
  let body;
  if (unsafe && request.body) {
    const reader = request.body.getReader();
    const chunks = [];
    let length = 0;
    while (true) {
      const item = await reader.read();
      if (item.done) break;
      length += item.value.length;
      if (length > MAX_BODY) { await reader.cancel(); return error(413, 'Request body too large'); }
      chunks.push(item.value);
    }
    body = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.length; }
  }
  try {
    const upstream = await fetch(destination, {
      method: request.method, headers, body, redirect: 'manual',
      signal: AbortSignal.timeout(140000), cf: { cacheTtl: 0, cacheEverything: false },
    });
    if (upstream.status >= 300 && upstream.status < 400) return error(502, 'Unexpected backend redirect');
    const responseHeaders = new Headers();
    const connectionHeaders = new Set((upstream.headers.get('Connection') || '').toLowerCase().split(',').map(x => x.trim()));
    for (const [name, value] of upstream.headers) {
      if (!HOP.has(name.toLowerCase()) && !connectionHeaders.has(name.toLowerCase()) &&
          name.toLowerCase() !== 'set-cookie' && !name.toLowerCase().startsWith('access-control-')) {
        responseHeaders.append(name, value);
      }
    }
    const cookies = upstream.headers.getSetCookie ? upstream.headers.getSetCookie() : upstream.headers.getAll('Set-Cookie');
    for (const cookie of cookies) {
      if (/;\s*domain=/i.test(cookie)) return error(502, 'Invalid backend cookie');
      responseHeaders.append('Set-Cookie', cookie);
    }
    responseHeaders.set('Cache-Control', 'no-store');
    responseHeaders.set('CDN-Cache-Control', 'no-store');
    responseHeaders.set('Cloudflare-CDN-Cache-Control', 'no-store');
    responseHeaders.delete('Location');
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return error(503, 'Backend unavailable or waking up. Please retry shortly.');
  }
}
