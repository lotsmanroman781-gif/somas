# Deploy SOMAS v1.2 using free plans

Target: Cloudflare Pages Free frontend and Functions, Render Free Python web service, Neon Free PostgreSQL. Use the existing **private** GitHub repository. This guide prepares a research MVP deployment; it does not claim an audited production service or unlimited free capacity. No deployment is performed by these files.

## 1. Prepare and test locally

Install Python 3.12, Node 22, and Docker Desktop/Compose. From the repository root in PowerShell:

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
```

Tests create and drop only randomly named `somas_test_*` databases on the local test server. Do not point tests at a hosted or real-user database. The test role needs permission to create databases. A skipped database suite is not acceptance.

To run the browser through the actual local Pages proxy:

```powershell
$env:SOMAS_PROXY_SECRET='local-only-replace-with-a-random-32-character-secret'
$env:SOMAS_ALLOWED_ORIGINS='http://localhost:8788,http://127.0.0.1:8788'
python run.py
```

In a second terminal, run `Copy-Item .dev.vars.example .dev.vars` once, then `npm run dev`. Open `http://localhost:8788`. `.dev.vars` contains only the local Render-equivalent origin, a local-only gateway secret, and `ALLOW_LOCAL_BACKEND=1`. The frontend never needs the database URI or AI key.

Shell settings do not cross terminal windows automatically. `.env.example` is documentation; `.env` is not auto-loaded. On Unix, use `source .venv/bin/activate` and `export NAME='value'`. Keep `.env` and `.dev.vars` ignored.

## 2. Review and push the private source

The repository contains `frontend/` at the root, `functions/api/[[path]].js`, `render.yaml`, Alembic migrations and backend code. Do not create another Git repository or change visibility.

```powershell
git status --short
git diff --check
git diff --stat
git add app frontend functions migrations scripts tests .github .gitignore .env.example .dev.vars.example requirements.txt requirements-dev.txt package.json package-lock.json pytest.ini alembic.ini compose.yaml render.yaml run.py start_windows.bat start_mac_linux.sh README.md ARCHITECTURE.md RELEASE_NOTES.md GITHUB_PUBLISH.md DEPLOY_RENDER_CLOUDFLARE_NEON.md
git diff --cached --stat
git commit -m "Upgrade SOMAS v1.2 to PostgreSQL and Cloudflare Render deployment"
git push origin HEAD
```

Review staged files before committing. No `.env`, `.dev.vars`, credentials, SQLite files, exports or runtime data should appear. Push only when you choose to do so; these instructions are not authorization for an agent to push or publish.

## 3. Create Neon Free PostgreSQL

