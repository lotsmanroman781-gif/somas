# SOMAS MVP v1.2

SOMAS (Self-Organizing Multi-Agent System) is a research application: a Manager designs a specialist team around a business objective. Each authenticated person owns a private Manager, organizations, specialists, independently trainable NumPy policies, draft runs, and training history.

The v1.2 deployment target is **Cloudflare Pages Free → Pages Functions `/api/*` → FastAPI on Render Free → PostgreSQL on Neon Free**. SQLAlchemy 2.x uses the async psycopg 3 driver throughout; Alembic owns schema changes. MongoDB and SQLite are not runtime databases.

The dashboard and v1.1 API contracts are preserved. Team design is not a fixed CEO/CTO/CFO chart: the Manager selects from the capability catalog. Demo outputs are simulated plans; optional AI outputs are unverified drafts. The system performs no external business actions.

## Local development

Prerequisites: Python 3.12, Node.js 22, and Docker with Compose (or a disposable PostgreSQL 17 server). No hosted database, paid API, or cloud account is needed locally.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci
docker compose up -d --wait
$env:DATABASE_URL = 'postgresql+psycopg://somas:local-development-only@127.0.0.1:5432/somas'
$env:SOMAS_PROXY_SECRET = 'local-only-replace-with-a-random-32-character-secret'
$env:SOMAS_ALLOWED_ORIGINS = 'http://localhost:8788,http://127.0.0.1:8788,http://localhost:8000,http://127.0.0.1:8000'
python -m alembic upgrade head
python run.py
```

In a second terminal at the repository root:

```powershell
Copy-Item .dev.vars.example .dev.vars
npm run dev
```

Open **http://localhost:8788**. Pages Functions forwards requests to `127.0.0.1:8000`; the browser uses only relative `/api/...` URLs. `.dev.vars` must contain the same proxy secret as the backend. Never use its example value in the cloud. A direct local dashboard also exists at `http://127.0.0.1:8000`, but when the gateway secret is set, use the proxy for authenticated API requests.

On macOS/Linux, activate with `source .venv/bin/activate` and use `export NAME='value'` instead of PowerShell `$env:NAME`. `.env.example` documents settings; `.env` is **not automatically loaded**. `python run.py` selects a psycopg-compatible Windows event loop; Render runs Linux.

Stop local services with `docker compose stop`. The local named PostgreSQL volume preserves data. Nothing writes runtime accounts or neural policies to Render's filesystem.

## Tests

Use a **local disposable server**, never Neon production. The test role needs `CREATEDB` permission. Each test creates a random `somas_test_*` database, applies Alembic, and drops only that database afterward.

```powershell
$env:SOMAS_TEST_DATABASE_URL = 'postgresql://somas:local-development-only@127.0.0.1:5432/postgres'
$env:SOMAS_TEST_PAGES_RUNTIME = '1'
python -m pytest -q
npm test
python -m ruff check app tests scripts migrations --select F,E9
python -m ruff format --check app tests scripts migrations
npx wrangler pages functions build functions --outdir .wrangler/pages-build
```

Without `SOMAS_TEST_DATABASE_URL`, database tests are explicitly skipped; that is not a full validation. Node must be on PATH for the live proxy test. CI uses PostgreSQL 17 and Node 22 and runs the API, importer, restart, concurrency, proxy, and migration tests. No paid AI service is used in tests.

`SOMAS_TEST_PAGES_RUNTIME=1` additionally runs the real Wrangler/workerd local runtime against FastAPI/PostgreSQL, including static paths, cookies and CSRF. It requires `npm ci`; without the flag that extra test is explicitly skipped. On Windows, Wrangler also requires the Microsoft Visual C++ runtime. Install the official runtime if workerd exits before startup.

## Preserved features and additions

