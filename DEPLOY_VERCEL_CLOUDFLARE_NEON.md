# Deploy SOMAS v1.3 on personal Free plans

Architecture: Cloudflare Pages and Pages Functions → native Vercel Python/FastAPI → Neon PostgreSQL. Use the existing private GitHub repository. Vercel Hobby is intended here for personal, non-commercial development. Do not select paid plans or paid add-ons. No deployment or hosted migration has been performed by these source changes.

## 1. Local validation

Install Python 3.12, Node 22 and Docker Desktop/Compose. From the repository root in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci
docker compose up -d --wait
$env:DATABASE_URL='postgresql://somas:local-development-only@127.0.0.1:5432/somas'
python -m alembic upgrade head
$env:SOMAS_TEST_DATABASE_URL='postgresql://somas:local-development-only@127.0.0.1:5432/postgres'
$env:SOMAS_TEST_PAGES_RUNTIME='1'
python -m pytest -q
npm test
python -m pip install -r requirements.txt --target .vercel-check/vendor
python scripts/check_vercel_bundle.py
```

Tests create/drop randomly named `somas_test_*` databases only on loopback. Never point tests at Neon or a real-user database. A skipped database suite is not acceptance. The bundle preflight measures staged runtime dependencies and imports NumPy, psycopg and FastAPI; CI repeats this on Linux/Python 3.12. Vercel's own final bundle report must still be checked before launch.

Recorded local validation (October 21, 2026): 44 Python tests passed with PostgreSQL 17.5 and real Wrangler/workerd enabled; six standalone JavaScript proxy contracts passed, with the optional live case covered by Python integration. Pages compilation, Ruff and formatting passed. A clean Windows/Python 3.12 runtime staging directory plus application measured **106.1 MiB uncompressed** and passed NumPy/psycopg/FastAPI imports. This measures local dependencies, not an actual Linux Vercel artifact; Linux CI and hosted acceptance have not been executed from this workspace.

To use the local Cloudflare proxy:

```powershell
$env:SOMAS_PROXY_SECRET='local-only-replace-with-a-random-32-character-secret'
$env:SOMAS_ALLOWED_ORIGINS='http://localhost:8788,http://127.0.0.1:8788'
python run.py
```

In another terminal, run `Copy-Item .dev.vars.example .dev.vars` once, then `npm run dev`. Open `http://localhost:8788`. Local `ALLOW_LOCAL_BACKEND=1` permits only loopback HTTP; never configure that variable in the cloud. `.env` is not automatically loaded. Shell variables do not cross terminal windows. On Unix use `source .venv/bin/activate` and `export NAME='value'`.

## 2. Neon Free database and schema

Keep the existing Neon Free project/database. No new database is needed for v1.3. In **Connect**, select the intended branch, database and role, enable **Connection pooling**, and privately copy its TLS URI. The host must look like `ep-YOUR-ENDPOINT-pooler.REGION.aws.neon.tech`. Keep `sslmode=require` and `channel_binding=require` when provided. Both `postgresql://` and `postgresql+psycopg://` work; the code consistently selects psycopg 3. Never share the URI in logs, Git, chat or Pages variables.

Set `DATABASE_URL` privately in your administrative shell, then check connectivity without modifying data:

```powershell
python scripts/check_database.py
```

Review the migrations and confirm this is your intended SOMAS database before initializing it:

```powershell
python -m alembic upgrade head
python scripts/check_database.py --schema
```

Expected schema revision remains `0001_v12`. v1.3 does not change the relational schema. Existing v1.2 accounts, sessions, organizations, histories and weights remain in place. Never delete tables, reset Neon, or use `alembic stamp` to bypass validation. For a database with unrelated conflicting tables, use a dedicated database/branch first. Make a reviewed backup before future schema changes. Use a direct TLS URL privately for administrative tools if needed; runtime Vercel requires the pooled URL.

### Optional reviewed GitHub migration workflow

`.github/workflows/migrate-database.yml` runs **only** through `workflow_dispatch`, on `main` in `lotsmanroman781-gif/somas`. It has no push/PR/deployment trigger. Ordinary Vercel builds and requests never migrate.

1. Review the exact commit and migrations on `main`, the intended Neon branch/database, and your backup.
2. In repository **Settings → Secrets and variables → Actions**, add encrypted repository secret `NEON_MIGRATION_DATABASE_URL`. Use the privately held TLS migration-role URI. Only the upgrade step receives it. Do not supply it to preview builds or PR workflows.
3. Add repository Actions variable `SOMAS_MIGRATIONS_ENABLED=true` only when ready to run the reviewed upgrade.
4. Open **Actions → Reviewed Neon schema migration → Run workflow**, select `main`, paste its full 40-character reviewed commit SHA and choose `reviewed-upgrade-head`. A mismatched SHA aborts before credential access. Review the run result, then disable the switch again.