1. Sign in at [Neon](https://console.neon.tech/) and choose **New project**.
2. Confirm the **Free** plan. Choose a project name such as `somas`, a region near your planned Render region, and PostgreSQL 17 if offered. Do not select paid compute, paid retention, or other add-ons.
3. Use the default branch or a clearly named production branch. Create/use a database named `somas` and a database role with its own generated password. Keep database roles separate from SOMAS human accounts.
4. Open **Connect**. Select the branch, database, and role. Enable **Connection pooling** for the application's small pool. Copy the PostgreSQL connection string privately. Keep `sslmode=require` and `channel_binding=require` if provided.
5. Save the connection string in your password manager and later in **Render's `DATABASE_URL` secret**, never in Git, chat, the browser, Pages build variables, or source files. This app accepts `postgresql://` or `postgresql+psycopg://` and consistently uses psycopg 3.
6. Keep an unpooled/direct connection available privately for administration or backup. Alembic uses transaction-scoped locks rather than session locks so the supplied pooled URL works with the migration path; if Neon reports a migration/pooler-specific error, use the direct TLS URL as `DATABASE_URL` while migrating, then restore the pooled runtime URL.
7. Confirm the dashboard still shows Free. Neon usage quotas and UI can change: verify the [current Free plan](https://neon.com/pricing) and [connection documentation](https://neon.com/docs/get-started/connect-neon). Do not upgrade automatically when a quota is reached.

Neon can suspend idle compute. A database wake-up can add latency. Data persists independently of Render restarts. This setup needs neither a Render disk nor a second database. Do not configure MongoDB Atlas, D1, or Render Postgres for this release.

## 4. Create the Render Free backend

1. Sign in to [Render](https://dashboard.render.com/), use a free workspace, and select **New → Web Service**.
2. Connect GitHub, granting access only to the existing private `somas` repository. Select the branch you intend to deploy.
3. Choose **Python** as the runtime and **Free** as the instance plan. Set the repository root to the project root (blank or `.`).
4. Enter these settings. The same configuration is represented in `render.yaml` if you prefer a Blueprint; review its plan before creating anything.

| Setting | Value |
|---|---|
| Build command | `pip install -r requirements.txt` |
| Start command | `python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-proxy-headers --no-access-log` |
| Health check path | `/readyz` |
| Instance type | Free |
| Python version | `3.12.10` via `PYTHON_VERSION` |
| Persistent disk | None |

5. Add these **backend** environment variables:

| Variable | Value / secrecy |
|---|---|
| `DATABASE_URL` | Private Neon TLS connection URI; secret |
| `PYTHON_VERSION` | `3.12.10` |
| `SOMAS_SECURE_COOKIES` | `1` |
| `SOMAS_ALLOW_PUBLIC_SIGNUP` | `false` during setup; explicitly set `true` for the final registration smoke test/public signup |
| `SOMAS_ALLOWED_ORIGINS` | Exact intended frontend origin, e.g. `https://YOUR-PROJECT.pages.dev`; no trailing slash or wildcard |
| `SOMAS_PROXY_SECRET` | Generate once with `python -c "import secrets; print(secrets.token_urlsafe(48))"`; save privately; same value on Pages |
| `OPENAI_API_KEY` | Leave unset for free demo mode |
| `OPENAI_MODEL` | Optional; only needed with an AI key |

6. Create the Free web service. Initial setup might fail if credentials or the intended frontend origin are not yet set. Fix configuration and retry; do not add a paid database or disk.
7. Record the backend HTTPS origin, e.g. `https://YOUR-SERVICE.onrender.com`. It must be the origin only, with no `/api` suffix, query, credentials or path.
8. Check `https://YOUR-SERVICE.onrender.com/healthz` and `/readyz`. Expected JSON statuses are `ok` and `ready`. Direct `/api/auth/me` should return **403 gateway required** without the proxy secret. That is intentional.

The startup command applies transactional Alembic migrations before binding `$PORT`. Future releases must add new migrations, not modify the frozen initial revision or recreate tables. Startup migration privileges are required for the configured database role. A separately privileged migration role and restricted runtime role are a future hardening option.

Render's Free service has an ephemeral filesystem, sleeps after about 15 minutes without inbound traffic, and may take about a minute to wake. It has monthly shared Free instance-hour limits and can restart. It is not a background worker or a guarantee of continuous agent work. See [Render Free limits](https://render.com/docs/free). Do not configure paid instances, persistent disks, cron jobs or an automatic upgrade. If a provider requests payment/card verification, stop and review the account requirements rather than authorizing a charge.

## 5. Create Cloudflare Pages Free and its API proxy

1. In [Cloudflare](https://dash.cloudflare.com/), open **Workers & Pages → Create application → Pages → Connect to Git**. Choose Pages (not a Python Worker or a static-only drag-and-drop upload).
2. Authorize access only to the private `somas` GitHub repository. Select it and the intended production branch.
3. Choose a project name and these build settings:

| Setting | Value |
|---|---|
| Framework preset | None |
| Root directory | Repository root; leave blank or `/` |
| Build command | `exit 0` |
| Build output directory | `frontend` |
| Functions source | Root-level `functions/` (automatically discovered) |
| Plan | Free |

4. Configure **Settings → Variables and Secrets** for the production environment:

| Pages Function variable | Value |
|---|---|
| `RENDER_BACKEND_ORIGIN` | `https://YOUR-SERVICE.onrender.com` |
| `SOMAS_PROXY_SECRET` | Secret; exactly the same random value configured on Render |
| `NODE_VERSION` | `22` for tooling/build compatibility |

Do **not** configure `DATABASE_URL`, Neon credentials, or `OPENAI_API_KEY` in Pages. Do not set `ALLOW_LOCAL_BACKEND` in the cloud. That switch exists only for local HTTP development. The Pages origin itself is not a secret; the gateway secret is.

5. Save and deploy/redeploy the Pages project. `frontend/_routes.json` routes only `/api/*` through the Function, so static assets do not consume Function calls. `frontend/_headers` sets CSP and related browser headers.
6. Confirm the assigned URL matches Render's `SOMAS_ALLOWED_ORIGINS` exactly. Add any custom frontend domain as an explicit comma-separated origin on Render; no wildcard or arbitrary preview origins. Production backend credentials should not be supplied automatically to untrusted preview branches.
7. Open `https://YOUR-PROJECT.pages.dev/static/app.js` and `/static/style.css`; both must load. `/api/auth/me` must return a JSON **401** for a signed-out user, not HTML, 404, or a gateway 403. A deployed frontend alone does not pass acceptance.

Pages Functions requests count against Workers Free usage limits. Keep the Free plan and monitor the [Functions pricing/quotas](https://developers.cloudflare.com/pages/functions/pricing/). No paid Workers plan, custom domain purchase, or edge database is required.

## 6. Full Alice/Bob persistence smoke test

Enable `SOMAS_ALLOW_PUBLIC_SIGNUP=true` on Render when you intentionally want registration available. Use synthetic data until launch requirements are addressed.

1. Open the final **Cloudflare** URL. In browser Network tools, confirm API requests target that same origin; no browser request should target Render or Neon.
2. Register Alice. Confirm the `somas_session` cookie is HttpOnly, Secure, SameSite=Strict, Path=/, with no Domain override. The UI should enter Alice's private workspace.
3. Design a demo organization. Record its ID, agent IDs and policy versions. Run demo drafts. Verify they are visibly simulated.
4. Submit a verified Manager capability correction and train one specialist strategy. Confirm policy versions increase; unverified feedback must not change weights.
5. Log out. Confirm `/api/auth/me` returns 401. Register Bob. Bob's organization and specialist lists must be empty and his Manager version untrained.
6. Try Alice's saved organization ID from Bob's authenticated session using the organization's details, export, run and feedback endpoints. Each must return 404. Inspect the automated tests for exact request examples; writes require Bob's current CSRF header.
7. Sign Bob out. Restart the Render backend with **Manual Deploy → Deploy latest commit** or its restart control. Wait for `/readyz`. Do not reset Neon or change `DATABASE_URL`.
8. Sign Alice back in and verify her org, runs, Manager version and specialist weights/versions remain. The app's automated persistence test also compares exact NumPy matrices and reads binary weights from a separate process.
9. Change Alice's password. All previous sessions should become unauthorized; the old password must fail, and the new password must work.
10. Remove the CSRF header from a cookie-authenticated write; expect 403. Sending an Origin from another site must also fail. None of these requests should disclose database errors or credentials.

The automated proxy roundtrip runs the same Pages Function module against a live local FastAPI/PostgreSQL backend. With `SOMAS_TEST_PAGES_RUNTIME=1`, a separate test also starts the actual Wrangler/workerd runtime and verifies static paths and authenticated requests. On Windows, install the official Microsoft Visual C++ runtime if workerd cannot start. Local checks and the final hosted browser smoke test are distinct; record which were actually executed.

## 7. Import existing v1.1 SQLite data

Back up the original SQLite file and stop its server. Stop writes to the target backend while importing; repeating an import into records that have since changed deliberately fails verification. Configure `DATABASE_URL` privately in an administrative shell, remove `SOMAS_DB`, apply Alembic, then run:

```powershell
python -m alembic upgrade head
python scripts/migrate_sqlite_to_postgresql.py path/to/somas_users.db --dry-run
python scripts/migrate_sqlite_to_postgresql.py path/to/somas_users.db --apply
python scripts/migrate_sqlite_to_postgresql.py path/to/somas_users.db --verify
```

Dry-run performs no PostgreSQL writes. Apply is transactional and repeatable; verify compares source-derived fields and binary policies. No record is assigned to a different human. Unowned v1.0 databases are rejected. Password/session hashes and current neural-policy versions are preserved. Missing historical policy versions cannot be reconstructed. Imports beyond 10,000 derived rows need reviewed batching. Source files and exports stay out of Git.

## Troubleshooting and remaining launch work

- **Render build/start fails:** verify Python version, installed requirements, a TLS PostgreSQL `DATABASE_URL`, database permissions and current Alembic revision. Never paste a full URI into logs/issues. An old SQLite or MongoDB variable does not configure this release.
- **503 readiness or database connection failure:** confirm the Neon branch/compute is available, password is current, hostname resolves, TLS parameters remain present, and compute/connection quotas are not exceeded. The app uses a small connection pool with pre-ping; retry after a cold start. Do not turn off TLS to resolve a remote error.
- **403 gateway:** check both copies of `SOMAS_PROXY_SECRET`. Browser requests must pass through Pages Functions; direct calls to Render are deliberately restricted.
- **403 Origin:** fix Render's exact origin allowlist (scheme + hostname + optional port, no trailing slash). Do not enable wildcard credentialed CORS.
- **Login succeeds but session disappears:** check Secure cookies, proxy Set-Cookie headers and same-origin routing. Do not add a cookie Domain pointing at Render. Keep browser requests relative.
- **503/HTML on first visit:** Render may be waking. The UI provides a retry message. Do not automatically repeat writes; check organization/run history before retrying an interrupted request.
- **409 training:** another correction updated the same policy. Reload the current state and reapply the intended verified correction. The winning update is preserved.
- **429:** a durable login/signup/account limit was reached. Honor `Retry-After`; do not disable protections for a public launch.
- **Free database grows:** monitor snapshots, runs and audit histories and plan retention/export deliberately. This release does not silently delete training history.

Email verification, password recovery, shared invitations and an independent security audit are still absent. Configure and validate a real email provider before offering verification/recovery; none is invented or bundled. Free hosting is appropriate for a research MVP with known availability/resource limits, not a promise of worldwide production capacity. Leave AI keys unset unless you deliberately accept external API charges.
