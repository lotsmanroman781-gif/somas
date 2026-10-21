# SOMAS v1.2 — PostgreSQL deployment upgrade

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
