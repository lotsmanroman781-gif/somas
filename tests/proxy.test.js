import test from 'node:test';
import assert from 'node:assert/strict';
import { onRequest } from '../functions/api/[[path]].js';

const secret = 'test-proxy-secret-32-characters-long';
const env = { RENDER_BACKEND_ORIGIN: 'https://somas-api.onrender.com', SOMAS_PROXY_SECRET: secret };
const request = (path = '/api/auth/me', options = {}) => new Request(`https://somas.test${path}`, options);
const invoke = (req, overrides = {}) => onRequest({ request: req, env: { ...env, ...overrides } });

test('forwards method, query, body, cookies and CSRF to fixed backend; preserves cookies', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url.href, 'https://somas-api.onrender.com/api/auth/login?next=https://evil.test');
    assert.equal(options.method, 'POST');
    assert.equal(new TextDecoder().decode(options.body), '{"hello":"world"}');
    assert.equal(options.headers.get('Cookie'), 'somas_session=opaque');
    assert.equal(options.headers.get('X-CSRF-Token'), 'csrf');
    assert.equal(options.headers.get('X-Somas-Proxy-Secret'), secret);
    assert.equal(options.headers.get('X-Forwarded-Host'), null);
    assert.equal(options.redirect, 'manual');
    const headers = new Headers({ 'Content-Type': 'application/json', 'Cache-Control': 'public' });
    headers.append('Set-Cookie', 'somas_session=new; HttpOnly; Secure; SameSite=Strict; Path=/');
    headers.append('Set-Cookie', 'second=ok; HttpOnly; Secure; SameSite=Strict; Path=/');
    return new Response('{"ok":true}', { status: 201, headers });
  };
  try {
    const response = await invoke(request('/api/auth/login?next=https://evil.test', {
      method: 'POST', headers: { Origin: 'https://somas.test', Cookie: 'somas_session=opaque',
        'X-CSRF-Token': 'csrf', 'X-Somas-Proxy-Secret': 'forged', 'X-Forwarded-Host': 'evil.test' },
      body: '{"hello":"world"}',
    }));
    assert.equal(response.status, 201);
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
    assert.equal(response.headers.getSetCookie().length, 2);
    assert.deepEqual(await response.json(), { ok: true });
  } finally { globalThis.fetch = original; }
});

test('rejects cross-origin and missing-origin writes', async () => {
  assert.equal((await invoke(request('/api/auth/login', { method: 'POST' }))).status, 403);
  assert.equal((await invoke(request('/api/auth/login', { method: 'POST', headers: { Origin: 'https://evil.test' } }))).status, 403);
});

test('rejects arbitrary destinations and incomplete configuration', async () => {
  for (const origin of ['https://evil.test', 'http://somas-api.onrender.com', 'https://somas-api.onrender.com/path',
    'https://user:pass@somas-api.onrender.com', 'https://somas-api.onrender.com?x=1']) {
    assert.equal((await invoke(request(), { RENDER_BACKEND_ORIGIN: origin })).status, 503);
  }
  assert.equal((await invoke(request(), { SOMAS_PROXY_SECRET: '' })).status, 503);
  assert.equal((await invoke(request('/static/app.js'))).status, 404);
});

test('bounds bodies including streams without content-length', async () => {
  const response = await invoke(request('/api/auth/login', {
    method: 'POST', headers: { Origin: 'https://somas.test' }, body: 'x'.repeat(32769),
  }));
  assert.equal(response.status, 413);
});

test('blocks redirects, strips hop headers, and sanitizes network failures', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(null, { status: 302, headers: { Location: 'https://evil.test' } });
    assert.equal((await invoke(request())).status, 502);
    globalThis.fetch = async () => new Response('{}', { headers: { Connection: 'X-Secret', 'X-Secret': 'private',
      'Access-Control-Allow-Origin': '*', 'Transfer-Encoding': 'chunked' } });
    const response = await invoke(request());
    assert.equal(response.headers.get('X-Secret'), null);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), null);
    assert.equal(response.headers.get('Transfer-Encoding'), null);
    globalThis.fetch = async () => { throw new Error('secret URI'); };
    const failure = await invoke(request());
    assert.equal(failure.status, 503);
    assert.ok(!(await failure.text()).includes('secret URI'));
  } finally { globalThis.fetch = original; }
});

test('rejects upstream cookies with Domain override', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response('{}', { headers: { 'Set-Cookie': 'somas_session=a; Domain=onrender.com' } });
  try { assert.equal((await invoke(request())).status, 502); }
  finally { globalThis.fetch = original; }
});

test('live same-origin proxy cookie, CSRF, isolation and logout roundtrip', {
  skip: !process.env.SOMAS_E2E_BACKEND,
}, async () => {
  const localEnv = { RENDER_BACKEND_ORIGIN: process.env.SOMAS_E2E_BACKEND, ALLOW_LOCAL_BACKEND: '1',
    SOMAS_PROXY_SECRET: process.env.SOMAS_E2E_SECRET };
  let cookie = '', csrf = '';
  async function api(path, method = 'GET', data, includeCsrf = true) {
    const headers = { Origin: 'https://somas.test', 'Content-Type': 'application/json' };
    if (cookie) headers.Cookie = cookie;
    if (includeCsrf && csrf) headers['X-CSRF-Token'] = csrf;
    return onRequest({ request: request(path, { method, headers, body: data ? JSON.stringify(data) : undefined }), env: localEnv });
  }
  const password = 'long-e2e-test-password-99';
  const alice = await api('/api/auth/register', 'POST', { email: `alice-${Date.now()}@example.com`, display_name: 'Alice', password });
  assert.equal(alice.status, 201);
  const setCookie = alice.headers.getSetCookie()[0];
  assert.match(setCookie, /HttpOnly/i); assert.match(setCookie, /Secure/i); assert.match(setCookie, /SameSite=strict/i);
  cookie = setCookie.split(';')[0]; csrf = (await alice.json()).csrf_token;
  assert.equal((await api('/api/auth/me')).status, 200);
  const business = { name: 'Proxy research', industry: 'Software', goal: 'Improve customer support and software quality', mode: 'demo' };
  assert.equal((await api('/api/organizations', 'POST', business, false)).status, 403);
  const created = await api('/api/organizations', 'POST', business);
  assert.equal(created.status, 201);
  const org = await created.json();
  assert.equal((await api(`/api/organizations/${org.id}/feedback`, 'POST', { score: 5,
    verified: true, correct_capabilities: ['quality'] })).status, 200);
  assert.equal((await api('/api/auth/profile', 'PATCH', { display_name: 'Alice Updated' })).status, 200);
  assert.equal((await api('/api/auth/logout', 'POST')).status, 200);
  assert.equal((await api('/api/auth/me')).status, 401);
  cookie = ''; csrf = '';
  const bob = await api('/api/auth/register', 'POST', { email: `bob-${Date.now()}@example.com`, display_name: 'Bob', password });
  assert.equal(bob.status, 201);
  cookie = bob.headers.getSetCookie()[0].split(';')[0]; csrf = (await bob.json()).csrf_token;
  assert.deepEqual(await (await api('/api/organizations')).json(), []);
  assert.equal((await api(`/api/organizations/${org.id}/export`)).status, 404);
});
