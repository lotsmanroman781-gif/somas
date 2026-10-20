# Existing somasai Worker: frontend and secure API gateway

Use this guide for the existing **somasai** Worker at **https://smart.somas.ai**. Vercel/FastAPI and Neon remain unchanged. The earlier Pages setup is an alternative deployment mode; Pages Functions are not automatically executed by `wrangler deploy`.

## Configuration and runtime variables

`wrangler.json` selects Worker `somasai`, entrypoint `worker/index.js`, static assets `frontend/` bound as `ASSETS`, and the existing custom domain `smart.somas.ai`. `/api` and `/api/*` run the Worker first; other paths use static asset routing. `/` serves `index.html`; missing assets return 404 instead of an HTML fallback. The Worker imports the existing Pages proxy, preserving its destination pin, secret validation, Origin/CSRF/cookie forwarding, request body limit, redirect rejection and no-store response headers. `frontend/_headers` applies security headers to static assets.

In **Cloudflare → Workers & Pages → somasai → Settings → Variables and Secrets**, configure these as **Worker runtime bindings**, not only build-system variables:

| Name | Type | Exact value |
|---|---|---|
| `BACKEND_ORIGIN` | Text | Your existing working Vercel production origin, e.g. `https://YOUR-API.vercel.app`; no path/query/credentials |
| `APPROVED_BACKEND_HOSTNAME` | Text | The exact same hostname, e.g. `YOUR-API.vercel.app`; no scheme/path |
| `SOMAS_PROXY_SECRET` | Secret | The existing secret configured on Vercel, identical byte for byte; at least 32 characters |

The actual Vercel hostname was not supplied, so no destination is invented or committed. Missing/mismatched variables produce JSON 503. `keep_vars: true` preserves dashboard text variables during Wrangler deployments; secrets are never committed in configuration. Do not set `ALLOW_LOCAL_BACKEND`, `DATABASE_URL`, Neon credentials or `OPENAI_API_KEY` on the deployed Worker. `ASSETS` is supplied by Wrangler, not a manually entered text variable. Node 22 is a build-tool setting, not an API secret.

Vercel's existing allowed-origin configuration must accept `https://smart.somas.ai` for browser writes. A backend 403 Origin response needs an allowlist review by the backend operator; this frontend fix does not change the working backend. Neither runtime variable contains the frontend domain: `BACKEND_ORIGIN` and its pin both identify Vercel.

## Existing Worker build settings

| Setting | Value |
|---|---|
| Project / Worker | Existing `somasai`; do not create another |
| Branch | `main` |
| Root directory | Repository root |
| Build command | `npm ci` (no frontend compilation needed) |
| Deploy command | `npx wrangler deploy` |
| Configuration | Root `wrangler.json` |
| Static assets | `frontend/` |
| Custom domain | Existing `smart.somas.ai`, retained in configuration |
| Hosting | Workers Free; no paid plan or additional service |

Keep the current custom domain attached to this Worker; do not delete DNS/domain mappings or switch to a Pages project. Publishing a commit can trigger the already connected Workers build. No direct cloud deployment is needed from a local agent.

## Local checks

```powershell
npm ci
npm test
npx wrangler deploy --dry-run --outdir .wrangler/worker-build
```

The dry run bundles locally and does not publish. To run locally, copy `.dev.vars.example` to ignored `.dev.vars` once, start the local FastAPI backend as described in README, and run `npm run dev`. Open `http://localhost:8788`. The local-only loopback flag in `.dev.vars` permits HTTP development. The Pages proxy source is retained and tested in an isolated Pages project; the repository's root Wrangler configuration now targets Workers.

The existing PostgreSQL integration suite now tests both actual Pages and Worker runtimes when `SOMAS_TEST_PAGES_RUNTIME=1` is set. Use only a disposable loopback PostgreSQL server:

```powershell
$env:SOMAS_TEST_DATABASE_URL='postgresql://somas:local-development-only@127.0.0.1:5432/postgres'
$env:SOMAS_TEST_PAGES_RUNTIME='1'
python -m pytest -q
```

Tests check `/`, JavaScript/CSS assets, signed-out JSON 401, registration/session cookies, CSRF, profile changes and logout through the actual Worker. The shared proxy contracts also cover destination/Origin rejection, body limits, cookie forwarding, redirects and sanitized failures. No schema change or hosted database operation is part of this fix.

Recorded local validation: **45 Python tests passed**, including actual local Worker and Pages runtimes with disposable PostgreSQL; **nine standalone JavaScript tests passed**, with their optional live case exercised by Python integration. Wrangler's official configuration schema, deploy dry run, retained Pages compilation, Ruff and formatting passed. The Worker JavaScript bundle was 4.91 KiB before compression, plus six frontend asset files. Read-only live requests to the four URLs below failed to connect from this environment; hosted success has not been verified.

## Hosted acceptance after the connected deployment

Check the deployed main commit in Workers Builds, then request these exact URLs:

| URL | Expected |
|---|---|
| `https://smart.somas.ai/` | 200 HTML containing the SOMAS interface |
| `https://smart.somas.ai/static/app.js` | 200 JavaScript |
| `https://smart.somas.ai/static/style.css` | 200 CSS |
| `https://smart.somas.ai/api/auth/me` | 401 JSON when signed out |

Browser requests must remain on `smart.somas.ai`. Verify login/logout and secure HttpOnly SameSite cookies through the browser after read-only checks pass. Never expose the gateway secret in browser code. JSON 503 means missing gateway config or an upstream failure; 403 may mean mismatched secrets or backend Origin restrictions. HTML from an API path indicates a stale/wrong deployment or routing configuration. Do not treat a successful build or local test as proof the live website works.

References: [Workers static asset bindings](https://developers.cloudflare.com/workers/static-assets/binding/) and [Worker-first routing](https://developers.cloudflare.com/workers/static-assets/routing/advanced/).
