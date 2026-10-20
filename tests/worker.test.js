import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../worker/index.js';

test('Worker serves frontend paths through its asset binding without gateway configuration', async () => {
  for (const path of ['/', '/static/app.js', '/static/style.css', '/missing.js']) {
    const request = new Request('https://smart.somas.ai' + path);
    const response = new Response(path, { status: path === '/missing.js' ? 404 : 200 });
    const actual = await worker.fetch(request, { ASSETS: { fetch: async received => {
      assert.equal(received, request);
      return response;
    } } });
    assert.equal(actual, response);
  }
});

test('Worker API uses the secured shared gateway and never falls back to HTML', async () => {
  let assetsCalled = false;
  const env = { ASSETS: { fetch: async () => { assetsCalled = true; return new Response('HTML'); } } };
  let response = await worker.fetch(new Request('https://smart.somas.ai/api/auth/me'), env);
  assert.equal(response.status, 503);
  assert.match(response.headers.get('content-type'), /application\/json/);
  response = await worker.fetch(new Request('https://smart.somas.ai/api'), env);
  assert.equal(response.status, 404);
  assert.equal(assetsCalled, false);
});

test('Worker forwards signed-out JSON status using the exact pinned backend', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(String(url), 'https://approved-api.vercel.app/api/auth/me');
    assert.equal(options.headers.get('X-Somas-Proxy-Secret'), 'test-worker-shared-secret-32-characters');
    assert.equal(options.headers.get('Cookie'), 'somas_session=opaque');
    return Response.json({ detail: 'Not authenticated' }, { status: 401 });
  };
  try {
    const response = await worker.fetch(new Request('https://smart.somas.ai/api/auth/me', {
      headers: { Cookie: 'somas_session=opaque' },
    }), {
      BACKEND_ORIGIN: 'https://approved-api.vercel.app',
      APPROVED_BACKEND_HOSTNAME: 'approved-api.vercel.app',
      SOMAS_PROXY_SECRET: 'test-worker-shared-secret-32-characters',
    });
    assert.equal(response.status, 401);
    assert.match(response.headers.get('content-type'), /application\/json/);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  } finally { globalThis.fetch = original; }
});