This uses an encrypted repository secret and an explicit human dispatch/review gate. **It does not implement independent required-reviewer approval.** GitHub Free private repositories may not provide protected-environment secrets/required reviewers; do not buy a plan to enable them. If independent approval is mandatory, leave this workflow disabled and use your reviewed local administrative procedure instead. Restrict repository write access and review workflow/dependency changes: maintainers who can change trusted workflows can change their safeguards. GitHub private Actions has account usage quotas; do not enable paid overages. See [GitHub environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

## 3. Vercel Hobby backend

After reviewing and committing the source, import the existing private GitHub repository into a **personal Vercel Hobby** project. Do not purchase a team plan. The backend uses the existing exported `app` in `app/main.py`; there is no second FastAPI application, custom adapter, `api/index.py`, or Uvicorn server command to configure.

| Vercel setting | Exact value |
|---|---|
| Plan / use | Hobby; personal non-commercial development |
| Framework preset | FastAPI |
| Root directory | Repository root (`.`) |
| Production branch | `main` |
| Python | `3.12`, selected by committed `.python-version` |
| Build command | Default; leave override OFF |
| Install command | Default; runtime dependencies from `requirements.txt` |
| Output directory | Default; leave override OFF |
| Start command | None; native Python Functions invoke `app/main.py` |
| Fluid compute | Enabled (native FastAPI default); required for the configured 180-second duration |
| Function duration | `180` seconds in `vercel.json` |

Use production environment variables below. Do not automatically share production secrets with untrusted preview branches. Before deploying code with new schema revisions, run the reviewed migration separately; the function fails startup on a mismatched schema.

| Vercel production variable | Value |
|---|---|
| `DATABASE_URL` | Secret Neon **pooled** TLS PostgreSQL URI |
| `SOMAS_PROXY_SECRET` | Secret random string of at least 32 characters; identical on Pages |
| `SOMAS_ALLOWED_ORIGINS` | Exact Cloudflare website origin, e.g. `https://YOUR-PAGES.pages.dev`; no trailing slash or wildcard |
| `SOMAS_SECURE_COOKIES` | `1` |
| `SOMAS_ALLOW_PUBLIC_SIGNUP` | `false` during setup; explicitly set `true` when registration should be available |
| `OPENAI_API_KEY` | Leave unset for free demo mode |
| `OPENAI_MODEL` | Optional; only relevant when deliberately enabling a funded AI API |

Generate the gateway secret privately, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`; store it securely and never commit it. Vercel supplies `VERCEL=1` automatically; do not copy local `.env.example` wholesale. No `PORT`, `PYTHON_VERSION`, persistent disk or worker is needed.

Record the project's stable **production** hostname, e.g. `YOUR-API.vercel.app`. Choose that exact hostname as the approved API destination. Never use a wildcard or per-commit preview hostname. Requests must reach the production function without an interactive Vercel sign-in page; the application itself enforces its gateway secret on `/api/*`. If platform deployment protection blocks Cloudflare, review production access settings deliberately. No deployment-protection bypass secret is implemented.

Check `https://YOUR-API.vercel.app/healthz` and `/readyz` for `ok` and `ready`. Calling `/api/auth/me` directly without the gateway secret should return JSON **403 gateway required**. `/` returns API metadata on Vercel; Cloudflare hosts the dashboard. Native lifespan startup checks database schema; shutdown disposes connections. There is no automatic DDL at import, startup, build or request time.

### Serverless connection and resource limits

Vercel uses SQLAlchemy `NullPool`: every completed transaction closes its client connection back to Neon's external pooler. Prepared statements are disabled for pooler compatibility. No idle process pool is multiplied across warm functions; global concurrency still consumes pooler clients, so monitor Neon quotas. Local development retains the bounded pool (3 + 2 overflow). Sessions, rate limits, policy weights and histories stay in PostgreSQL, with no filesystem persistence.

All training/execution and database writes are awaited before the response. No background worker or process survival is assumed. Requests have a 130-second application deadline, 140-second gateway timeout and 180-second Vercel duration. Free quotas/cold starts can still interrupt work; check run history before repeating writes. There is no guarantee of continuous agent work or unlimited public capacity.

The Python function has a 500 MB uncompressed bundle limit. `.vercelignore` and `excludeFiles` omit Node dependencies, frontend assets, tests, docs, migration/admin files, caches and local secrets. Only runtime dependencies and backend code are needed. The preflight rejects staged runtime size at 450 MB, leaving adapter headroom. Check the final Vercel build report, especially after dependency changes. Do not solve a bundle or duration failure by upgrading to a paid plan.

Official references: [native FastAPI and lifespan](https://vercel.com/docs/frameworks/backend/fastapi), [Python runtime](https://vercel.com/docs/functions/runtimes/python), [function duration](https://vercel.com/docs/functions/configuring-functions/duration), [Hobby plan](https://vercel.com/docs/plans/hobby). Confirm current account limits before deployment.

## 4. Cloudflare Pages Free frontend and gateway

Connect the same private repository using **Workers & Pages → Pages → Connect to Git**. Keep the Free plan.

| Pages setting | Value |
|---|---|
| Framework preset | None |
| Root directory | Repository root; leave blank |
| Build command | `exit 0` |
| Build output directory | `frontend` |
| Functions source | Root `functions/`, automatically discovered |
| Production branch | `main` |

Configure these **production** Function bindings, then redeploy Pages:

| Pages variable | Value |
|---|---|
| `BACKEND_ORIGIN` | `https://YOUR-API.vercel.app` (origin only; no path/query/credentials) |
| `APPROVED_BACKEND_HOSTNAME` | `YOUR-API.vercel.app` (exact same hostname; no scheme/path) |
| `SOMAS_PROXY_SECRET` | Secret; exactly matches Vercel |
| `NODE_VERSION` | `22` |

Remove the old `RENDER_BACKEND_ORIGIN` binding. Do not configure `DATABASE_URL`, Neon credentials, `OPENAI_API_KEY` or `ALLOW_LOCAL_BACKEND` on hosted Pages. The proxy accepts only the pinned HTTPS `.vercel.app` destination, rejects redirects and unapproved destinations, and forwards cookies/CSRF without exposing the gateway secret to the browser. Both origin and hostname settings must match; missing/mismatched bindings return 503 without fetching.

Update Vercel's `SOMAS_ALLOWED_ORIGINS` to this exact Pages origin, **not** the Vercel hostname. Add a custom frontend domain only as an explicitly reviewed additional origin. Do not grant production credentials to arbitrary preview branches. Browser API requests remain relative `/api/*`; no browser request should go to Vercel or Neon. `frontend/_routes.json` sends only API paths through Functions; static headers include CSP. Monitor [Pages Functions Free quotas](https://developers.cloudflare.com/pages/functions/pricing/).

When replacing an existing Render deployment, keep its database unchanged, migrate configuration to Vercel, then update the Pages bindings and redeploy. Once the final smoke test succeeds, stop the old backend to avoid two application versions writing simultaneously. Existing browser sessions survive if the same database and Pages origin remain; gateway-secret changes must be coordinated on both ends.

## 5. Hosted acceptance checklist

These checks require your explicit deployment; local tests do not establish hosted acceptance.

1. Load `/static/app.js` and `/static/style.css` on Pages. Signed-out `/api/auth/me` must return JSON 401, not HTML, 403 or 404.
2. Intentionally enable signup on Vercel. Register synthetic Alice through Pages. Confirm `somas_session`: HttpOnly, Secure, SameSite=Strict, Path=/, no Domain override. All browser requests use the Pages origin.
3. Create an organization in demo mode; run its simulated drafts. Record organization/agent IDs. Submit verified Manager and specialist feedback and confirm policy versions increase. Unverified feedback must not train.
4. Log out and register Bob. His organizations/specialists are empty and his Manager is independent. Alice's organization detail/export/run/feedback IDs must return 404 from Bob's session (writes include Bob's CSRF token).
5. Sign Alice in again. Redeploy/restart the Vercel function without modifying Neon, then confirm her current session, organizations, runs and trained policies remain. Local tests additionally compare exact weight matrices after a fresh lifespan.
6. Remove CSRF from a cookie-authenticated write: expect 403. Send an unrelated Origin: expect 403. Direct API access without the gateway secret remains 403. Change Alice's password and confirm old sessions/password fail.
7. Verify Vercel build size, duration, cold-start behavior and provider quota dashboards. Keep AI keys unset. Record actual results; do not claim a hosted smoke test from local ASGI/Wrangler tests alone.

## Troubleshooting and existing launch limitations

- **503 gateway:** check `BACKEND_ORIGIN`, exact `APPROVED_BACKEND_HOSTNAME`, and both gateway-secret values. A hostname mismatch deliberately fails closed. Remove the legacy Render variable.
- **503/startup failure:** confirm Neon pooled TLS URI and revision `0001_v12`. Run the private read-only checker locally. Apply reviewed schema changes separately; never add migrations to Vercel build/start commands.
- **HTML/redirect response:** verify the chosen stable production domain and Vercel access settings. Redirects are rejected; do not point the gateway at a login page or preview alias.
- **403 Origin/cookie problems:** allow the exact Pages origin on Vercel, keep Secure cookies, and use same-origin browser calls. Never set a cookie Domain pointing at the backend.
- **409 training:** reload the latest policy before applying the intended verified correction. The winning update is preserved.
- **429/quota/timeouts:** honor Retry-After and inspect history before retrying writes. Do not disable protections or enable paid overages automatically.

The v1.1 SQLite importer remains an explicit offline administrative utility; see README for dry-run/apply/verify commands. It is excluded from the function bundle. Email verification, password recovery, shared invitations and an independent security audit remain absent. This is a research deployment, not a claim of audited production security, worldwide availability, real external business actions, or benchmark superiority.