- Register/login/logout, current session, profile edits, password changes, and revocation of all sessions after password changes.
- Account-scoped organization design, history, exports, specialist directory, reorganization, and inherited specialist weights.
- Manager and specialist neural filters before LLM calls: 7,405 and 7,062 trainable parameters respectively, separate from frozen LLM weights.
- Verified-only supervised SGD training with versioned binary policy snapshots; concurrent conflicting updates return HTTP 409 without losing the winning update.
- PostgreSQL foreign keys and transactions preserve owner/org/agent integrity and roll back incomplete graph creation or training bookkeeping.
- Manager-defined departments and reporting relationships, owner memberships, recorded decisions, training history, and planning conversations.
- Durable database rate limiting, strict Origin checks, secure cookies, CSRF protection, and a secret-authenticated API proxy.

The private owner model remains the active authorization model. Membership rows are created for owners; there is no invitations UI or sharing API. An editor/viewer schema role does not grant access through the existing owner-only APIs.

## API

Existing `/api/auth/*`, `/api/status`, `/api/catalog`, `/api/agents`, `/api/organizations`, run/reorganize/feedback/export routes remain. Additions:

| Route | Purpose |
|---|---|
| `GET /healthz` | Process liveness, without database diagnostics |
| `GET /readyz` | PostgreSQL and schema readiness |
| `GET /api/manager` | Current user's Manager identity and policy version |
| `GET/PATCH /api/organizations/{id}/agents/{agent_id}` | Inspect/edit an owned specialist's task or role |
| `GET /api/organizations/{id}/departments` | Manager-defined departments |
| `GET /api/organizations/{id}/relationships` | Reporting/review relationships |
| `GET /api/organizations/{id}/memberships` | Owner membership records |
| `GET /api/organizations/{id}/decisions` | Manager/worker filter decision records |
| `GET /api/organizations/{id}/conversations` | Recorded planning messages |
| `GET /api/organizations/{id}/feedback` | Training feedback history |

Lists accept `limit=1..100` and `offset=0..10000`. Exports include the organization and up to the latest 100 runs; additional runs are available via the paginated run endpoint. Responses never include password hashes, session hashes, neural weight bytes, or database credentials.

## Existing SQLite data

Back up the v1.1 database and stop writes to it. No legacy database is imported at startup. Remove the old `SOMAS_DB` setting. Apply PostgreSQL schema migrations first, then explicitly run:

```powershell
python scripts/migrate_sqlite_to_postgresql.py path/to/somas_users.db --dry-run
python scripts/migrate_sqlite_to_postgresql.py path/to/somas_users.db --apply
python scripts/migrate_sqlite_to_postgresql.py path/to/somas_users.db --verify
```

The utility opens SQLite read-only, rejects unowned v1.0 data and forged references, preserves IDs/hashed passwords/sessions/binary policies, creates owner memberships and relational graph records, and imports in one transaction. Repeating the same import is safe; conflicting target data aborts without overwriting. Verification compares imported rows and bytes. Imports above 10,000 derived rows require reviewed batching. Historical policy snapshots not present in v1.1 cannot be reconstructed. Stop the backend while importing so sessions and policies do not change during verification.

## Deployment and research limits

Follow [DEPLOY_RENDER_CLOUDFLARE_NEON.md](DEPLOY_RENDER_CLOUDFLARE_NEON.md) for exact free-tier settings and the Alice/Bob restart smoke test. See [ARCHITECTURE.md](ARCHITECTURE.md) for the schema and security boundaries.

The research hypothesis remains unproven: no benchmark establishes that trainable routing outperforms heuristics or LLM-only organization design. Single-example training can overfit. Feedback is supervised, not automatic reinforcement learning from verified business outcomes. Execution is sequential planning, not autonomous graph scheduling.

Email verification, password recovery, shared business invitations, and a production security audit remain absent. Render Free sleeps after idle periods; Neon can suspend idle compute. A cold start is not continuous agent work. Keep optional AI keys unset for free demo use. `auto` organization mode also stays in demo; only explicit `ai` mode invokes a funded API.
