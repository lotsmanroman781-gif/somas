# SOMAS v1.3 — Native Vercel backend

Unreleased source upgrade, October 21, 2026. No public deployment, hosted migration or new cloud resources were created.

- Kept the existing FastAPI application, authentication, owner isolation, Manager/specialist agents, demo execution, NumPy training and PostgreSQL schema.
- Added native FastAPI configuration, Python 3.12 selection and runtime bundle exclusions; removed the Render deployment manifest. Cloudflare remains the frontend host.
- Switched the gateway to `BACKEND_ORIGIN` plus an exact `APPROVED_BACKEND_HOSTNAME` pin. Cookies, CSRF, origin checks, gateway authentication and SSRF defenses remain.
- Vercel uses NullPool with the Neon external pooler; startup validates schema without migrating. Secure cookies and gateway configuration are mandatory under Vercel.
- Added a disabled-by-default, manually dispatched migration workflow with reviewed main SHA, explicit confirmation and encrypted repository secret. GitHub Free private repository independent approval limitations are documented.
- Added serverless cold/warm/restart tests, schema fail-closed checks, isolated native imports and a runtime dependency size/import preflight, also configured in Linux CI.
- Added the v1.3 deployment guide and retained the v1.2 Render guide as a clearly marked historical reference.

Validation: **44 Python tests passed** against disposable local PostgreSQL 17.5, including real Wrangler/workerd, live proxy authentication, migrations, restart persistence and Vercel lifecycle cases. Six standalone JavaScript contract tests passed; the optional live case is exercised by the Python integration suite. Pages Function compilation and Ruff checks passed. The local Windows/Python 3.12 staged runtime measured **106.1 MiB** and passed native imports. Actual Linux Vercel packaging, account settings and hosted browser acceptance remain deployment-time checks; no hosted environment was accessed.

## SOMAS v1.2 — PostgreSQL deployment upgrade

Unreleased source upgrade, October 20, 2026. No public deployment or cloud resources were created.

- Replaced SQLite persistence and the unfinished MongoDB adaptation with PostgreSQL, SQLAlchemy 2.x async sessions and psycopg 3. Added frozen Alembic schema migrations with serialized startup migration execution.
- Added relational users/sessions, organizations/memberships, Manager-defined departments/relationships, owned agents/config JSONB, binary neural policies and immutable versions, runs, feedback, conversations, decisions and audit logs.
- Preserved v1.1 registration/login/logout/profile/password behavior, owner-based 404 isolation, Manager team design, NumPy filters, verified-only training, demo drafts, exports and inherited specialist policies.
- Added transactional graph/run/training persistence and version-based conflict detection. Added durable auth/request limits, strict Origin/body checks and sanitized failures.
- Moved the existing dashboard to `frontend/`, retained its design/escaping, and added the same-origin Pages Function proxy with secure cookie/CSRF forwarding and a shared backend gateway secret.
- Added Render Free, local PostgreSQL Compose, Cloudflare settings examples, CI, an explicit idempotent v1.1 SQLite importer, and a free-tier Neon/Render/Pages deployment guide.
- Added inspection/edit APIs for owned specialists and inspection APIs for departments, relationships, memberships, conversations, decisions and feedback.
- `auto` design mode now remains demo even if an AI key exists. Only explicit AI mode invokes the optional paid API.

Validation: **37 Python tests passed** against PostgreSQL 17.5, including migration/import/restart/concurrency tests and a live FastAPI-to-Pages proxy roundtrip. The actual Wrangler/workerd runtime also passed static asset, registration, cookie, CSRF, profile and logout checks. Six standalone JavaScript proxy contract tests passed (their optional live case is exercised by the Python integration suite). Pages Functions compilation, Ruff, formatting, and dependency checks passed. Hosted Cloudflare/Render/Neon acceptance still requires account configuration and the documented browser smoke test. No benchmark superiority, real business execution, automatic reinforcement learning, shared-workspace invitation flow, email verification/recovery, or production security certification is claimed.

## Previous v1.1

Added private human accounts, opaque hashed sessions, CSRF defenses, independently owned neural policies and the My Agents dashboard. The legacy SQLite database is never automatically claimed by a new user. v1.2 leaves source SQLite files untouched and imports only explicitly authorized, owned v1.1 records.
